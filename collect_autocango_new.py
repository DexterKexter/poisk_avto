"""
Autocango.com NEW-car listing ID collector.

The /newcar/ section is small (~24 cars on the landing page, no real
pagination) so we just scroll the landing page to trigger any lazy
content and collect every `a[href*='/sku/newcar-']` link.

Unlike /usedcar/, the newcar grid does NOT use `div.car-item`; cards
are direct `<a>` elements inside a Vue carousel + grid.

Usage:
    python collect_autocango_new.py --limit 10000

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import re
import time
from typing import Any

import db as DB

SOURCE = "autocango"
TYPE_SLUG = "newcar"
LISTING_URL = "https://www.autocango.com/newcar"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def extract_cars_js() -> str:
    """JS that collects every newcar link on the page, dedup'd by ACN id."""
    return r"""() => {
        const seen = new Map();
        for (const a of document.querySelectorAll("a[href*='/sku/newcar-']")) {
            const href = a.getAttribute('href');
            const idMatch = href.match(/ACN\d+/);
            if (!idMatch) continue;
            const id = idMatch[0];
            // Prefer the first occurrence that has the richest text
            const text = (a.innerText || '').replace(/\s+/g, ' ').trim();
            if (seen.has(id) && (seen.get(id).text.length >= text.length)) continue;

            let brand_slug = null, model_slug = null, type_slug = null;
            const m = href.match(/\/sku\/(newcar|usedcar)-(.+?)-(ACN\d+|ACU\d+|[A-Z]{2,4}\d{6,10})/);
            if (m) {
                type_slug = m[1];
                const middle = m[2].split('-');
                brand_slug = middle[0];
                model_slug = middle.slice(1).join(' ');
            }

            const imgs = Array.from(a.querySelectorAll('img'))
                .map(i => i.src).filter(s => s && !s.startsWith('data:'))
                .map(s => s.split('?')[0]);

            let price_usd = null;
            const priceMatch = text.match(/\$([\d,]+)/);
            if (priceMatch) price_usd = parseInt(priceMatch[1].replace(/,/g, ''), 10);

            let msrp_cny = null;
            const cnyMatch = text.match(/¥\s*([\d,]+)/);
            if (cnyMatch) msrp_cny = parseInt(cnyMatch[1].replace(/,/g, ''), 10);

            seen.set(id, {
                id,
                href: new URL(href, location.origin).href,
                type_slug, brand_slug, model_slug,
                images: imgs.slice(0, 3),
                text, price_usd, msrp_cny,
            });
        }
        return [...seen.values()];
    }"""


def parse_text_fields(text: str) -> dict:
    """Extract regex-parseable fields from listing card text.

    For new cars: no mileage, no registration date, no 180-day-rule mark.
    """
    out: dict[str, Any] = {}
    m = re.search(r'Model Year\s*(\d{4})', text)
    if m:
        out["model_year"] = int(m.group(1))
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
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10000,
                    help="Max new IDs to upsert total")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE} (type={TYPE_SLUG})")
    print(f"Listing: {LISTING_URL}\n")

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
                  "--no-sandbox", "--disable-dev-shm-usage",
                  "--ignore-certificate-errors"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768},
                                  locale="en-US",
                                  ignore_https_errors=True)
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        try:
            page.goto(LISTING_URL, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(1500)
            # Scroll twice to trigger any lazy-rendered grid content
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            cars = page.evaluate(extract_cars_js())
        except Exception as e:
            print(f"  listing FAIL: {e}")
            cars = []

        cars = [c for c in cars if c.get("type_slug") == TYPE_SLUG]
        for car in cars:
            cid = car.get("id")
            if cid:
                all_cars[cid] = car

        elapsed = int(time.time() - started)
        print(f"  collected {len(cars)} newcars | unique: {len(all_cars)} | {elapsed}s")

        browser.close()

    print(f"\nTotal unique newcars: {len(all_cars)}")

    skipped_known = 0
    to_save: list[tuple[str, dict]] = []
    for cid, car in all_cars.items():
        if cid in known:
            skipped_known += 1
            continue
        fields = parse_text_fields(car.get("text", ""))
        metadata = {
            "href": car.get("href"),
            "type_slug": car.get("type_slug") or TYPE_SLUG,
            "brand_slug": car.get("brand_slug"),
            "model_slug": car.get("model_slug"),
            "images": car.get("images"),
            "price_usd": car.get("price_usd"),
            "msrp_cny": car.get("msrp_cny"),
            **fields,
        }
        to_save.append((cid, metadata))

    print(f"  already in DB: {skipped_known}")
    print(f"  to save:       {len(to_save)}")

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
