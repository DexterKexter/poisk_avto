"""en.guazi.com listing collector — Playwright-rendered.

Scrapes the English export-oriented version of Guazi which provides:
  - Brand/model/trim already in English
  - Prices in USD (FOB)
  - Photos on guazistatic-global CDN (no Chrome ORB issues)
  - Export certifications, inspection scores
  - Only exportable vehicles (exactly what KZ buyers need)

Strategy:
  - Navigate to /used-cars/{brand}/page{N}/ with Playwright
  - Extract car cards from rendered DOM (React Server Components)
  - Save to pending_ids with metadata for detail scraping
  - Iterates ALL brands that exist in our `brands` table

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

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi"
BASE_URL = "https://en.guazi.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Brand → slug mapping on en.guazi.com (lowercase, hyphenated).
# Built from /used-cars/ page links: /used-cars/bmw/, /used-cars/toyota/, etc.
# For brands not listed here, we generate slug automatically.
BRAND_SLUG = {
    "BMW": "bmw", "Audi": "audi", "Mercedes-Benz": "mercedes-benz",
    "Toyota": "toyota", "Lexus": "lexus", "Honda": "honda",
    "Hyundai": "hyundai", "Kia": "kia", "Genesis": "genesis",
    "Volkswagen": "volkswagen", "Porsche": "porsche",
    "Nissan": "nissan", "Mazda": "mazda", "Subaru": "subaru",
    "Mitsubishi": "mitsubishi", "Chevrolet": "chevrolet",
    "Ford": "ford", "Cadillac": "cadillac", "Buick": "buick",
    "Tesla": "tesla", "BYD": "byd", "Geely": "geely",
    "Chery": "chery", "Haval": "haval", "Great Wall": "great-wall",
    "Hongqi": "hongqi", "Changan": "changan", "ChangAn": "changan",
    "Li Auto": "li-auto", "Lixiang": "li-auto",
    "NIO": "nio", "XPeng": "xpeng", "Zeekr": "zeekr",
    "Voyah": "voyah", "AITO": "aito", "Wuling": "wuling",
    "WuLing": "wuling", "Tank": "tank", "Denza": "denza",
    "Lynk & Co": "lynk-and-co", "Xiaomi": "xiaomi",
    "Polestar": "polestar", "Volvo": "volvo", "Skoda": "skoda",
    "Rolls-Royce": "rolls-royce", "Bentley": "bentley",
    "Ferrari": "ferrari", "Lamborghini": "lamborghini",
    "Maserati": "maserati", "Aston Martin": "aston-martin",
    "Land Rover": "land-rover", "Jaguar": "jaguar",
    "Jeep": "jeep", "Dodge": "dodge", "Lincoln": "lincoln",
    "Alfa Romeo": "alfa-romeo", "Mini": "mini", "MINI": "mini",
    "Infiniti": "infiniti", "Acura": "acura",
    "GAC Trumpchi": "gac-trumpchi", "Geely Galaxy": "geely-auto",
    "Ora": "ora", "GWM Ora": "ora",
    "Jetour": "jetour", "Exeed": "exeed",
    "Deepal": "deepal", "Onvo": "onvo",
    "Roewe": "roewe", "Baojun": "baojun",
    "Dongfeng": "dongfeng", "JAC": "jac", "JMC": "jmc",
    "Foton": "foton", "Bestune": "bestune",
}


def brand_slug(mark: str) -> str:
    return BRAND_SLUG.get(mark) or mark.lower().replace(
        "&", "and").replace(" ", "-").replace("_", "-")


def extract_cards(page) -> list[dict]:
    """Extract car card data from a rendered listing page.

    en.guazi.com renders cards as React components. We extract from the
    DOM rather than intercepting API calls — more resilient to API auth
    changes while the public DOM stays stable.
    """
    cards = page.evaluate(r"""() => {
        const results = [];
        // Strategy 1: find car card links with structured alt text
        // Alt pattern: "Used {Brand} {Model} {Year} {Trim}"
        // They appear in <img> inside <a> card containers
        const imgs = document.querySelectorAll('img[alt^="Used "]');
        for (const img of imgs) {
            const alt = img.alt;
            const card = img.closest('a') || img.closest('[data-testid]') || img.parentElement?.parentElement;
            if (!card) continue;
            const href = card.getAttribute('href') || '';
            // Extract clueId from href: /used-cars/detail/123456/
            const idMatch = href.match(/\/detail\/(\d+)/);
            if (!idMatch) continue;
            const clueId = idMatch[1];
            // Parse alt: "Used BMW 5 Series 2018 530Li Leading Edition Luxury Package"
            // Price from card text
            const priceEl = card.querySelector('[class*="price"]') || card;
            const priceText = priceEl.innerText || '';
            const priceMatch = priceText.match(/\$\s*([\d,]+)/);
            const price = priceMatch ? parseInt(priceMatch[1].replace(/,/g, ''), 10) : null;
            // Mileage
            const mileMatch = priceText.match(/([\d,.]+)\s*(?:km|mi)/i);
            const mileage = mileMatch ? parseFloat(mileMatch[1].replace(/,/g, '')) : null;
            // Year from alt
            const yearMatch = alt.match(/(\d{4})/);
            const year = yearMatch ? parseInt(yearMatch[1], 10) : null;
            // Photo URL
            const photoSrc = img.src || img.dataset?.src || '';

            results.push({
                clueId, alt, href, price, mileage, year, photoSrc
            });
        }

        // Strategy 2: if strategy 1 found nothing, try generic card containers
        if (results.length === 0) {
            const cards = document.querySelectorAll('[class*="car-card"], [class*="vehicle_card"], [class*="carItem"]');
            for (const card of cards) {
                const link = card.querySelector('a[href*="/detail/"]');
                if (!link) continue;
                const href = link.getAttribute('href') || '';
                const idMatch = href.match(/\/detail\/(\d+)/);
                if (!idMatch) continue;
                const text = card.innerText || '';
                results.push({
                    clueId: idMatch[1],
                    alt: '',
                    href,
                    price: null,
                    mileage: null,
                    year: null,
                    photoSrc: '',
                    rawText: text.substring(0, 500)
                });
            }
        }

        // Dedupe by clueId
        const seen = new Set();
        return results.filter(r => {
            if (seen.has(r.clueId)) return false;
            seen.add(r.clueId);
            return true;
        });
    }""")
    return cards


def collect_brand(page, mark: str, slug: str, max_pages: int,
                  min_year: int, min_price: int,
                  max_mileage_km: int) -> list[dict]:
    """Collect cars for one brand across multiple pages.

    en.guazi.com loads listing data via internal API (RSC streaming).
    We intercept API responses via Playwright's response handler rather
    than parsing DOM — the DOM often stays empty without auth.
    """
    collected = []
    for pg in range(1, max_pages + 1):
        url = f"{BASE_URL}/used-cars/{slug}/"
        if pg > 1:
            url = f"{BASE_URL}/used-cars/{slug}/page{pg}/"

        api_cars: list[dict] = []

        def _on_response(resp):
            """Intercept JSON API responses that contain car listings."""
            try:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct and "text/x-component" not in ct:
                    return
                body = resp.text()
                if not body or len(body) < 50:
                    return
                # RSC streaming sends multiple JSON lines — try each
                for line in body.split("\n"):
                    line = line.strip()
                    if not line or not (line.startswith("{") or line.startswith("[")):
                        continue
                    try:
                        import json as _json
                        obj = _json.loads(line)
                    except Exception:
                        continue
                    # Look for car list data
                    items = None
                    if isinstance(obj, dict):
                        data = obj.get("data") or obj
                        if isinstance(data, dict):
                            items = data.get("list") or data.get("items") or data.get("records")
                    elif isinstance(obj, list):
                        items = obj
                    if items and isinstance(items, list) and len(items) > 0:
                        first = items[0]
                        if isinstance(first, dict) and any(
                            k in first for k in ("clueId", "productId", "carId",
                                                  "brandName", "modelName", "price")):
                            api_cars.extend(items)
            except Exception:
                pass

        page.on("response", _on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=45_000)
            page.wait_for_timeout(3000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"    page {pg} load failed: {e}", flush=True)
            page.remove_listener("response", _on_response)
            break
        page.remove_listener("response", _on_response)

        # Strategy 1: API-intercepted cars
        if api_cars:
            print(f"    page {pg}: intercepted {len(api_cars)} cars from API",
                  flush=True)
            for car in api_cars:
                cid = str(car.get("clueId") or car.get("productId")
                          or car.get("carId") or car.get("id", ""))
                if not cid:
                    continue
                brand = car.get("brandName") or car.get("brand") or mark
                model = car.get("modelName") or car.get("model") or car.get("seriesName") or ""
                year = car.get("year") or car.get("modelYear")
                price = car.get("price") or car.get("displayPrice")
                mileage = car.get("mileage") or car.get("kilometer")
                photo = car.get("coverImage") or car.get("image") or car.get("mainPhoto") or ""
                detail_url = car.get("detailUrl") or f"/used-cars/detail/{cid}/"

                collected.append({
                    "source_id": cid,
                    "url": f"{BASE_URL}{detail_url}" if detail_url.startswith("/") else detail_url,
                    "mark": brand,
                    "model": model,
                    "alt": f"Used {brand} {model} {year or ''}".strip(),
                    "price_usd": int(price) if price else None,
                    "mileage_km": int(float(str(mileage).replace(",", ""))) if mileage else None,
                    "year": int(year) if year else None,
                    "photo": photo,
                    "api_data": car,
                })
            if len(api_cars) < 10:
                break
            continue

        # Strategy 2: DOM extraction (fallback)
        cards = extract_cards(page)
        if not cards:
            debug = page.evaluate("""() => ({
                title: document.title,
                url: location.href,
                bodyLen: document.body?.innerText?.length || 0,
                bodySnippet: (document.body?.innerText || '').substring(0, 1500),
                imgCount: document.querySelectorAll('img').length,
                altImgs: Array.from(document.querySelectorAll('img[alt]'))
                    .map(i=>i.alt).filter(a=>a.length>5).slice(0,10),
                detailLinks: Array.from(document.querySelectorAll('a[href*="/detail/"]'))
                    .map(a=>a.href).slice(0,5),
            })""")
            print(f"    page {pg}: 0 cards. title={debug['title']!r}, "
                  f"bodyLen={debug['bodyLen']}, imgs={debug['imgCount']}, "
                  f"detailLinks={len(debug.get('detailLinks',[]))}",
                  flush=True)
            if debug.get("altImgs"):
                print(f"    alt samples: {debug['altImgs'][:5]}", flush=True)
            if debug.get("detailLinks"):
                print(f"    detail hrefs: {debug['detailLinks']}", flush=True)
            if pg == 1:
                print(f"    body: {debug['bodySnippet'][:800]}", flush=True)
            break

        for c in cards:
            year = c.get("year") or 0
            price = c.get("price") or 0
            mileage = c.get("mileage") or 0
            if min_year and year < min_year:
                continue
            if min_price and price < min_price:
                continue
            if max_mileage_km and mileage > max_mileage_km:
                continue
            collected.append({
                "source_id": c["clueId"],
                "url": f"{BASE_URL}{c['href']}" if c["href"].startswith("/") else c["href"],
                "mark": mark,
                "alt": c.get("alt", ""),
                "price_usd": price,
                "mileage_km": mileage,
                "year": year,
                "photo": c.get("photoSrc", ""),
            })

        if len(cards) < 10:
            break

    return collected


def get_brands_to_scrape() -> list[tuple[str, str]]:
    """Fetch brands from our DB that have known slugs."""
    r = DB._pg_request("GET", "brands?select=name&order=name")
    if r.status_code != 200:
        return list(BRAND_SLUG.items())
    brands = r.json()
    result = []
    seen = set()
    for b in brands:
        name = b["name"]
        slug = brand_slug(name)
        if slug not in seen:
            result.append((name, slug))
            seen.add(slug)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", default="",
                    help="CSV of brand names (empty = all from DB)")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--min-year", type=int, default=2018)
    ap.add_argument("--min-price-usd", type=int, default=2000)
    ap.add_argument("--max-mileage-km", type=int, default=150000)
    ap.add_argument("--limit", type=int, default=15000)
    args = ap.parse_args()

    if args.brands:
        brands = [(b.strip(), brand_slug(b.strip()))
                   for b in args.brands.split(",") if b.strip()]
    else:
        brands = get_brands_to_scrape()

    print(f"Collecting from en.guazi.com: {len(brands)} brands, "
          f"max {args.max_pages} pages/brand, "
          f"year≥{args.min_year}, price≥${args.min_price_usd}, "
          f"mileage≤{args.max_mileage_km}km", flush=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 2000},
            locale="en-US",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        total_saved = 0
        for i, (mark, slug) in enumerate(brands, 1):
            if total_saved >= args.limit:
                break
            cars = collect_brand(
                page, mark, slug, args.max_pages,
                args.min_year, args.min_price_usd,
                args.max_mileage_km,
            )
            saved = 0
            for car in cars:
                if total_saved >= args.limit:
                    break
                meta = {
                    "url": car["url"],
                    "mark": car["mark"],
                    "alt": car["alt"],
                    "price_usd": car["price_usd"],
                    "mileage_km": car["mileage_km"],
                    "year": car["year"],
                }
                ok = DB.upsert_pending({
                    "source": SOURCE,
                    "source_id": car["source_id"],
                    "meta": json.dumps(meta, ensure_ascii=False),
                })
                if ok:
                    saved += 1
                    total_saved += 1
            if cars:
                print(f"  [{i}/{len(brands)}] {mark:25} → {len(cars)} found, "
                      f"{saved} upserted (total {total_saved})", flush=True)

        browser.close()

    print(f"\nDone. Total upserted: {total_saved}", flush=True)


if __name__ == "__main__":
    main()
