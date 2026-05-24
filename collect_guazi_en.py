"""en.guazi.com listing collector — Playwright, no proxy needed.

en.guazi.com is the international export platform (FOB pricing in USD).
Accessible worldwide without Oxylabs — direct Playwright.

Strategy:
  - Login with GUAZI_EMAIL / GUAZI_PASSWORD (optional, works without)
  - Discover brand slugs from /used-cars/ navigation
  - Browse /used-cars/{brand}/page{N}/ for car cards
  - Extract cards via JS evaluation + URL slug parsing
  - Save to pending_ids with source="guazi_en"

Env: SUPABASE_URL, SUPABASE_KEY, GUAZI_EMAIL (opt), GUAZI_PASSWORD (opt)
"""

import argparse
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi_en"
BASE_URL = "https://en.guazi.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SLUG_RE = re.compile(
    r'^(.+?)-(\d{4})-(\d+)l-([a-z]+)-(\d+)km-(at|mt)'
    r'(?:-(2wd|4wd))?-(\d+)-seats-([a-z0-9]+)$'
)

BRAND_SLUG_TO_NAME = {
    "toyota": "Toyota", "volkswagen": "Volkswagen", "bmw": "BMW",
    "mercedes-benz": "Mercedes-Benz", "audi": "Audi", "honda": "Honda",
    "nissan": "Nissan", "hyundai": "Hyundai", "kia": "Kia",
    "byd": "BYD", "geely-auto": "Geely", "chery": "Chery",
    "haval": "Haval", "great-wall": "Great Wall", "changan": "Changan",
    "buick": "Buick", "chevrolet": "Chevrolet", "ford": "Ford",
    "cadillac": "Cadillac", "lincoln": "Lincoln",
    "mazda": "Mazda", "subaru": "Subaru", "mitsubishi": "Mitsubishi",
    "tesla": "Tesla", "nio": "NIO", "xpeng": "XPeng",
    "li-auto": "Li Auto", "zeekr": "Zeekr", "xiaomi-auto": "Xiaomi",
    "volvo": "Volvo", "lexus": "Lexus", "infiniti": "Infiniti",
    "porsche": "Porsche", "land-rover": "Land Rover", "jaguar": "Jaguar",
    "bentley": "Bentley", "rolls-royce": "Rolls-Royce",
    "maserati": "Maserati", "ferrari": "Ferrari", "lamborghini": "Lamborghini",
    "peugeot": "Peugeot", "citroen": "Citroen", "skoda": "Skoda",
    "renault": "Renault", "smart": "smart", "mini": "MINI", "mg": "MG",
    "jetour": "Jetour", "tank": "Tank", "lynk-co": "Lynk & Co",
    "wey": "WEY", "hongqi": "Hongqi", "denza": "Denza",
    "voyah": "Voyah", "aion": "Aion", "ora": "ORA",
    "leapmotor": "Leapmotor", "neta": "Neta", "arcfox": "ARCFOX",
    "roewe": "Roewe", "wuling": "Wuling", "baojun": "Baojun",
    "dongfeng": "Dongfeng", "jac": "JAC", "foton": "Foton",
    "gac-trumpchi": "GAC Trumpchi", "aito": "AITO",
    "jeep": "Jeep", "dodge": "Dodge", "chrysler": "Chrysler",
    "genesis": "Genesis", "acura": "Acura",
    "alfa-romeo": "Alfa Romeo", "aston-martin": "Aston Martin",
    "mclaren": "McLaren", "lotus": "Lotus",
    "suzuki": "Suzuki", "ds": "DS",
}


def parse_product_slug(slug: str) -> dict | None:
    """Parse structured data from the URL slug.

    Example: bmw-3-series-2021-20l-black-31800km-at-2wd-5-seats-hkwz64zjgr
    """
    m = SLUG_RE.match(slug)
    if not m:
        return None
    brand_series, year, disp, color, km, trans, drive, seats, item_id = m.groups()
    return {
        "brand_series_slug": brand_series,
        "year": int(year),
        "displacement_dl": int(disp),
        "color": color.capitalize() if color != "gray" else "Gray",
        "mileage_km": int(km),
        "transmission": "Automatic" if trans == "at" else "Manual",
        "drive": {"2wd": "FWD", "4wd": "AWD"}.get(drive) if drive else None,
        "seats": int(seats),
        "item_id": item_id,
    }


EXTRACT_CARDS_JS = """() => {
    const results = [];
    const seen = new Set();
    const links = document.querySelectorAll('a[href*="/products/"][href$=".html"]');

    for (const link of links) {
        const href = link.getAttribute('href');
        if (!href || seen.has(href)) continue;
        seen.add(href);

        // Walk up to find card container
        let card = link;
        for (let i = 0; i < 8; i++) {
            if (!card.parentElement) break;
            card = card.parentElement;
            const text = card.innerText || '';
            if (text.length > 80 && text.length < 3000) break;
        }

        const text = (card.innerText || '').replace(/\\n+/g, ' | ');

        // Find grade badge (single letter A-D or S)
        const gradeEl = card.querySelector('[class*="grade"], [class*="Grade"]');
        let grade = '';
        if (gradeEl) {
            grade = (gradeEl.innerText || '').trim();
        } else {
            // Try to find standalone letter that's a grade
            const gradeMatch = text.match(/\\b([ABCDS])\\b/);
            if (gradeMatch) grade = gradeMatch[1];
        }

        // Find price
        let price = null;
        const priceMatch = text.match(/\\$([\\d,]+)/);
        if (priceMatch) {
            price = parseInt(priceMatch[1].replace(/,/g, ''), 10);
        }

        // Find image
        const img = card.querySelector('img[src*="guazi"], img[src*="image"]');
        const imgSrc = img ? (img.src || img.getAttribute('data-src') || '') : '';
        const imgAlt = img ? (img.alt || '') : '';

        // Seller type
        let sellerType = '';
        if (text.includes('Certified Dealer')) sellerType = 'dealer';
        else if (text.includes('Individual')) sellerType = 'individual';

        results.push({
            href: href,
            text: text.substring(0, 500),
            grade: grade,
            price_usd: price,
            img_src: imgSrc,
            img_alt: imgAlt,
            seller_type: sellerType,
        });
    }
    return results;
}"""

DISCOVER_BRANDS_JS = """() => {
    const brands = new Set();
    const links = document.querySelectorAll('a[href*="/used-cars/"]');
    for (const link of links) {
        const href = link.getAttribute('href') || '';
        const m = href.match(/\\/used-cars\\/([a-z][a-z0-9-]+)\\/?$/);
        if (m) {
            const slug = m[1];
            // Skip non-brand pages
            if (['sedan','suv','mini-van','hatchback','wagon','pick-up',
                 'van','truck','buy','sell','search','tag'].includes(slug)) continue;
            brands.add(slug);
        }
    }
    return Array.from(brands).sort();
}"""

TOTAL_RESULTS_JS = """() => {
    const text = document.body.innerText || '';
    const m = text.match(/([\\d,]+)\\s*RESULTS?/i);
    return m ? parseInt(m[1].replace(/,/g, ''), 10) : 0;
}"""


def login(page, email: str, password: str) -> bool:
    """Attempt login via the sign-in button on en.guazi.com."""
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)

        # Look for login/sign-in button
        login_btn = page.query_selector(
            'button:has-text("Log"), a:has-text("Log"), '
            'button:has-text("Sign"), a:has-text("Sign")'
        )
        if not login_btn:
            print("  No login button found — continuing without auth")
            return False

        login_btn.click()
        page.wait_for_timeout(2000)

        # Try email/password fields
        email_input = page.query_selector(
            'input[type="email"], input[name="email"], '
            'input[placeholder*="email" i], input[placeholder*="Email"]'
        )
        pass_input = page.query_selector(
            'input[type="password"], input[name="password"]'
        )

        if not email_input or not pass_input:
            print("  Login form not found — continuing without auth")
            return False

        email_input.fill(email)
        pass_input.fill(password)
        page.wait_for_timeout(500)

        # Submit
        submit = page.query_selector(
            'button[type="submit"], button:has-text("Log in"), '
            'button:has-text("Sign in")'
        )
        if submit:
            submit.click()
        else:
            pass_input.press("Enter")

        page.wait_for_timeout(3000)

        if "login" not in page.url.lower():
            print("  Logged in successfully")
            return True
        print("  Login may have failed — continuing")
        return False
    except Exception as e:
        print(f"  Login error: {e} — continuing without auth")
        return False


def extract_cards_from_page(page) -> list[dict]:
    """Extract car cards from the current page using JS evaluation."""
    raw_cards = page.evaluate(EXTRACT_CARDS_JS)
    cards = []
    for raw in raw_cards:
        href = raw.get("href", "")
        # Extract slug from href: /products/{slug}.html
        slug_m = re.search(r'/products/(.+?)\.html', href)
        if not slug_m:
            continue
        slug = slug_m.group(1)
        parsed = parse_product_slug(slug)
        if not parsed:
            continue

        # Title from image alt or card text
        title = raw.get("img_alt", "").replace("Used ", "", 1).strip()
        if not title:
            # First line of card text usually is the title
            text = raw.get("text", "")
            parts = text.split(" | ")
            title = parts[0].strip() if parts else slug

        cards.append({
            "item_id": parsed["item_id"],
            "url": BASE_URL + href if href.startswith("/") else href,
            "slug": slug,
            "title": title,
            "year": parsed["year"],
            "mileage_km": parsed["mileage_km"],
            "color": parsed["color"],
            "displacement_dl": parsed["displacement_dl"],
            "transmission": parsed["transmission"],
            "drive": parsed["drive"],
            "seats": parsed["seats"],
            "price_usd": raw.get("price_usd"),
            "grade": raw.get("grade", ""),
            "seller_type": raw.get("seller_type", ""),
            "thumb_url": raw.get("img_src", ""),
        })
    return cards


def card_passes_filters(card: dict, min_year: int, max_mileage_km: int,
                        min_price_usd: int,
                        allowed_grades: set[str] | None = None) -> tuple[bool, str]:
    if card["year"] < min_year:
        return False, f"year {card['year']} < {min_year}"
    if card["mileage_km"] > max_mileage_km:
        return False, f"mileage {card['mileage_km']} > {max_mileage_km}"
    if card.get("price_usd") and card["price_usd"] < min_price_usd:
        return False, f"price ${card['price_usd']} < ${min_price_usd}"
    # Grade filter: only apply if grade was reliably extracted (non-empty)
    # AND is a known grade value. Skip if grade looks like a false positive
    # from regex matching random letters in card text.
    grade = card.get("grade", "")
    if allowed_grades and grade and len(grade) == 1 and grade in "SABCD":
        if grade not in allowed_grades:
            return False, f"grade {grade} not in {allowed_grades}"
    return True, ""


def upsert_pending(card: dict) -> bool:
    rec = {
        "source": SOURCE,
        "source_id": card["item_id"],
        "metadata": {
            "url": card["url"],
            "slug": card["slug"],
            "title": card["title"],
            "thumb_url": card.get("thumb_url"),
            "year": card["year"],
            "mileage_km": card["mileage_km"],
            "price_usd": card.get("price_usd"),
            "grade": card.get("grade"),
            "color": card.get("color"),
            "displacement_dl": card.get("displacement_dl"),
            "transmission": card.get("transmission"),
            "drive": card.get("drive"),
            "seats": card.get("seats"),
            "seller_type": card.get("seller_type"),
        },
        "found_at": DB.now_iso(),
    }
    return DB.upsert_pending(rec)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", type=str, default="")
    ap.add_argument("--max-pages-per-brand", type=int, default=50)
    ap.add_argument("--min-year", type=int, default=2021)
    ap.add_argument("--max-mileage-km", type=int, default=100_000)
    ap.add_argument("--min-price-usd", type=int, default=7_000)
    ap.add_argument("--grades", type=str, default="S,A")
    ap.add_argument("--limit", type=int, default=20_000)
    args = ap.parse_args()

    allowed_grades = set(g.strip().upper() for g in args.grades.split(",") if g.strip()) if args.grades else None

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    guazi_email = os.environ.get("GUAZI_EMAIL", "")
    guazi_password = os.environ.get("GUAZI_PASSWORD", "")

    print(f"Collecting en.guazi.com listings")
    print(f"  filters: year>={args.min_year}, mileage<={args.max_mileage_km:,}km, "
          f"price>=${args.min_price_usd:,}, grades={allowed_grades or 'any'}")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent=UA, locale="en-US", ignore_https_errors=True,
        viewport={"width": 1366, "height": 900},
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    page = ctx.new_page()

    # Optional login
    if guazi_email and guazi_password:
        login(page, guazi_email, guazi_password)

    # Discover brands from the listing page
    if args.brands:
        brand_slugs = [b.strip() for b in args.brands.split(",") if b.strip()]
    else:
        print("  Discovering brands from /used-cars/ ...")
        page.goto(f"{BASE_URL}/used-cars/", wait_until="domcontentloaded",
                  timeout=30_000)
        page.wait_for_timeout(2000)
        brand_slugs = page.evaluate(DISCOVER_BRANDS_JS)
        if not brand_slugs:
            # Fallback to hardcoded popular brands
            brand_slugs = [
                "toyota", "volkswagen", "bmw", "mercedes-benz", "audi",
                "honda", "nissan", "hyundai", "byd", "geely-auto",
                "tesla", "buick", "ford", "mazda", "kia",
                "chery", "haval", "changan", "great-wall", "volvo",
                "lexus", "porsche", "land-rover", "cadillac", "mg",
                "nio", "xpeng", "li-auto", "zeekr", "xiaomi-auto",
                "chevrolet", "subaru", "mitsubishi", "jetour",
                "hongqi", "tank", "wuling", "skoda",
            ]
        print(f"  Found {len(brand_slugs)} brands: {brand_slugs[:10]}...")

    saved = 0
    skipped = 0
    seen: set[str] = set()
    started = time.time()

    for brand_slug in brand_slugs:
        if saved >= args.limit:
            break
        brand_name = BRAND_SLUG_TO_NAME.get(brand_slug, brand_slug.replace("-", " ").title())
        print(f"\n[{brand_name}] /used-cars/{brand_slug}/")

        page_num = 1
        empty_streak = 0

        while page_num <= args.max_pages_per_brand and saved < args.limit:
            if page_num == 1:
                url = f"{BASE_URL}/used-cars/{brand_slug}/"
            else:
                url = f"{BASE_URL}/used-cars/{brand_slug}/page{page_num}/"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1500)

                # Scroll to trigger lazy-loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
            except Exception as e:
                print(f"  page {page_num}: load error — {e}")
                break

            if page_num == 1:
                total = page.evaluate(TOTAL_RESULTS_JS)
                print(f"  {total:,} results total")

            cards = extract_cards_from_page(page)
            if not cards:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                page_num += 1
                continue
            empty_streak = 0

            page_saved = 0
            for card in cards:
                if card["item_id"] in seen:
                    continue
                seen.add(card["item_id"])
                ok, reason = card_passes_filters(
                    card, args.min_year, args.max_mileage_km, args.min_price_usd,
                    allowed_grades)
                if not ok:
                    skipped += 1
                    continue
                if upsert_pending(card):
                    saved += 1
                    page_saved += 1

            elapsed = int(time.time() - started)
            print(f"  page {page_num}: {len(cards)} cards -> {page_saved} kept "
                  f"(total {saved}, {elapsed}s)")
            page_num += 1
            time.sleep(0.5)

    browser.close()
    pw.stop()

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
