"""
Autocango.com NEW-car listing ID collector.

The /newcar/ section is small (a few hundred SKUs total) so we skip
filters entirely — no city loop, no price/year minimums — and just walk
pagination until the page returns zero cars.

Usage:
    python collect_autocango_new.py --max-pages 100 --limit 10000

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import re
import time
from typing import Any

import db as DB

SOURCE = "autocango"
TYPE_SLUG = "newcar"
BASE_URL = "https://www.autocango.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def build_listing_url(page_num: int) -> str:
    """Unfiltered /newcar/ listing, optional /page=N suffix."""
    if page_num <= 1:
        return f"{BASE_URL}/newcar"
    return f"{BASE_URL}/newcar/page={page_num}"


def extract_cars_js() -> str:
    """JS that pulls car-items from the rendered newcar listing page."""
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

            let msrp_cny = null;
            const cnyMatch = text.match(/¥\s*([\d,]+)/);
            if (cnyMatch) msrp_cny = parseInt(cnyMatch[1].replace(/,/g, ''), 10);

            return {
                id, href: href ? new URL(href, location.origin).href : null,
                type_slug, brand_slug, model_slug,
                images: imgs.slice(0, 3),
                text, price_usd, msrp_cny,
            };
        }).filter(c => c.id);
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
    ap.add_argument("--max-pages", type=int, default=100,
                    help="Hard cap on listing pages to fetch")
    ap.add_argument("--limit", type=int, default=10000,
                    help="Max new IDs to upsert total")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE} (type={TYPE_SLUG})")
    print(f"No filters — walking /newcar/ pagination (max {args.max_pages} pages)\n")

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

        for n in range(1, args.max_pages + 1):
            url = build_listing_url(n)
            try:
                page.goto(url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1200)
                cars = page.evaluate(extract_cars_js())
            except Exception as e:
                print(f"  [p{n}] EXCEPTION: {e}")
                continue
            # Defensive: drop any usedcar entries that may slip in
            cars = [c for c in cars if c.get("type_slug") == TYPE_SLUG]
            new_on_page = 0
            for car in cars:
                cid = car.get("id")
                if cid and cid not in all_cars:
                    all_cars[cid] = car
                    new_on_page += 1
            elapsed = int(time.time() - started)
            print(f"  [p{n}] {len(cars)} newcars ({new_on_page} new) "
                  f"| total unique: {len(all_cars)} | {elapsed}s")
            if len(cars) == 0:
                print(f"  no cars on page {n} — end of pagination")
                break

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
