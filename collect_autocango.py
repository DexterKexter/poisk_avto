"""
Autocango.com listing ID collector — playwright + DOM scraping.

autocango.com is a Chinese new+used car export platform. WAF blocks
direct HTTP, but headless Chromium passes. We open
  https://www.autocango.com/usedcar/excludeSold=true/page=N
extract div.car-item, save the visible fields + href to pending_ids.

~30 cars per page, ~$0 per request (GitHub Actions free tier).

Usage:
    python collect_autocango.py --pages 10 --min-year 0 --limit 5000

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


def build_listing_url(page_num: int, exclude_sold: bool = True) -> str:
    parts = ["usedcar"]
    if exclude_sold:
        parts.append("excludeSold=true")
    if page_num > 1:
        parts.append(f"page={page_num}")
    return f"{BASE_URL}/" + "/".join(parts)


def extract_cars_js() -> str:
    """JS that extracts all cars from current page."""
    return r"""() => {
        const cards = Array.from(document.querySelectorAll('div.car-item'));
        return cards.map(card => {
            const link = card.querySelector('a[href*="/sku/"]');
            const href = link ? link.getAttribute('href') : null;
            const idMatch = href ? href.match(/[A-Z]{2,4}\d{6,10}/) : null;
            const id = idMatch ? idMatch[0] : null;

            // url-slug pieces (brand-model) from /sku/usedcar-Brand-Model-ID
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

            // Extract price: $X,XXX usually appears as standalone in card
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
    """Extract structured fields from card.innerText."""
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
    ap.add_argument("--pages", type=int, default=10,
                    help="How many listing pages to fetch (~30 cars each)")
    ap.add_argument("--min-year", type=int, default=0,
                    help="Skip cars with model_year < this (0 = no filter)")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--exclude-sold", type=bool, default=True)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE}")
    print(f"Pages: {args.pages} × ~30 = up to {args.pages * 30}")
    print(f"Filters: min_year={args.min_year}, exclude_sold={args.exclude_sold}\n")

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

        for n in range(1, args.pages + 1):
            url = build_listing_url(n, args.exclude_sold)
            try:
                page.goto(url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1500)
                cars = page.evaluate(extract_cars_js())
            except Exception as e:
                print(f"  [page {n}] EXCEPTION: {e}")
                continue
            new_on_page = 0
            for car in cars:
                cid = car.get("id")
                if cid and cid not in all_cars:
                    all_cars[cid] = car
                    new_on_page += 1
            elapsed = int(time.time() - started)
            print(f"  [page {n}] {len(cars)} cars ({new_on_page} new), "
                  f"total unique: {len(all_cars)}, elapsed {elapsed}s")
            if new_on_page == 0 and n > 1:
                # Pagination exhausted
                print(f"  no new cars on page {n} — stopping")
                break

        browser.close()

    print(f"\nTotal unique cars: {len(all_cars)}")

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
            **fields,
        }
        to_save.append((cid, metadata))

    print(f"  already in DB: {skipped_known}")
    print(f"  too old: {skipped_old}")
    print(f"  to save: {len(to_save)}")

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
