"""che168.com listing collector.

Strategy:
  - Visit /{city_slug}/list/ pages (playwright — bypasses JS anti-bot challenge)
  - Each page has up to 58 `<li class="cards-li">` with all metadata in attrs
  - Filter in Python: year ≥ MIN_YEAR, mileage ≤ MAX_MILEAGE_KM, price ≥ MIN_PRICE_CNY
  - Save to pending_ids with metadata

URL structure:
  https://www.che168.com/{city_slug}/list/?ms={min_year}&pvareaid=102179
  Pagination: append &page=2,3,...

Card attrs (in HTML):
  infoid / brandid / seriesid / specid / dealerid / carname / price (万元) /
  milage (万公里) / regdate (YYYY/MM) / publicdate (ISO) / cid / pid / cartype

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any

from playwright.sync_api import sync_playwright

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "che168"
BASE_URL = "https://www.che168.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 6 biggest cities. che168 uses pinyin slugs.
CITIES = {
    "Beijing":    {"slug": "beijing",   "cid": "110100"},
    "Shanghai":   {"slug": "shanghai",  "cid": "310100"},
    "Guangzhou":  {"slug": "guangzhou", "cid": "440100"},
    "Shenzhen":   {"slug": "shenzhen",  "cid": "440300"},
    "Chengdu":    {"slug": "chengdu",   "cid": "510100"},
    "Hangzhou":   {"slug": "hangzhou",  "cid": "330100"},
}


def build_listing_url(city_slug: str, page: int, min_year: int) -> str:
    """che168 listing URL — year filter via ?ms=, pagination via ?page=."""
    base = f"{BASE_URL}/{city_slug}/list/"
    qs = [f"ms={min_year}", "pvareaid=102179"]
    if page > 1:
        qs.append(f"page={page}")
    return base + "?" + "&".join(qs)


EXTRACT_CARDS_JS = r"""() => {
    const out = [];
    for (const li of document.querySelectorAll('li.cards-li')) {
        const get = (k) => li.getAttribute(k);
        out.push({
            infoid:     get('infoid'),
            brandid:    get('brandid'),
            seriesid:   get('seriesid'),
            specid:     get('specid'),
            dealerid:   get('dealerid'),
            carname:    get('carname'),
            price:      get('price'),
            milage:     get('milage'),
            regdate:    get('regdate'),
            publicdate: get('publicdate'),
            cid:        get('cid'),
            pid:        get('pid'),
            cartype:    get('cartype'),
            href:       li.querySelector('a.carinfo')?.getAttribute('href') || '',
        });
    }
    return out;
}"""


def fetch_page(page, url: str) -> list[dict]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1500)
        # Sometimes JS anti-bot reloads after a moment — give it space
        page.wait_for_timeout(800)
    except Exception as e:
        print(f"    goto failed: {str(e)[:120]}")
        return []
    try:
        return page.evaluate(EXTRACT_CARDS_JS) or []
    except Exception as e:
        print(f"    extract failed: {str(e)[:120]}")
        return []


def card_passes_filters(card: dict, min_year: int, max_mileage_km: int,
                        min_price_cny: int) -> tuple[bool, str]:
    """Return (passes, reason_if_not)."""
    # Year (from regdate YYYY/MM)
    rd = card.get("regdate") or ""
    m = re.match(r"(\d{4})", rd)
    if not m:
        return False, "no regdate"
    year = int(m.group(1))
    if year < min_year:
        return False, f"year {year} < {min_year}"

    # Mileage: che168 attr is in 万公里 (10,000 km)
    try:
        mileage_wan = float(card.get("milage") or 0)
        mileage_km = mileage_wan * 10_000
    except ValueError:
        return False, "bad mileage"
    if mileage_km > max_mileage_km:
        return False, f"mileage {mileage_km:.0f}km > {max_mileage_km}"

    # Price: in 万元 (10,000 CNY)
    try:
        price_wan = float(card.get("price") or 0)
        price_cny = price_wan * 10_000
    except ValueError:
        return False, "bad price"
    if price_cny < min_price_cny:
        return False, f"price {price_cny:.0f} < {min_price_cny}"

    return True, ""


def build_detail_url(card: dict) -> str:
    href = card.get("href") or ""
    if not href:
        return f"{BASE_URL}/dealer/{card.get('dealerid')}/{card.get('infoid')}.html"
    if href.startswith("http"):
        return href
    return BASE_URL + href


def upsert_pending(card: dict) -> bool:
    sku = card.get("infoid")
    if not sku:
        return False
    rec = {
        "source": SOURCE,
        "source_id": str(sku),
        "metadata": {
            "url": build_detail_url(card),
            "brandid": card.get("brandid"),
            "seriesid": card.get("seriesid"),
            "specid": card.get("specid"),
            "dealerid": card.get("dealerid"),
            "carname": card.get("carname"),
            "price_cny": float(card.get("price") or 0) * 10_000,
            "mileage_km": float(card.get("milage") or 0) * 10_000,
            "regdate": card.get("regdate"),
            "publicdate": card.get("publicdate"),
            "cid": card.get("cid"),
            "pid": card.get("pid"),
            "cartype": card.get("cartype"),
        },
        "found_at": DB.now_iso(),
    }
    return DB.upsert_pending(rec)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", type=str,
                    default=",".join(CITIES.keys()),
                    help="Comma-separated city keys")
    ap.add_argument("--pages-per-city", type=int, default=30)
    ap.add_argument("--min-year", type=int, default=2020)
    ap.add_argument("--max-mileage-km", type=int, default=100_000)
    ap.add_argument("--min-price-cny", type=int, default=5_000)
    ap.add_argument("--limit", type=int, default=10_000,
                    help="Cap on total upserts")
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    invalid = [c for c in cities if c not in CITIES]
    if invalid:
        sys.exit(f"Unknown: {invalid}. Available: {list(CITIES.keys())}")

    print(f"Collecting che168: {len(cities)} cities × ≤{args.pages_per_city} pages")
    print(f"  filters: year≥{args.min_year}, mileage≤{args.max_mileage_km:,}km, "
          f"price≥¥{args.min_price_cny:,}")
    print(f"  cap: {args.limit:,} pending upserts\n")

    saved = 0
    skipped = {"filtered": 0, "duplicate": 0, "bad_row": 0}
    started = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=UA, locale="zh-CN", ignore_https_errors=True,
            viewport={"width": 1366, "height": 900},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        for city in cities:
            city_meta = CITIES[city]
            print(f"\n[{city}] slug={city_meta['slug']} cid={city_meta['cid']}")
            seen_in_city = 0
            for page_num in range(1, args.pages_per_city + 1):
                if saved >= args.limit:
                    print(f"  reached cap {args.limit}")
                    break
                url = build_listing_url(city_meta["slug"], page_num, args.min_year)
                cards = fetch_page(page, url)
                if not cards:
                    print(f"  [{city} p{page_num}] no cards — stop")
                    break

                page_saved = 0
                for c in cards:
                    ok, reason = card_passes_filters(
                        c, args.min_year, args.max_mileage_km, args.min_price_cny)
                    if not ok:
                        skipped["filtered"] += 1
                        continue
                    if upsert_pending(c):
                        saved += 1
                        page_saved += 1
                        seen_in_city += 1
                    else:
                        skipped["bad_row"] += 1

                elapsed = int(time.time() - started)
                print(f"  [{city} p{page_num}]  {len(cards)} cards → "
                      f"{page_saved} kept (city total {seen_in_city}, "
                      f"all {saved}, {elapsed}s)")
                if len(cards) < 10:  # last page (usually)
                    break

        browser.close()

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s.")
    print(f"  Pending upserted: {saved}")
    print(f"  Filtered out: {skipped['filtered']}  bad: {skipped['bad_row']}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
