"""
Autocango.com listing ID collector — quality filter strategy.

For KZ-import use case we iterate over the top 6 Chinese export-hub
cities, applying filters that pre-screen for quality:
  - originalPaint=22   (Original Paint tab — verified no repaint)
  - minPrice=$5000     (cuts true junk: ex-taxis, salvage)
  - minModelYear=2021  (within China's 180-day rule horizon)
  - excludeSold=true   (only available)
  - sort=6             (newest listings first)

Cities (with PRC administrative codes):
  Shanghai     province=310000 city=310100
  Guangzhou    province=440000 city=440100
  Shenzhen     province=440000 city=440300
  Beijing      province=110000 city=110100
  Tianjin      province=120000 city=120100
  Chengdu      province=510000 city=510100

Usage:
    python collect_autocango.py --pages-per-city 20 --limit 10000

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any

import db as DB

SOURCE = "autocango"
BASE_URL = "https://www.autocango.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")

# Top 6 Chinese export hubs.
# province_id and city_id are PRC administrative codes
# (same scheme as dongchedi uses).
CITIES = {
    "Shanghai":  {"province_id": 310000, "city_id": 310100},
    "Guangzhou": {"province_id": 440000, "city_id": 440100},
    "Shenzhen":  {"province_id": 440000, "city_id": 440300},
    "Beijing":   {"province_id": 110000, "city_id": 110100},
    "Tianjin":   {"province_id": 120000, "city_id": 120100},
    "Chengdu":   {"province_id": 510000, "city_id": 510100},
}


def build_listing_url(city_key: str, page_num: int,
                      min_price: int, min_year: int,
                      original_paint: int, exclude_sold: bool) -> str:
    """Build URL: filter segments + cityId + pagination."""
    city = CITIES[city_key]
    parts = ["usedcar"]
    parts.append(f"minPrice={min_price}")
    parts.append(f"minModelYear={min_year}")
    parts.append("country=China")
    parts.append(f"provinceId={city['province_id']}")
    parts.append(f"cityId={city['city_id']}")
    parts.append("sort=6")
    if exclude_sold:
        parts.append("excludeSold=true")
    parts.append(f"originalPaint={original_paint}")
    if page_num > 1:
        parts.append(f"page={page_num}")
    return f"{BASE_URL}/" + "/".join(parts)


def extract_cars_js() -> str:
    """JS that pulls car-items from current rendered page."""
    return r"""() => {
        const cards = Array.from(document.querySelectorAll('div.car-item'));
        return cards.map(card => {
            const link = card.querySelector('a[href*="/sku/"]');
            const href = link ? link.getAttribute('href') : null;
            const idMatch = href ? href.match(/[A-Z]{2,4}\d{6,10}/) : null;
            const id = idMatch ? idMatch[0] : null;

            let brand_slug = null, model_slug = null, type_slug = null;
            if (href) {
                const m = href.match(/\/sku\/(newcar|usedcar)-(.+?)-([A-Z]{2,4}\d{6,10})/);
                if (m) {
                    type_slug = m[1];
                    const middle = m[2].split('-');
                    brand_slug = middle[0];
                    model_slug = middle.slice(1).join(' ');
                }
            }

            const imgs = Array.from(card.querySelectorAll('img'))
                .map(i => i.src).filter(s => s && !s.startsWith('data:'));
            const text = (card.innerText || '').replace(/\s+/g, ' ').trim();

            let price_usd = null;
            const priceMatch = text.match(/\$([\d,]+)/);
            if (priceMatch) price_usd = parseInt(priceMatch[1].replace(/,/g, ''), 10);

            return {
                id, href: href ? new URL(href, location.origin).href : null,
                type_slug, brand_slug, model_slug,
                images: imgs.slice(0, 3),
                text, price_usd,
            };
        }).filter(c => c.id);
    }"""


def parse_text_fields(text: str) -> dict:
    out: dict[str, Any] = {}
    m = re.search(r'Reg\.\s*Year\s*(\d{4})-(\d{1,2})', text)
    if m:
        out["reg_year"] = int(m.group(1))
        out["reg_month"] = int(m.group(2))
    m = re.search(r'Model Year\s*(\d{4})', text)
    if m:
        out["model_year"] = int(m.group(1))
    m = re.search(r'Mlg\(km\)\s*([\d,]+)', text)
    if m:
        out["mileage_km"] = int(m.group(1).replace(",", ""))
    m = re.search(r'Fuel\s*(\S+)', text)
    if m:
        out["fuel"] = m.group(1).strip()
    m = re.search(r'Engine\(cc\)\s*([\d-]+)', text)
    if m and m.group(1) != "-":
        out["engine_cc"] = int(m.group(1))
    m = re.search(r'Transm\.\s*(\S+)', text)
    if m:
        out["transmission"] = m.group(1).strip()
    m = re.search(r'Exterior Color\s*(\S+)', text)
    if m:
        out["color"] = m.group(1).strip()
    m = re.search(r'Steering\s*(\S+)', text)
    if m:
        out["steering"] = m.group(1).strip()
    out["compliant_180day"] = "180-Day Rule Compliant" in text
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", type=str, default=",".join(CITIES.keys()),
                    help="Comma-separated city keys")
    ap.add_argument("--pages-per-city", type=int, default=20,
                    help="Max listing pages to fetch per city")
    ap.add_argument("--min-price", type=int, default=5000,
                    help="Minimum price in USD")
    ap.add_argument("--min-year", type=int, default=2021,
                    help="Minimum model year")
    ap.add_argument("--original-paint", type=int, default=22,
                    help="Original-paint tab code (22 = strict)")
    ap.add_argument("--exclude-sold", type=bool, default=True)
    ap.add_argument("--limit", type=int, default=10000,
                    help="Max new IDs total")
    args = ap.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    bad = [c for c in cities if c not in CITIES]
    if bad:
        sys.exit(f"Unknown cities: {bad}. Available: {list(CITIES.keys())}")

    from playwright.sync_api import sync_playwright

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE}")
    print(f"Cities ({len(cities)}): {cities}")
    print(f"Filters: minPrice={args.min_price}, minYear={args.min_year}, "
          f"originalPaint={args.original_paint}, excludeSold={args.exclude_sold}")
    print(f"Pages per city: {args.pages_per_city}\n")

    print("Loading known IDs cache…")
    known = set()
    if DB.USE_POSTGRES:
        r = DB._pg_request("GET", f"cars?source=eq.{SOURCE}&select=source_id")
        if r.status_code == 200:
            known.update(row["source_id"] for row in r.json())
        r = DB._pg_request("GET", f"pending_ids?source=eq.{SOURCE}&select=source_id")
        if r.status_code == 200:
            known.update(row["source_id"] for row in r.json())
    print(f"  already in DB: {len(known)}\n")

    all_cars: dict[str, dict] = {}
    started = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        for city in cities:
            print(f"\n=== {city} ===")
            cars_in_city = 0
            for n in range(1, args.pages_per_city + 1):
                url = build_listing_url(city, n,
                                         args.min_price, args.min_year,
                                         args.original_paint,
                                         args.exclude_sold)
                try:
                    page.goto(url, wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(1200)
                    cars = page.evaluate(extract_cars_js())
                except Exception as e:
                    print(f"  [{city} p{n}] EXCEPTION: {e}")
                    continue
                # Diagnostic: dump page state on the FIRST page when no
                # listings come back — that's the smoking gun for HTML
                # changes or anti-bot blocks.
                if n == 1 and not cars:
                    try:
                        html = page.content()
                    except Exception:
                        html = ""
                    title_text = ""
                    try:
                        title_text = page.title()[:120]
                    except Exception:
                        pass
                    head = (html or "")[:1500]
                    sample_hrefs = sorted(set(
                        re.findall(r'href="(/[a-zA-Z0-9_./-]+/)"', html or "")
                    ))[:20]
                    print(
                        f"  ⚠ DIAGNOSE [autocango/{city}] {url}\n"
                        f"    final URL: {page.url}\n"
                        f"    <title>: {title_text!r}\n"
                        f"    HTML length: {len(html or '')}\n"
                        f"    sample hrefs ({len(sample_hrefs)}): {sample_hrefs}\n"
                        f"    HTML preview:\n{head}\n"
                        f"    ---end preview---",
                        flush=True,
                    )
                new_on_page = 0
                for car in cars:
                    cid = car.get("id")
                    if cid and cid not in all_cars:
                        all_cars[cid] = {**car, "source_city": city}
                        new_on_page += 1
                cars_in_city += len(cars)
                elapsed = int(time.time() - started)
                print(f"  [{city} p{n}] {len(cars)} cars ({new_on_page} new) "
                      f"| total unique: {len(all_cars)} | {elapsed}s")
                if len(cars) == 0:
                    print(f"  [{city}] no cars on page {n} — moving to next city")
                    break

        browser.close()

    print(f"\nTotal unique cars across all cities: {len(all_cars)}")

    skipped_known = skipped_old = 0
    to_save: list[tuple[str, dict]] = []
    for cid, car in all_cars.items():
        if cid in known:
            skipped_known += 1
            continue
        fields = parse_text_fields(car.get("text", ""))
        year = fields.get("model_year") or fields.get("reg_year")
        if args.min_year and year and year < args.min_year:
            skipped_old += 1
            continue
        metadata = {
            "href": car.get("href"),
            "type_slug": car.get("type_slug"),
            "brand_slug": car.get("brand_slug"),
            "model_slug": car.get("model_slug"),
            "images": car.get("images"),
            "price_usd": car.get("price_usd"),
            "source_city": car.get("source_city"),
            **fields,
        }
        to_save.append((cid, metadata))

    print(f"  already in DB:    {skipped_known}")
    print(f"  too old (<{args.min_year}): {skipped_old}")
    print(f"  to save:          {len(to_save)}")

    saved = 0
    for cid, meta in to_save:
        ok = DB.upsert_pending({
            "source": SOURCE,
            "source_id": cid,
            "metadata": meta,
            "found_at": DB.now_iso(),
        })
        if ok:
            saved += 1
        if saved >= args.limit:
            break

    total = int(time.time() - started)
    print(f"\nDone in {total}s. Upserted: {saved} new IDs.")


if __name__ == "__main__":
    main()
