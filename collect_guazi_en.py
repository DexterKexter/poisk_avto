"""en.guazi.com listing collector — Playwright.

Scrapes the English export version of Guazi. Each listing page has
`<a href="/products/{slug}.html">` links where the slug itself encodes:
  brand-model-year-engineL-color-mileageKm-trans-drive-seats-productId.html

Link text carries: "Grade {A-D} Used {Brand} {Model} {Year} {Trim}"

No login required. No chinese_maps. No LLM normalization. Data is
already English with USD pricing.

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi"
BASE_URL = "https://en.guazi.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

BRAND_SLUG = {
    "BMW": "bmw", "Audi": "audi", "Mercedes-Benz": "mercedes-benz",
    "Toyota": "toyota", "Lexus": "lexus", "Honda": "honda",
    "Hyundai": "hyundai", "Kia": "kia", "Genesis": "genesis",
    "Volkswagen": "volkswagen", "Porsche": "porsche",
    "Honda": "honda", "Nissan": "nissan", "Mazda": "mazda",
    "Subaru": "subaru", "Mitsubishi": "mitsubishi",
    "Chevrolet": "chevrolet", "Ford": "ford", "Cadillac": "cadillac",
    "Tesla": "tesla", "BYD": "byd", "Geely": "geely",
    "Chery": "chery", "Haval": "haval", "Great Wall": "great-wall",
    "Li Auto": "li-auto", "NIO": "nio", "XPeng": "xpeng",
    "Zeekr": "zeekr", "Voyah": "voyah", "AITO": "aito",
    "Lynk & Co": "lynk-and-co", "Xiaomi": "xiaomi",
    "Volvo": "volvo", "Land Rover": "land-rover", "Jaguar": "jaguar",
    "Jeep": "jeep", "Rolls-Royce": "rolls-royce", "Bentley": "bentley",
    "Ferrari": "ferrari", "Lamborghini": "lamborghini",
    "Maserati": "maserati", "Wuling": "wuling", "Tank": "tank",
    "Denza": "denza", "Changan": "changan", "Hongqi": "hongqi",
    "MG": "mg", "Jetour": "jetour",
}


def brand_to_slug(mark: str) -> str:
    return BRAND_SLUG.get(mark) or mark.lower().replace(
        "&", "and").replace(" ", "-").replace("_", "-")


def parse_product_slug(href: str) -> dict | None:
    """Parse /products/bmw-3-series-2021-20l-black-31800km-at-2wd-5-seats-hkwz64zjgr.html"""
    m = re.search(r'/products/(.+)\.html', href)
    if not m:
        return None
    slug = m.group(1).split("?")[0]
    parts = slug.rsplit("-", 1)
    product_id = parts[-1] if len(parts) == 2 else slug

    info = {"product_id": product_id, "slug": slug, "href": href}

    km_m = re.search(r'(\d+)km', slug)
    if km_m:
        info["mileage_km"] = int(km_m.group(1))

    year_m = re.search(r'-(\d{4})-', slug)
    if year_m:
        info["year"] = int(year_m.group(1))

    engine_m = re.search(r'-(\d+(?:\.\d+)?)l-', slug)
    if engine_m:
        info["displacement"] = float(engine_m.group(1))

    seats_m = re.search(r'(\d+)-seats?', slug)
    if seats_m:
        info["seats"] = int(seats_m.group(1))

    if "-4wd-" in slug or "-awd-" in slug:
        info["drive"] = "AWD"
    elif "-2wd-" in slug or "-fwd-" in slug:
        info["drive"] = "FWD"
    elif "-rwd-" in slug:
        info["drive"] = "RWD"

    if "-at-" in slug:
        info["transmission"] = "Automatic"
    elif "-mt-" in slug:
        info["transmission"] = "Manual"

    for color in ["black", "white", "silver", "grey", "red", "blue",
                   "green", "brown", "gold", "orange", "yellow", "purple",
                   "champagne", "beige", "pink"]:
        if f"-{color}-" in slug:
            info["color"] = color.capitalize()
            if color == "grey":
                info["color"] = "Gray"
            break

    return info


def parse_link_text(text: str) -> dict:
    """Parse 'Grade A Used BMW 3 Series 2021 Restyled 325i M Sport Night Edition Package'"""
    result = {}
    grade_m = re.match(r'Grade\s+([A-F][+-]?)\s+', text, re.I)
    if grade_m:
        result["grade"] = grade_m.group(1).upper()
        text = text[grade_m.end():]

    if text.startswith("Used "):
        text = text[5:]

    year_m = re.search(r'\b(\d{4})\b', text)
    if year_m:
        result["year"] = int(year_m.group(1))
        brand_model = text[:year_m.start()].strip()
        trim = text[year_m.end():].strip()
        # Remove "Restyled" / "Facelift" prefix from trim if present
        trim = re.sub(r'^(?:Restyled|Facelift)\s+', '', trim)
        result["brand_model"] = brand_model
        result["trim"] = trim
    else:
        result["brand_model"] = text
        result["trim"] = ""

    return result


def extract_cards(page) -> list[dict]:
    """Extract car cards from rendered en.guazi.com listing page."""
    raw = page.evaluate(r"""() => {
        const results = [];
        const links = document.querySelectorAll('a[href*="/products/"]');
        for (const a of links) {
            const href = a.getAttribute('href') || '';
            if (!href.includes('.html')) continue;
            const text = (a.innerText || '').trim().replace(/\n/g, ' ');
            // Find nearby image
            const card = a.closest('[class*="card"]') || a.parentElement?.parentElement;
            let imgSrc = '';
            if (card) {
                const img = card.querySelector('img[alt*="Used"]') || card.querySelector('img[src*="guazi"]');
                if (img) imgSrc = img.src || '';
            }
            results.push({href, text, imgSrc});
        }
        const seen = new Set();
        return results.filter(r => {
            if (seen.has(r.href)) return false;
            seen.add(r.href);
            return true;
        });
    }""")

    cards = []
    for r in raw:
        slug_data = parse_product_slug(r["href"])
        if not slug_data:
            continue
        text_data = parse_link_text(r["text"])
        cards.append({**slug_data, **text_data, "photo": r.get("imgSrc", "")})
    return cards


def collect_brand(page, mark: str, slug: str, max_pages: int,
                  min_year: int, min_price: int, max_mileage_km: int) -> list[dict]:
    collected = []
    for pg in range(1, max_pages + 1):
        url = f"{BASE_URL}/used-cars/{slug}/"
        if pg > 1:
            url = f"{BASE_URL}/used-cars/{slug}/page{pg}/"
        try:
            page.goto(url, wait_until="networkidle", timeout=45_000)
            page.wait_for_timeout(4000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"    page {pg} load failed: {e}", flush=True)
            break

        cards = extract_cards(page)
        if not cards:
            break

        for c in cards:
            year = c.get("year") or 0
            km = c.get("mileage_km") or 0
            if min_year and year < min_year:
                continue
            if max_mileage_km and km > max_mileage_km:
                continue
            collected.append(c)

        if len(cards) < 8:
            break

    return collected


def get_brands_to_scrape() -> list[tuple[str, str]]:
    r = DB._pg_request("GET", "brands?select=name&order=name")
    if r.status_code != 200:
        return list(BRAND_SLUG.items())
    seen = set()
    result = []
    for b in r.json():
        name = b["name"]
        slug = brand_to_slug(name)
        if slug not in seen:
            result.append((name, slug))
            seen.add(slug)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", default="")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--min-year", type=int, default=2018)
    ap.add_argument("--min-price-usd", type=int, default=0)
    ap.add_argument("--max-mileage-km", type=int, default=200000)
    ap.add_argument("--limit", type=int, default=15000)
    args = ap.parse_args()

    if args.brands:
        brands = [(b.strip(), brand_to_slug(b.strip()))
                   for b in args.brands.split(",") if b.strip()]
    else:
        brands = get_brands_to_scrape()

    print(f"Collecting from en.guazi.com: {len(brands)} brands, "
          f"max {args.max_pages} pages/brand", flush=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 3000}, locale="en-US")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        total_saved = 0
        for i, (mark, slug) in enumerate(brands, 1):
            if total_saved >= args.limit:
                break
            cars = collect_brand(page, mark, slug, args.max_pages,
                                args.min_year, args.min_price_usd,
                                args.max_mileage_km)
            saved = 0
            for car in cars:
                if total_saved >= args.limit:
                    break
                meta = json.dumps(car, ensure_ascii=False)
                ok = DB.upsert_pending({
                    "source": SOURCE,
                    "source_id": car["product_id"],
                    "meta": meta,
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
