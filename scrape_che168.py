"""che168 detail-page scraper.

Pulls one car at a time via playwright (JS anti-bot challenge).
Extracts ALL fields including VIN, trust badges, photos in HD.

Usage:
    python scrape_che168.py [--limit 1000] [--workers 4]

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from playwright.sync_api import sync_playwright

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "che168"
SOURCE_LANGUAGE = "zh"
PRICE_CURRENCY = "CNY"
KM_AGE_UNIT = "km"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

BASE_URL = "https://www.che168.com"

# che168 photos: replace `{w}x{h}_0_q87_c42_` with HD variant
PHOTO_HD_TARGET = "1024x768"

from chinese_maps import (
    BRAND_MAP, COLOR_MAP, FUEL_MAP, TRANSMISSION_MAP, DRIVE_MAP, CITY_MAP,
    SERIES_MAP, SERIES_SUFFIX_NOISE,
)


_SERIES_SUFFIX_EN = {
    "新能源": " EV", "进口": "", "插电混动": " PHEV",
    "插电式混合动力": " PHEV", "混动": " Hybrid",
    "PHEV": " PHEV", "EV": " EV",
}


def translate_series(s: str) -> str:
    """Chinese model name → English via SERIES_MAP.

    Order matters: try full string first (so combined keys like 宏光MINIEV
    take precedence), then strip a known suffix and translate the stem.
    """
    if not s:
        return ""
    s = s.strip()
    direct = SERIES_MAP.get(s)
    if direct:
        return direct
    for tag in SERIES_SUFFIX_NOISE:
        if s.endswith(tag) and len(s) > len(tag):
            stem = s[: -len(tag)].strip()
            stem_en = SERIES_MAP.get(stem, stem)
            return (stem_en + _SERIES_SUFFIX_EN.get(tag, "")).strip()
    return s


def tr(value: str, mapping: dict[str, str]) -> str:
    if not value:
        return ""
    return mapping.get(value.strip(), value.strip())


def upgrade_photo(url: str) -> str:
    """720x540 → 1024x768 (sharper, ~2x area, still cheap to load)."""
    return re.sub(r"/\d+x\d+_0_q\d+_", f"/{PHOTO_HD_TARGET}_0_q87_", url)


def parse_int(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except ValueError:
        return None


def parse_year_month(s: str | None) -> tuple[int | None, str | None]:
    """Parse '2022年03月' → (2022, '2022-03-01')."""
    if not s:
        return None, None
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", s)
    if not m:
        m2 = re.search(r"(\d{4})[/-](\d{1,2})", s)
        if not m2:
            return None, None
        y, mo = m2.group(1), m2.group(2)
    else:
        y, mo = m.group(1), m.group(2)
    return int(y), f"{y}-{int(mo):02d}-01"


def parse_mileage_km(s: str | None) -> int | None:
    """'6.8万公里' → 68000."""
    if not s:
        return None
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        return int(float(m.group(1)) * 10_000)
    m = re.search(r"([\d.]+)\s*(?:公里|km)", s, re.IGNORECASE)
    if m:
        return int(float(m.group(1)))
    return None


def parse_price_cny(s: str | None) -> int | None:
    """'26.80万' or '￥26.80万' → 268000 CNY. Returns None if no `万` marker
    (refuse to guess from arbitrary digit-strings — title-text would otherwise
    merge year/spec/price digits into a single huge number)."""
    if not s:
        return None
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        return int(float(m.group(1)) * 10_000)
    # Title-only-fallback: look for `_<X.YYYY>_` pattern (che168 uses this in <title>)
    m2 = re.search(r"_([\d.]+)_(?:.{0,6}二手车)", s)
    if m2:
        return int(float(m2.group(1)) * 10_000)
    return None


VIN_RE = re.compile(r"\b([A-HJ-NPR-Z][A-HJ-NPR-Z0-9]{16})\b")


def extract_vin(html: str) -> str | None:
    """Find a plausible VIN in the page. Filter hex-only hashes."""
    for m in VIN_RE.finditer(html):
        v = m.group(1)
        if re.fullmatch(r"[A-F0-9]+", v):  # hex hash
            continue
        # Real VIN should have at least one number AND one letter NOT in A-F
        if re.search(r"[G-NPR-Z]", v):
            return v
    return None


TRUST_BADGES = [
    "认证二手车", "精选好车", "无重大事故", "事故车", "泡水车",
    "30天整车保修", "7天无理由", "15天包退", "30天包退",
    "180天质保", "1年质保", "原版漆", "一手车", "原厂质保",
    "111项", "里程核实", "VIN核实",
]


def extract_trust_badges(html: str) -> dict[str, int]:
    return {b: html.count(b) for b in TRUST_BADGES if html.count(b) > 0}


SPEC_FIELDS = {
    "regdate_text":     r"上牌时间[\s\S]{0,80}?(\d{4}\s*年\s*\d{1,2}\s*月)",
    "mileage_text":     r"表显里程[\s\S]{0,80}?([\d.]+\s*万?\s*公里)",
    "transfers_text":   r"过户次数[\s\S]{0,80}?(\d+)\s*次",
    "color":            r"车身颜色[\s\S]{0,120}?([一-龥]{1,8}色)",
    "drive_type_zh":    r"驱动方式[\s\S]{0,120}?([一-龥]{2,12})",
    "transmission_zh":  r"变速箱[\s\S]{0,120}?([一-龥A-Za-z]{1,10})",
    "fuel_zh":          r"燃料类型[\s\S]{0,120}?([一-龥]{1,8})",
    "emission":         r"排放标准[\s\S]{0,120}?(国\s*[一-龥VI]{1,5})",
    "displacement":     r"排量[\s\S]{0,80}?([\d.]+\s*[TL])",
    "battery_score":    r"电池评分[\s\S]{0,40}?(\d+)\s*分",
    "battery_health":   r"电池容量保持率[\s\S]{0,40}?([\d.]+%)",
    "battery_capacity": r"电池容量[\s\S]{0,40}?([\d.]+\s*kWh)",
    "ev_range":         r"新车续航[\s\S]{0,40}?(\d+)\s*km",
    "dealer_address":   r"地址[:]\s*([一-龥A-Za-z0-9·\s]{8,80})",
    "title":            r"<title>([^<]+)</title>",
}


def extract_specs(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, pat in SPEC_FIELDS.items():
        m = re.search(pat, html)
        if m:
            out[k] = m.group(1).strip()
    return out


def extract_photos(html: str) -> list[str]:
    """Real car photos sit on `2sc2.autoimg.cn/escimg/...` and are templated
    `<size>_0_q87_c42_autohomecar__<HASH>.<ext>`. Ads / promo banners use the
    `adm*.autoimg.cn/admdfs/` path and look like `0x0_autohomecar__...` — must
    be excluded or every listing gets the same generic ad image."""
    raw = re.findall(
        r"(?:https?:)?//[\w.-]*autoimg\.cn/[^\"'\s<>)]+?\.(?:jpg|webp)", html)
    seen_hash: set[str] = set()
    out: list[str] = []
    for u in raw:
        url = u if u.startswith("http") else "https:" + u
        # 1. Reject ad subdomains/paths
        if "/admdfs/" in url or "adm" in url.split("//")[1].split("/")[0]:
            continue
        # 2. Must be the dealer-photo template (escimg + <size>_0_q87_c42_)
        if "/escimg/" not in url or "_q87_c42_" not in url:
            continue
        m = re.search(r"autohomecar__(\w+?)\.(?:jpg|webp)", url)
        if not m:
            continue
        h = m.group(1)
        if h in seen_hash:
            continue
        seen_hash.add(h)
        out.append(upgrade_photo(url))
    return out


CITY_BY_CID = {
    "110100": "Beijing",   "310100": "Shanghai",  "440100": "Guangzhou",
    "440300": "Shenzhen",  "510100": "Chengdu",   "330100": "Hangzhou",
}


def parse_card(html: str, meta: dict, sku_id: str) -> dict | None:
    """Map HTML + listing metadata to our cars row."""
    specs = extract_specs(html)
    badges = extract_trust_badges(html)
    photos = extract_photos(html)
    vin = extract_vin(html)

    # year = model year (from "2024款" in carname), reg_date = registration date
    _, reg_iso = parse_year_month(
        specs.get("regdate_text") or meta.get("regdate"))
    year_match = re.search(r"(\d{4})\s*款", carname)
    if year_match:
        year = int(year_match.group(1))
    else:
        # Fall back to registration year if no "XXXX款" pattern
        year, _ = parse_year_month(
            specs.get("regdate_text") or meta.get("regdate"))
    mileage_km = (parse_mileage_km(specs.get("mileage_text"))
                  or int(meta.get("mileage_km") or 0) or None)
    # Prefer listing metadata (`万` × 10_000 already computed at collect time)
    price_cny = int(meta.get("price_cny") or 0) or None
    if not price_cny:
        price_cny = parse_price_cny(specs.get("title", ""))

    carname = meta.get("carname") or ""
    # Brand: first space-separated token of carname (e.g. "宝马5系 2022款...")
    brand_zh = ""
    series_zh = ""
    if carname:
        # carname is like "宝马5系 2022款 530Li 尊享型 M运动套装"
        parts = carname.split(" ", 1)
        series_zh = parts[0]
        # Try to find the Chinese brand prefix (longest match first)
        sorted_prefixes = sorted(BRAND_MAP, key=len, reverse=True)
        for prefix in sorted_prefixes:
            if series_zh.startswith(prefix):
                brand_zh = prefix
                series_zh = series_zh[len(prefix):]
                break
        # series may still start with a (shorter) brand prefix
        for prefix in sorted_prefixes:
            if series_zh.startswith(prefix):
                series_zh = series_zh[len(prefix):]
                break

    mark_en = tr(brand_zh, BRAND_MAP) or brand_zh or ""
    # series cleaned: replace 系/级, then translate via SERIES_MAP if possible
    series_en = series_zh.replace("系", " Series").replace("级", " Class").strip()
    series_en = translate_series(series_en) or series_en

    # Drive / transmission / fuel — translate
    drive_zh = specs.get("drive_type_zh", "")
    trans_zh = specs.get("transmission_zh", "")
    fuel_zh = specs.get("fuel_zh", "")

    transfers = parse_int(specs.get("transfers_text"))

    detail_url = (meta.get("url")
                  or f"{BASE_URL}/dealer/{meta.get('dealerid')}/{sku_id}.html")
    publicdate = meta.get("publicdate")

    city_name = CITY_BY_CID.get(meta.get("cid") or "")
    city_zh = next((zh for zh, en in CITY_MAP.items() if en == city_name), "")

    source_data = {
        "trust_badges":    badges,
        "transfers":       transfers,
        "emission":        specs.get("emission"),
        "battery_score":   parse_int(specs.get("battery_score")),
        "battery_health":  specs.get("battery_health"),
        "battery_capacity": specs.get("battery_capacity"),
        "ev_range_km":     parse_int(specs.get("ev_range")),
        "displacement":    specs.get("displacement"),
        "dealer_address":  specs.get("dealer_address"),
        "dealer_id":       meta.get("dealerid"),
        "brand_id_che168": meta.get("brandid"),
        "series_id_che168": meta.get("seriesid"),
        "spec_id_che168":  meta.get("specid"),
    }
    source_data = {k: v for k, v in source_data.items() if v is not None}

    ts = DB.now_iso()
    return {
        "source": SOURCE,
        "source_id": str(sku_id),
        "source_language": SOURCE_LANGUAGE,
        "url": detail_url,
        "title": carname,

        "mark_original": brand_zh or None,
        "mark": mark_en or None,
        "series_original": series_zh or None,
        # Model is bare series (without brand) — frontend renders mark separately
        "model": series_en or carname,
        "complectation": " ".join(carname.split(" ")[1:]) if " " in carname else None,
        "year": year,
        "reg_date": reg_iso,

        "price_original": price_cny,
        "price_currency": PRICE_CURRENCY,

        "km_age_original": mileage_km,
        "km_age_unit": KM_AGE_UNIT,
        "km_age": mileage_km,

        "color_original": specs.get("color"),
        "color": tr(specs.get("color", ""), COLOR_MAP) or None,

        "body_type": None,  # not exposed by che168 detail simply
        "engine_type": tr(fuel_zh, FUEL_MAP) or None,
        "fuel_original": fuel_zh or None,
        "transmission_original": trans_zh or None,
        "transmission_type": tr(trans_zh, TRANSMISSION_MAP) or None,
        "drive_type": tr(drive_zh, DRIVE_MAP) or None,
        "drive_original": drive_zh or None,

        "city_original": city_zh or None,
        "city": city_name or None,

        "vin": vin,

        "images": photos,
        "image_count": len(photos),

        "source_data": source_data,
        "published_at": publicdate,
        "first_seen": ts,
        "last_seen": ts,
    }


# ────────── per-worker browser context ──────────

class WorkerCtx:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.ctx = None
        self.page = None

    def __enter__(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self.ctx = self.browser.new_context(
            user_agent=UA, locale="zh-CN", ignore_https_errors=True,
            viewport={"width": 1366, "height": 900},
        )
        self.ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        self.page = self.ctx.new_page()
        return self.page

    def __exit__(self, *_):
        try:
            self.browser.close()
        finally:
            self.pw.stop()


def fetch_detail_html(page, url: str) -> str | None:
    """Fetch detail page. Handles anti-bot JS-challenge + lazy-loaded photos.

    che168 lazy-loads autoimg.cn photos via JS after DOMContentLoaded — if we
    grab content() too early there are no image URLs in the DOM yet. We MUST
    wait for them; if they never appear, the page is likely the anti-bot shim
    or a half-loaded state — retry.
    """
    for attempt in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(800)
            # Wait for at least one autoimg URL — required for a valid scrape
            try:
                # Wait for REAL car photos (escimg subpath), not just any autoimg.cn ref
                page.wait_for_function(
                    "() => /escimg\\/[^\"\\']+autohomecar/.test("
                    "document.documentElement.outerHTML)",
                    timeout=14000,
                )
                html = page.content()
                if len(html) > 5000:
                    return html
            except Exception:
                # photos didn't load — let it settle, retry
                page.wait_for_timeout(3000)
        except Exception as e:
            if attempt == 2:
                print(f"      goto err: {str(e)[:120]}")
            page.wait_for_timeout(2500)
    return None


def scrape_batch(rows: list[dict]) -> list[tuple[str, bool, str]]:
    """One playwright session per batch — reuse browser across many URLs."""
    results: list[tuple[str, bool, str]] = []
    with WorkerCtx() as page:
        for row in rows:
            sku_id = row["source_id"]
            meta = row.get("metadata") or {}
            url = meta.get("url") or f"{BASE_URL}/dealer/{meta.get('dealerid')}/{sku_id}.html"
            html = fetch_detail_html(page, url)
            if not html or len(html) < 5000:
                results.append((sku_id, False, "tiny/empty page"))
                continue
            rec = parse_card(html, meta, sku_id)
            if not rec:
                results.append((sku_id, False, "parse failed"))
                continue
            ok = DB.upsert_car(rec)
            results.append((sku_id, ok, ""))
    return results


def fetch_pending_rows(limit: int) -> list[dict]:
    """Fetch pending IDs with metadata (which has dealer URL, brand IDs, etc)."""
    r = DB._pg_request(
        "GET",
        f"pending_ids?source=eq.{SOURCE}"
        f"&failed_attempts=lt.{DB.QUARANTINE_THRESHOLD}"
        f"&select=source_id,metadata&limit={limit * 3}",
    )
    if r.status_code != 200:
        print(f"  fetch pending FAIL: {r.text[:200]}")
        return []
    pending = r.json()

    # Drop ones already scraped
    r2 = DB._pg_request("GET", f"cars?source=eq.{SOURCE}&select=source_id")
    scraped = {row["source_id"] for row in r2.json()} if r2.status_code == 200 else set()
    fresh = [p for p in pending if str(p["source_id"]) not in scraped]
    return fresh[:limit]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    pending = fetch_pending_rows(args.limit)
    if not pending:
        print("No pending IDs"); return
    print(f"Scraping {len(pending)} che168 cards with {args.workers} workers"
          f" (batches of 20 per playwright session)")

    BATCH_SIZE = 20
    batches = [pending[i:i+BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]

    ok_count = 0
    fail_count = 0
    started = time.time()
    processed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scrape_batch, b): b for b in batches}
        for fut in as_completed(futs):
            try:
                results = fut.result()
            except Exception:
                traceback.print_exc()
                fail_count += len(futs[fut])
                continue
            for sku_id, ok, err in results:
                processed += 1
                if ok:
                    ok_count += 1
                else:
                    DB.mark_failed(SOURCE, sku_id)
                    fail_count += 1
            elapsed = int(time.time() - started)
            print(f"  batch done: {processed}/{len(pending)} "
                  f"(ok={ok_count}, fail={fail_count}, {elapsed}s)")

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. OK: {ok_count}, FAIL: {fail_count}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
