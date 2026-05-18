"""guazi.com detail-page scraper — via Oxylabs Realtime API.

Guazi blocks both direct HTTP and headless playwright with captcha; Oxylabs
(China geo, render=html) bypasses it cleanly.

Each guazi detail page contains inline JSON (escaped) with detailed inspection
scorecard:
  - 检测等级 (inspection grade)
  - 三电附件检测 / 车身外观 / 内饰及配置 / 车身骨架 / 机舱工况 — issue counts
  - 保险理赔 (insurance claim count)
  - 电池容量 / 新车续航 / 快充 (battery details for EVs)

VIN is NOT exposed (guazi hides until dealer contact).
Photos: image-public.guazistatic.com — append `?x-bce-process=...resize,w_1920,h_1280`
for Full HD.

Env: OXY_USER, OXY_PASS, SUPABASE_URL, SUPABASE_KEY

Usage:
    python scrape_guazi.py [--limit 1000] [--workers 8]
"""

import argparse
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi"
SOURCE_LANGUAGE = "zh"
PRICE_CURRENCY = "CNY"
KM_AGE_UNIT = "km"

BASE_URL = "https://www.guazi.com"

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"
OXY_TIMEOUT = 180
OXY_MAX_RETRIES = 3

# Photo HD: replace `w_330,h_220` (or any small) → 1920x1280
PHOTO_HD_TARGET = "?x-bce-process=image/quality,q_95/resize,m_fill,w_1920,h_1280"

from chinese_maps import (
    BRAND_MAP, COLOR_MAP, FUEL_MAP, TRANSMISSION_MAP, DRIVE_MAP, CITY_MAP,
)


def tr(value: str, mapping: dict[str, str]) -> str:
    if not value:
        return ""
    return mapping.get(value.strip(), value.strip())


def upgrade_photo(url: str) -> str:
    """Strip any existing x-bce-process and add HD variant."""
    base = url.split("?")[0]
    return base + PHOTO_HD_TARGET


def parse_int(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except ValueError:
        return None


def parse_mileage_km(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        return int(float(m.group(1)) * 10_000)
    return parse_int(s)


def parse_yyyymm(s: str | None) -> tuple[int | None, str | None]:
    if not s:
        return None, None
    m = re.match(r"(\d{4})-(\d{1,2})", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return y, f"{y}-{mo:02d}-01"
    m2 = re.match(r"(\d{4})", s)
    if m2:
        return int(m2.group(1)), f"{m2.group(1)}-01-01"
    return None, None


# guazi embeds spec rows in escaped JSON like:
#   \"label\":\"表显里程\",\"value\":\"3.37万公里\"
SPEC_PAIRS_RE = re.compile(
    r'\\"label\\":\\"([^\\]+?)\\",\\"value\\":\\"([^\\]*?)\\"')


def extract_spec_pairs(html: str) -> dict[str, str]:
    """All label:value pairs (Chinese-labeled spec rows)."""
    out: dict[str, str] = {}
    for k, v in SPEC_PAIRS_RE.findall(html):
        # Keep first occurrence
        if k not in out:
            out[k] = v
    return out


def extract_photos(html: str) -> list[str]:
    raw = re.findall(
        r'https?://[\w.-]*\.guazistatic\.com/[^"\'\s<>]+?\.(?:jpg|webp|png)',
        html)
    urls = list(dict.fromkeys(raw))
    # Skip tiny icons (qnbdp106... is a small UI asset prefix)
    car_photos = [u for u in urls
                  if "qnbdp7206x" in u or "qnbdp720" in u or "carpic" in u]
    return [upgrade_photo(u) for u in car_photos]


VERIFIED_BADGES = [
    "已检测", "纯电动", "瓜子认证", "瓜子保", "保养记录", "无事故",
    "无重大事故", "无泡水", "瓜子精选", "瓜子放心购", "已减",
]


def extract_badges(html: str) -> dict[str, int]:
    return {b: html.count(b) for b in VERIFIED_BADGES if html.count(b) > 0}


def parse_card(html: str, meta: dict, clue_id: str) -> dict | None:
    pairs = extract_spec_pairs(html)
    badges = extract_badges(html)
    photos = extract_photos(html)

    # Title from page <title>
    title_m = re.search(r"<title>([^<]+)</title>", html)
    full_title = (title_m.group(1) if title_m
                  else meta.get("title") or "")
    # Title example: "二手哪吒汽车 哪吒N01 2020款 380t 行业定制版报价..."
    short_title = re.sub(r"^二手", "", full_title).split("报价")[0].strip()
    parts = short_title.split(" ", 1) if " " in short_title else [short_title, ""]
    brand_zh = parts[0] if parts else ""
    series_complectation = parts[1] if len(parts) > 1 else ""

    # Resolve brand → English via shared map (longest match first)
    mark_zh = ""
    sorted_prefixes = sorted(BRAND_MAP, key=len, reverse=True)
    for prefix in sorted_prefixes:
        if brand_zh.startswith(prefix):
            mark_zh = prefix
            series_complectation = (brand_zh[len(prefix):]
                                    + " " + series_complectation).strip()
            break
    mark_en = tr(mark_zh, BRAND_MAP) or brand_zh
    # The series often repeats the brand name (e.g. "哪吒汽车 哪吒N01") — strip it too
    for prefix in sorted_prefixes:
        if series_complectation.startswith(prefix):
            series_complectation = series_complectation[len(prefix):].strip()
            break

    series_complectation = series_complectation.strip()
    # First word after brand is usually series
    if " " in series_complectation:
        series_zh, complectation_zh = series_complectation.split(" ", 1)
    else:
        series_zh, complectation_zh = series_complectation, ""

    # year = model year (from "2020款" in title), reg_date = first registration
    _, reg_iso = parse_yyyymm(pairs.get("首次上牌") or pairs.get("上牌时间"))
    year_match = re.search(r"(\d{4})\s*款", short_title)
    if year_match:
        year = int(year_match.group(1))
    else:
        year, _ = parse_yyyymm(pairs.get("首次上牌") or pairs.get("上牌时间"))
    mileage_km = parse_mileage_km(pairs.get("表显里程")) or meta.get("mileage_km")
    transfers = parse_int(pairs.get("过户次数"))
    color_zh = pairs.get("车身颜色", "")
    transmission_zh = pairs.get("变速箱", "")
    drive_zh = pairs.get("驱动方式", "")
    fuel_zh = pairs.get("能源类型") or pairs.get("燃料类型", "")
    displacement = pairs.get("发动机", "")
    emission = pairs.get("排放标准", "")

    # Inspection scorecard fields
    inspection = {
        "grade":           pairs.get("检测等级"),
        "ev_components":   pairs.get("三电附件检测"),
        "body_exterior":   pairs.get("车身外观"),
        "interior":        pairs.get("内饰及配置"),
        "frame":           pairs.get("车身骨架"),
        "engine_bay":      pairs.get("机舱工况"),
        "insurance_claims": pairs.get("保险理赔"),
        "guarantee":       pairs.get("车况保障"),
    }
    inspection = {k: v for k, v in inspection.items() if v}

    # Battery details (EVs)
    battery = {
        "capacity_kwh":     pairs.get("电池容量"),
        "type":             pairs.get("电池类型"),
        "new_range_km":     pairs.get("新车续航"),
        "fast_charge":      pairs.get("快充功能"),
        "fast_charge_time": pairs.get("快充"),
        "drive_motor":      pairs.get("驱动电机"),
    }
    battery = {k: v for k, v in battery.items() if v}

    source_data: dict[str, Any] = {
        "trust_badges":  badges,
        "transfers":     transfers,
        "inspection":    inspection,
        "battery":       battery if battery else None,
        "emission":      emission or None,
        "displacement":  displacement or None,
        "source_city":   pairs.get("车源地"),
        "clue_id":       clue_id,
    }
    source_data = {k: v for k, v in source_data.items() if v is not None}

    detail_url = meta.get("url") or f"{BASE_URL}/car-detail/c{clue_id}.html"
    city_en = meta.get("city")  # listing city (where displayed)
    city_zh = next((zh for zh, en in CITY_MAP.items() if en == city_en), "")

    ts = DB.now_iso()
    return {
        "source": SOURCE,
        "source_id": str(clue_id),
        "source_language": SOURCE_LANGUAGE,
        "url": detail_url,
        "title": short_title,

        "mark_original": mark_zh or brand_zh or None,
        "mark": mark_en or None,
        "series_original": series_zh or None,
        # Model is bare series (without brand) — frontend renders mark separately
        "model": (series_zh.replace("系", " Series")
                           .replace("级", " Class").strip()) or None,
        "complectation": complectation_zh or None,
        "year": year,
        "reg_date": reg_iso,

        "price_original": meta.get("price_cny"),
        "price_currency": PRICE_CURRENCY,

        "km_age_original": mileage_km,
        "km_age_unit": KM_AGE_UNIT,
        "km_age": mileage_km,

        "color_original": color_zh,
        "color": tr(color_zh, COLOR_MAP) or None,
        "engine_type": tr(fuel_zh, FUEL_MAP) or None,
        "fuel_original": fuel_zh or None,
        "transmission_original": transmission_zh or None,
        "transmission_type": tr(transmission_zh, TRANSMISSION_MAP) or None,
        "drive_type": tr(drive_zh, DRIVE_MAP) or None,
        "drive_original": drive_zh or None,

        "city_original": city_zh or None,
        "city": city_en or None,

        "vin": None,  # guazi hides

        "images": photos,
        "image_count": len(photos),

        "source_data": source_data,
        "first_seen": ts,
        "last_seen": ts,
    }


def oxylabs_fetch(url: str) -> str | None:
    """Render guazi detail page through Oxylabs (China geo)."""
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
    }
    for attempt in range(OXY_MAX_RETRIES):
        try:
            r = requests.post(
                OXY_URL, auth=(OXY_USER, OXY_PASS),
                json=payload, timeout=OXY_TIMEOUT,
            )
            if r.status_code != 200:
                time.sleep(2 ** attempt)
                continue
            results = r.json().get("results") or []
            if not results:
                time.sleep(2 ** attempt)
                continue
            content = results[0].get("content") or ""
            if len(content) < 5000:
                time.sleep(2 ** attempt)
                continue
            # Captcha pages are small or contain known markers
            if "captcha" in content[:2000].lower():
                time.sleep(2 ** attempt)
                continue
            return content
        except Exception:
            time.sleep(2 ** attempt)
    return None


def fetch_pending_rows(limit: int) -> list[dict]:
    r = DB._pg_request(
        "GET",
        f"pending_ids?source=eq.{SOURCE}"
        f"&failed_attempts=lt.{DB.QUARANTINE_THRESHOLD}"
        f"&select=source_id,metadata&limit={limit * 3}",
    )
    if r.status_code != 200:
        return []
    pending = r.json()
    r2 = DB._pg_request("GET", f"cars?source=eq.{SOURCE}&select=source_id")
    scraped = {row["source_id"] for row in r2.json()} if r2.status_code == 200 else set()
    return [p for p in pending if str(p["source_id"]) not in scraped][:limit]


def scrape_one(row: dict) -> tuple[str, bool, str]:
    clue_id = row["source_id"]
    meta = row.get("metadata") or {}
    url = meta.get("url") or f"{BASE_URL}/car-detail/c{clue_id}.html"
    html = oxylabs_fetch(url)
    if not html:
        return clue_id, False, "fetch failed"
    rec = parse_card(html, meta, clue_id)
    if not rec:
        return clue_id, False, "parse failed"
    ok = DB.upsert_car(rec)
    return clue_id, ok, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")
    if not OXY_USER or not OXY_PASS:
        sys.exit("Need OXY_USER and OXY_PASS")

    pending = fetch_pending_rows(args.limit)
    if not pending:
        print("No pending IDs"); return
    print(f"Scraping {len(pending)} guazi cards via Oxylabs "
          f"({args.workers} workers)")

    ok_count = 0
    fail_count = 0
    started = time.time()
    processed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scrape_one, r): r for r in pending}
        for fut in as_completed(futs):
            try:
                cid, ok, err = fut.result()
            except Exception:
                traceback.print_exc()
                fail_count += 1
                continue
            processed += 1
            if ok:
                ok_count += 1
            else:
                DB.mark_failed(SOURCE, cid)
                fail_count += 1
            if processed % 25 == 0 or processed == len(pending):
                elapsed = int(time.time() - started)
                print(f"  {processed}/{len(pending)} "
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
