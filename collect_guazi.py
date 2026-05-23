"""guazi.com listing collector — direct HTTP, $0.

Strategy:
  - Visit /{city_slug}/buy/ pages (redirects to /{city_slug}/)
  - HTML has 400 `.car-item` blocks; each has detail URL, title, price, year, mileage, badges
  - Filter in Python: year ≥ MIN_YEAR, mileage ≤ MAX_MILEAGE_KM, price ≥ MIN_PRICE_CNY
  - Save to pending_ids with metadata

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any

import requests
from playwright.sync_api import sync_playwright

import db as DB
from chinese_maps import CITY_MAP

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi"
BASE_URL = "https://www.guazi.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.guazi.com/",
}

CITIES = {
    "Beijing":    "bj",
    "Shanghai":   "sh",
    "Guangzhou":  "gz",
    "Shenzhen":   "sz",
    "Chengdu":    "cd",
    "Hangzhou":   "hz",
}


def build_listing_url(city_slug: str, path_suffix: str = "") -> str:
    """City homepage or city/brand subpage. Pagination (`/o2/`) triggers captcha;
    iterate brand-by-brand instead for breadth.
    """
    path_suffix = path_suffix.strip("/")
    if path_suffix:
        return f"{BASE_URL}/{city_slug}/{path_suffix}/"
    return f"{BASE_URL}/{city_slug}/"


BRAND_HREF_RE = re.compile(r'href="/([a-z]+)/([a-z0-9_-]+)/?"')


def _diagnose_empty(city_slug: str, url: str, homepage_html: str) -> None:
    """Dump everything we can about an empty homepage so we can tell whether
    Guazi changed HTML / WAF blocked us / proxy creds are missing without
    re-running CI 3 times."""
    head = homepage_html[:1500] if homepage_html else "<empty>"
    title = ""
    m = re.search(r"<title>(.*?)</title>", homepage_html or "", re.DOTALL)
    if m:
        title = m.group(1).strip()[:120]
    # Pull every href="/.../.../" pattern, not just the brand filter — so we
    # can see what links the page actually exposes today.
    all_hrefs = re.findall(r'href="(/[a-zA-Z0-9_./-]+/)"', homepage_html or "")
    sample_hrefs = sorted(set(all_hrefs))[:20]
    print(
        "  ⚠ DIAGNOSE [guazi/{slug}] {url}\n"
        "    OXY creds present: {oxy}\n"
        "    Direct Playwright fallback: {pw}\n"
        "    HTML length: {ln}\n"
        "    <title>: {title!r}\n"
        "    sample hrefs ({n}/{tot}): {hrefs}\n"
        "    HTML preview:\n{preview}\n"
        "    ---end preview---".format(
            slug=city_slug, url=url,
            oxy=bool(OXY_USER and OXY_PASS),
            pw=not (OXY_USER and OXY_PASS),
            ln=len(homepage_html or ""), title=title,
            n=len(sample_hrefs), tot=len(all_hrefs),
            hrefs=sample_hrefs,
            preview=head,
        ),
        flush=True,
    )


def discover_brand_paths(city_slug: str, homepage_html: str) -> list[str]:
    """Pull all /{city}/{brand}/ URLs from the city homepage navigation."""
    brands: set[str] = set()
    for city_part, brand_part in BRAND_HREF_RE.findall(homepage_html):
        if city_part != city_slug:
            continue
        if brand_part in {"buy", "sell", "trade", "tag", "list", "search",
                           "rank", "sortvalue", "ranklist", "huishou"}:
            continue
        brands.add(brand_part)
    return sorted(brands)


HREF_RE  = re.compile(r'href="(/car-detail/c(\d+)\.html)"')
ALT_RE   = re.compile(r'alt="([^"]+)"')
PHOTO_RE = re.compile(r'src="(https?://[^"?]+)')
DESC_RE  = re.compile(r'<div class="car-item-info-desc">(.+?)</div>', re.DOTALL)
TAGS_RE  = re.compile(r'<div class="car-item-info-tag">(.+?)</div>\s*<div', re.DOTALL)
PRICE_RE = re.compile(r'<span class="car-item-info-price-value">([\d.]+)</span>')


def extract_cards(html: str) -> list[dict]:
    """Split HTML on `<div class="car-item">` and parse each block individually."""
    chunks = html.split('<div class="car-item ">')[1:]
    out: list[dict] = []
    for chunk in chunks:
        # Cards are ~2KB; cap defensively so regex stays fast
        block = chunk[:3000]

        href = HREF_RE.search(block);    alt = ALT_RE.search(block)
        photo = PHOTO_RE.search(block);  desc = DESC_RE.search(block)
        tags_m = TAGS_RE.search(block);  price = PRICE_RE.search(block)
        if not (href and alt and desc and price):
            continue

        # Desc contains HTML comments `<!-- -->` between segments — strip them
        desc_text = re.sub(r"<[^>]+>", "", desc.group(1))
        d_parts = [p.strip() for p in desc_text.split("|") if p.strip()]
        year = mileage_km = city = None
        for p in d_parts:
            ym = re.search(r"(\d{4})\s*年", p)
            if ym:
                year = int(ym.group(1)); continue
            km = re.search(r"([\d.]+)\s*万\s*公里", p)
            if km:
                mileage_km = int(float(km.group(1)) * 10_000); continue
            if re.search(r"[一-龥]", p):
                # Translate Chinese city → English so downstream cars.city is clean.
                city = CITY_MAP.get(p, p)
        tags = re.findall(r"<span[^>]*>([^<]+)</span>",
                          tags_m.group(1) if tags_m else "")
        out.append({
            "url": BASE_URL + href.group(1),
            "clue_id": href.group(2),
            "title": alt.group(1),
            "thumb_url": photo.group(1) if photo else None,
            "year": year,
            "mileage_km": mileage_km,
            "city": city,
            "tags": tags,
            "price_cny": int(float(price.group(1)) * 10_000),
        })
    return out


def card_passes_filters(card: dict, min_year: int, max_mileage_km: int,
                        min_price_cny: int) -> tuple[bool, str]:
    if not card.get("year") or card["year"] < min_year:
        return False, f"year {card.get('year')} < {min_year}"
    if not card.get("mileage_km") or card["mileage_km"] > max_mileage_km:
        return False, f"mileage {card.get('mileage_km')} > {max_mileage_km}"
    if not card.get("price_cny") or card["price_cny"] < min_price_cny:
        return False, f"price {card.get('price_cny')} < {min_price_cny}"
    return True, ""


def upsert_pending(card: dict) -> bool:
    rec = {
        "source": SOURCE,
        "source_id": str(card["clue_id"]),
        "metadata": {
            "url":       card["url"],
            "title":     card["title"],
            "thumb_url": card.get("thumb_url"),
            "year":      card.get("year"),
            "mileage_km": card.get("mileage_km"),
            "price_cny": card.get("price_cny"),
            "city":      card.get("city"),
            "tags":      card.get("tags"),
        },
        "found_at": DB.now_iso(),
    }
    return DB.upsert_pending(rec)


_PW = None
_BROWSER = None
_CTX = None
_PAGE = None
_REQUESTS_THIS_SESSION = 0


def _start_session():
    """Start (or restart) a fresh browser context."""
    global _PW, _BROWSER, _CTX, _PAGE, _REQUESTS_THIS_SESSION
    if _BROWSER:
        try: _BROWSER.close()
        except Exception: pass
        _BROWSER = _CTX = _PAGE = None
    if _PW is None:
        _PW = sync_playwright().start()
    _BROWSER = _PW.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    _CTX = _BROWSER.new_context(
        user_agent=UA, locale="zh-CN", ignore_https_errors=True,
        viewport={"width": 1366, "height": 900},
    )
    _CTX.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    _PAGE = _CTX.new_page()
    _REQUESTS_THIS_SESSION = 0


def _ensure_page():
    if _PAGE is None:
        _start_session()
    return _PAGE


OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"


def _oxylabs_fetch(url: str) -> str | None:
    """Fetch a guazi page via Oxylabs (China geo).
    GitHub runners are US-based and guazi 301-redirects them to en.guazi.com,
    so direct fetch / Playwright both return the English placeholder.
    """
    payload = {
        "source": "universal", "url": url,
        "geo_location": "China", "locale": "zh-CN", "render": "html",
    }
    for attempt in range(3):
        try:
            r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                              json=payload, timeout=120)
            if r.status_code != 200:
                time.sleep(2 ** attempt); continue
            results = r.json().get("results") or []
            if not results:
                time.sleep(2 ** attempt); continue
            content = results[0].get("content") or ""
            if len(content) < 5000:
                time.sleep(2 ** attempt); continue
            head = content[:3000].lower()
            if ("captcha" in head or "<title>验证</title>" in content[:3000]
                    or "请完成下方验证" in content[:3000]):
                time.sleep(2 ** attempt); continue
            return content
        except Exception:
            time.sleep(2 ** attempt)
    return None


def fetch_html(url: str) -> str | None:
    """Route through Oxylabs when credentials present, else fall back to Playwright
    (useful for local dev from a CN-resolvable network)."""
    if OXY_USER and OXY_PASS:
        return _oxylabs_fetch(url)
    global _REQUESTS_THIS_SESSION
    page = _ensure_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(900)
        _REQUESTS_THIS_SESSION += 1
        if "captcha" in page.url:
            print(f"    ⚠ captcha hit after {_REQUESTS_THIS_SESSION} reqs — restart")
            _start_session()
            return None
        html = page.content()
        if len(html) < 5000:
            return None
        return html
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", type=str, default=",".join(CITIES.keys()))
    ap.add_argument("--pages-per-city", type=int, default=20)
    ap.add_argument("--min-year", type=int, default=2020)
    ap.add_argument("--max-mileage-km", type=int, default=100_000)
    ap.add_argument("--min-price-cny", type=int, default=5_000)
    ap.add_argument("--limit", type=int, default=10_000)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    invalid = [c for c in cities if c not in CITIES]
    if invalid:
        sys.exit(f"Unknown: {invalid}. Available: {list(CITIES.keys())}")

    print(f"Collecting guazi: {len(cities)} cities × ≤{args.pages_per_city} pages")
    print(f"  filters: year≥{args.min_year}, mileage≤{args.max_mileage_km:,}km, "
          f"price≥¥{args.min_price_cny:,}")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    saved = 0
    skipped = 0
    started = time.time()
    # Parallel fetch over Oxylabs: 8 in-flight requests per city.
    WORKERS = 8 if (OXY_USER and OXY_PASS) else 1

    for city in cities:
        slug = CITIES[city]
        print(f"\n[{city}] /{slug}/")

        url_home = build_listing_url(slug)
        homepage = fetch_html(url_home)
        if not homepage:
            print(f"  city homepage empty — skip")
            continue
        brand_paths = discover_brand_paths(slug, homepage)
        print(f"  discovered {len(brand_paths)} brand subpages, "
              f"fetching {WORKERS}-way parallel")
        if len(brand_paths) == 0:
            # Either Guazi changed HTML, WAF is serving a captcha, or we're
            # on the en.guazi.com placeholder because Oxylabs creds are
            # missing. Dump enough context to tell which.
            _diagnose_empty(slug, url_home, homepage)

        seen: set[str] = set()
        # Process homepage cards first
        for c in extract_cards(homepage):
            cid = c["clue_id"]
            if cid in seen: continue
            seen.add(cid)
            ok, _ = card_passes_filters(
                c, args.min_year, args.max_mileage_km, args.min_price_cny)
            if not ok:
                skipped += 1; continue
            if upsert_pending(c):
                saved += 1

        # Fetch all brand subpages in parallel
        urls = [(p, build_listing_url(slug, p)) for p in brand_paths]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_html, u): p for p, u in urls}
            for fut in as_completed(futures):
                if saved >= args.limit: break
                path = futures[fut]
                try: html = fut.result()
                except Exception: html = None
                if not html: continue
                cards = extract_cards(html)
                page_saved = 0
                for c in cards:
                    cid = c["clue_id"]
                    if cid in seen: continue
                    seen.add(cid)
                    ok, _ = card_passes_filters(
                        c, args.min_year, args.max_mileage_km, args.min_price_cny)
                    if not ok:
                        skipped += 1; continue
                    if upsert_pending(c):
                        saved += 1; page_saved += 1
                elapsed = int(time.time() - started)
                print(f"  [{path[:25]:25}] {len(cards):>3} cards → {page_saved:>3} kept"
                      f" (city {len(seen)}, all {saved}, {elapsed}s)")

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. Upserted: {saved}, filtered: {skipped}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
