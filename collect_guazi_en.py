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

        const text = (card.innerText || '');
        const textFlat = text.replace(/\\n+/g, ' | ');

        // Grade: look for "Grade\\nS" or "Grade\\nA" pattern
        let grade = '';
        const gradeMatch = text.match(/Grade\\s*\\n\\s*([SABCD])/);
        if (gradeMatch) {
            grade = gradeMatch[1];
        } else {
            const gradeEl = card.querySelector('[class*="grade" i]');
            if (gradeEl) {
                const gt = (gradeEl.innerText || '').replace(/Grade/i, '').trim();
                if (gt.length === 1 && 'SABCD'.includes(gt)) grade = gt;
            }
        }

        // Price: look for FOB Price pattern or $XX,XXX
        let price = null;
        const priceMatch = text.match(/\\$([\\d,]+)/);
        if (priceMatch) {
            price = parseInt(priceMatch[1].replace(/,/g, ''), 10);
        }

        // Title: find the link text or <img alt="Used ...">
        // The product link itself or nearby heading usually has the car name
        let title = '';
        // Try: img alt attribute (often "Used BMW 3 Series 2021 ...")
        const imgs = card.querySelectorAll('img');
        for (const img of imgs) {
            const alt = (img.alt || '').trim();
            if (alt.startsWith('Used ')) {
                title = alt.replace(/^Used /, '');
                break;
            }
        }
        // Fallback: find line that looks like a car name (contains year 20XX)
        if (!title) {
            const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 10);
            for (const line of lines) {
                if (/\\b20[12]\\d\\b/.test(line) && !line.includes('$') && !line.includes('Grade')) {
                    title = line.replace(/^Used /, '');
                    break;
                }
            }
        }

        // Image: find car photo (not icons/badges)
        let imgSrc = '';
        for (const img of imgs) {
            const src = img.src || img.getAttribute('data-src') || '';
            if (src.includes('guazistatic.com') || (src.includes('image') && !src.includes('icon') && !src.includes('assets'))) {
                imgSrc = src;
                break;
            }
        }

        // Seller type
        let sellerType = '';
        if (textFlat.includes('Certified Dealer')) sellerType = 'dealer';
        else if (textFlat.includes('Guazi Owned')) sellerType = 'guazi_owned';
        else if (textFlat.includes('Individual')) sellerType = 'individual';

        results.push({
            href: href,
            text: textFlat.substring(0, 500),
            grade: grade,
            price_usd: price,
            img_src: imgSrc,
            img_alt: title,
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

        # Title from JS extraction, or build from slug
        title = raw.get("img_alt", "").replace("Used ", "", 1).strip()
        if not title or title in ("Grade", "S", "A", "B", "C", "D"):
            # Build readable title from slug: "bmw-3-series" → "BMW 3 Series"
            brand_series = parsed["brand_series_slug"]
            title = brand_series.replace("-", " ").title() + f" {parsed['year']}"

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


def build_search_url(brand: str | None, min_price: int, min_year: int,
                     max_mileage: int, grades: str, seller_types: str,
                     page: int) -> str:
    """Build en.guazi.com search URL with server-side filters.

    If brand is given, scope to /used-cars/{brand}/. Otherwise global /used-cars/.
    """
    params = {
        "price": f"{min_price},",
        "licenseYear": f"{min_year},",
        "roadHaul": f"0,{max_mileage}",
    }
    if grades:
        params["detectionLevels"] = grades
    if seller_types:
        params["vehicleSourceClassificationCustomers"] = seller_types
    if page > 1:
        params["page"] = str(page)
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    path = f"/used-cars/{brand}/" if brand else "/used-cars/"
    return f"{BASE_URL}{path}?{qs}"


def discover_brands(page) -> list[str]:
    """Extract brand slugs from /used-cars/ navigation.

    The brand nav links are present in SSR HTML, so a single goto + evaluate
    is enough. We retry a few times (the page occasionally times out) and try
    both the bare and a filtered URL before giving up. Callers should fall
    back to the built-in BRAND_SLUG_TO_NAME list if this returns few brands.
    """
    urls = [
        f"{BASE_URL}/used-cars/",
        build_search_url(None, 7000, 2021, 100000, "S,A", "", 1),
    ]
    for attempt in range(3):
        url = urls[attempt % len(urls)]
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            brands = page.evaluate(DISCOVER_BRANDS_JS)
            if brands:
                return brands
            print(f"  discovery attempt {attempt + 1}: 0 brands from {url}")
        except Exception as e:
            print(f"  discovery attempt {attempt + 1} failed: {e}")
        time.sleep(2)
    return []


def new_browser_ctx(pw):
    """Spin up a fresh browser/context/page (used to recycle fingerprint)."""
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
    return browser, ctx, page


def crawl_brand(page, brand: str, args, seen: set[str], saved_so_far: int,
                started: float) -> tuple[int, int]:
    """Walk pages for one brand. Returns (saved_added, pages_walked)."""
    import random
    saved_added = 0
    empty_streak = 0
    page_num = 1
    pages_walked = 0
    while (page_num <= args.max_pages_per_brand
           and saved_so_far + saved_added < args.limit):
        url = build_search_url(
            brand, args.min_price_usd, args.min_year, args.max_mileage_km,
            args.grades, args.seller_types, page_num)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(int(random.uniform(1200, 2500)))
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(int(random.uniform(600, 1200)))

            if page_num == 1:
                total = page.evaluate(TOTAL_RESULTS_JS)
                print(f"  [{brand}] {total:,} results")

            cards = extract_cards_from_page(page)
        except Exception as e:
            # "Execution context was destroyed" etc — anti-bot navigation /
            # redirect mid-evaluate. Skip this page instead of crashing the run.
            print(f"  [{brand}] page {page_num}: load/parse error — {e}")
            empty_streak += 1
            if empty_streak >= 2:
                break
            page_num += 1
            continue

        if not cards:
            empty_streak += 1
            if empty_streak >= 2:
                break
            page_num += 1
            continue
        empty_streak = 0
        pages_walked = page_num

        page_saved = 0
        for card in cards:
            if card["item_id"] in seen:
                continue
            seen.add(card["item_id"])
            if upsert_pending(card):
                saved_added += 1
                page_saved += 1

        elapsed = int(time.time() - started)
        print(f"  [{brand}] page {page_num}: {len(cards)} cards "
              f"-> {page_saved} new (brand total {saved_added}, "
              f"grand total {saved_so_far + saved_added}, {elapsed}s)")
        page_num += 1
        time.sleep(random.uniform(1.0, 2.5))

    return saved_added, pages_walked


def main() -> None:
    import random
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-year", type=int, default=2021)
    ap.add_argument("--max-mileage-km", type=int, default=100_000)
    ap.add_argument("--min-price-usd", type=int, default=7_000)
    ap.add_argument("--grades", type=str, default="S,A")
    ap.add_argument("--seller-types", type=str, default="180003,180002",
                    help="180003=Guazi Owned, 180002=Certified Dealer")
    ap.add_argument("--max-pages", type=int, default=500,
                    help="(legacy) hard cap on total pages")
    ap.add_argument("--max-pages-per-brand", type=int, default=30,
                    help="guazi caps pagination at ~25 pages per scope")
    ap.add_argument("--brands", type=str, default="",
                    help="comma-separated brand slugs (default: auto-discover)")
    ap.add_argument("--brand-recycle-every", type=int, default=10,
                    help="restart browser after this many brands to dodge anti-bot")
    ap.add_argument("--limit", type=int, default=20_000)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    guazi_email = os.environ.get("GUAZI_EMAIL", "")
    guazi_password = os.environ.get("GUAZI_PASSWORD", "")

    print(f"Collecting en.guazi.com per-brand (server-side filtered)")
    print(f"  price>=${args.min_price_usd:,}, year>={args.min_year}, "
          f"mileage<={args.max_mileage_km:,}km, grades={args.grades}")

    pw = sync_playwright().start()
    browser, ctx, page = new_browser_ctx(pw)

    if guazi_email and guazi_password:
        login(page, guazi_email, guazi_password)

    builtin = sorted(BRAND_SLUG_TO_NAME.keys())
    if args.brands.strip():
        brands = [b.strip() for b in args.brands.split(",") if b.strip()]
        print(f"  brands (manual): {len(brands)}")
    else:
        discovered = discover_brands(page)
        # Merge discovery with the built-in catalog so a flaky/empty discovery
        # never aborts the run. Discovered-only slugs (new brands) are kept too.
        merged = sorted(set(discovered) | set(builtin))
        print(f"  brands discovered: {len(discovered)}, "
              f"built-in: {len(builtin)}, crawling: {len(merged)}")
        brands = merged
    if not brands:
        sys.exit("No brands to crawl — aborting")

    random.shuffle(brands)

    saved = 0
    seen: set[str] = set()
    started = time.time()
    brands_done = 0
    for brand in brands:
        if saved >= args.limit:
            print(f"  collect_limit reached ({saved}), stopping")
            break

        try:
            added, pages = crawl_brand(page, brand, args, seen, saved, started)
        except Exception as e:
            # A crashed page/context shouldn't abort the whole run — recycle
            # the browser and move to the next brand.
            print(f"  ==> [{brand}] crawl error — {e}; recycling browser")
            try:
                browser.close()
            except Exception:
                pass
            browser, ctx, page = new_browser_ctx(pw)
            continue
        saved += added
        brands_done += 1
        print(f"  ==> [{brand}] +{added} new, {pages} pages "
              f"(grand total {saved}, {brands_done}/{len(brands)} brands)")

        if brands_done % args.brand_recycle_every == 0:
            print(f"  recycling browser after {brands_done} brands...")
            try:
                browser.close()
            except Exception:
                pass
            browser, ctx, page = new_browser_ctx(pw)
            time.sleep(random.uniform(2.0, 4.0))

    try:
        browser.close()
    finally:
        pw.stop()

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. Saved: {saved} from {brands_done} brands")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
