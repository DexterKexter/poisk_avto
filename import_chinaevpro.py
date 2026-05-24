"""
import_chinaevpro.py — scrape Chinese EV brands + models from chinaevpro.com
and upsert into Supabase `brands` and `models` tables.

Workflow:
  1. Fetch /brands listing page → extract 59 brand slugs
  2. For each brand, fetch /brands/{slug} → parse brand info + model cards
     from the Next.js RSC payload embedded in the SSR HTML
  3. Upsert brands (on_conflict=slug) and models (on_conflict=slug)

Usage:  python import_chinaevpro.py [--limit N] [--brands byd,nio]
Env:    SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from typing import Any

import urllib3
import requests

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

import db as DB

# Suppress SSL warnings (system clock may be ahead of cert validity)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "chinaevpro"
BASE_URL = "https://www.chinaevpro.com"
SUPABASE_STORAGE = (
    "https://thzpihfbglhksxsimprj.supabase.co"
    "/storage/v1/object/public"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

HEADERS = {"User-Agent": UA, "Accept": "text/html"}

# ------------------------------------------------------------------ helpers


def _fetch(url: str, retries: int = 3) -> str | None:
    """GET a URL and return its text, with retries."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            if r.status_code == 200:
                return r.text
            print(f"    HTTP {r.status_code} for {url} (attempt {attempt})")
        except requests.RequestException as e:
            print(f"    request error: {str(e)[:100]} (attempt {attempt})")
        if attempt < retries:
            time.sleep(2 * attempt)
    return None


def _decode_rsc_payload(html: str) -> str:
    """Extract and concatenate all Next.js RSC payload chunks from HTML."""
    chunks: list[str] = []
    for m in re.finditer(
        r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL
    ):
        try:
            decoded = json.loads('"' + m.group(1) + '"')
            chunks.append(decoded)
        except (json.JSONDecodeError, ValueError):
            chunks.append(m.group(1))
    return "".join(chunks)


def _slugify(brand_slug: str, model_name: str) -> str:
    """Build a model slug like 'byd-seal-06-dm-i' from brand slug + model name."""
    raw = f"{brand_slug}-{model_name}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug


# ------------------------------------------------- scrape brands listing


def fetch_brand_slugs() -> list[str]:
    """Fetch /brands and return all brand slugs."""
    html = _fetch(f"{BASE_URL}/brands")
    if not html:
        sys.exit("Failed to fetch /brands listing")

    payload = _decode_rsc_payload(html)
    raw_slugs = re.findall(r'/brands/([\w-]+)', payload)

    # Deduplicate preserving order, skip non-brand entries
    seen: set[str] = set()
    slugs: list[str] = []
    skip = {"page-", "layout-", "loading-"}
    for s in raw_slugs:
        if s in seen or any(s.startswith(p) for p in skip):
            continue
        seen.add(s)
        slugs.append(s)

    return slugs


# ------------------------------------------------- scrape one brand page


def parse_brand_page(slug: str, html: str) -> dict[str, Any]:
    """Parse brand info + model list from a brand page's RSC payload.

    Returns dict with keys:
        brand: {name, slug, logo_url, description, source_url, country, source}
        models: [{name, slug, body_type, image_url, source}]
    """
    payload = _decode_rsc_payload(html)

    # --- brand name (from h1 tag in RSC) ---
    brand_name = slug  # fallback
    h1 = re.search(
        r'text-4xl font-bold text-gray-900"[^}]*"children":"([^"]+)"',
        payload,
    )
    if h1:
        brand_name = h1.group(1)

    # --- logo ---
    logo_url = None
    logo_match = re.search(r'brand-logos/([\w.-]+)', payload)
    if logo_match:
        logo_url = f"{SUPABASE_STORAGE}/brand-logos/{logo_match.group(1)}"

    # --- description ---
    description = None
    desc_match = re.search(
        r'leading-relaxed[^"]*"[^}]*"children":"([^"]{20,})"',
        payload,
    )
    if desc_match:
        description = desc_match.group(1)

    # --- established year ---
    # Pattern: "Established YYYY"
    year_match = re.search(r'"children":"Established (\d{4})"', payload)

    # --- model cards ---
    models: list[dict] = []
    model_sections = payload.split("model-images/")

    # Collect model link slugs for cross-referencing
    model_link_slugs = re.findall(r'/models/([\w-]+)', payload)
    # Deduplicate preserving order
    seen_links: set[str] = set()
    unique_links: list[str] = []
    for lnk in model_link_slugs:
        if lnk not in seen_links:
            seen_links.add(lnk)
            unique_links.append(lnk)

    # Collect prices from font-bold text-green-600
    # In the decoded RSC payload, prices appear as "$$14,000" (literal double dollar)
    prices: list[str] = []
    for pm in re.finditer(
        r'font-bold text-green-600"[^}]*"children":"\$\$([\d,]+)"',
        payload,
    ):
        prices.append(pm.group(1))
    if not prices:
        # Fallback: try escaped form
        for pm in re.finditer(
            r'font-bold text-green-600[^}]*"children":"[^"]*?([\d]{1,3}(?:,\d{3})+)"',
            payload,
        ):
            prices.append(pm.group(1))

    for idx, section in enumerate(model_sections[1:]):
        # Image filename
        img_match = re.match(r'([\w.-]+)', section)
        if not img_match:
            continue
        img_file = img_match.group(1)
        image_url = f"{SUPABASE_STORAGE}/model-images/{img_file}"

        # Model name from alt attribute
        alt_match = re.search(r'"alt":"([^"]+)"', section)
        model_name = alt_match.group(1) if alt_match else ""
        if not model_name:
            continue

        # Body type from text-muted-foreground
        body_match = re.search(
            r'text-muted-foreground"[^}]*"children":"([^"]+)"',
            section,
        )
        body_type = body_match.group(1) if body_match else None

        # Model slug: try to match from model links
        model_slug = _slugify(slug, model_name)
        # Use the canonical slug from /models/ links if available
        for link_slug in unique_links:
            link_name = link_slug.replace(slug + "-", "", 1)
            if link_name.lower().replace("-", " ") == model_name.lower().replace("-", " "):
                model_slug = link_slug
                break

        # Price from parallel list
        price_usd = None
        if idx < len(prices):
            try:
                price_usd = int(prices[idx].replace(",", ""))
            except ValueError:
                pass

        models.append({
            "name": model_name,
            "slug": model_slug,
            "body_type": body_type,
            "image_url": image_url,
            "price_from_usd": price_usd,
            "source": SOURCE,
        })

    return {
        "brand": {
            "name": brand_name,
            "slug": slug,
            "logo_url": logo_url,
            "country": "China",
            "source": SOURCE,
            "source_url": f"{BASE_URL}/brands/{slug}",
        },
        "models": models,
    }


# ------------------------------------------------- full models via Playwright

EXTRACT_MODELS_JS = """(brandSlug) => {
    const cards = document.querySelectorAll('a[href*="/models/"]');
    const results = [];
    const seen = new Set();
    for (const card of cards) {
        const href = card.getAttribute('href') || '';
        if (!href.startsWith('/models/') || href === '/models/' || seen.has(href)) continue;
        seen.add(href);
        const slug = href.replace('/models/', '');

        const text = card.innerText || '';
        const lines = text.split('\\n').map(l => l.trim()).filter(l => l);

        let name = '', bodyType = '', price = null;
        for (const line of lines) {
            if (line === 'Available' || line === 'Upcoming' || line === 'View Details') continue;
            if (/^(Sedan|SUV|Hatchback|Minivan|Coupe|Wagon|Pickup|Van|Truck|Liftback|MPV|Shooting Brake|Coupe SUV|Sports Car)/i.test(line)) {
                bodyType = line;
            } else if (/^\\$[\\d,]+$/.test(line)) {
                price = parseInt(line.replace(/[$,]/g, ''), 10);
            } else if (!name && line.length > 1 && !/^From/.test(line)) {
                name = line;
            }
        }

        const img = card.querySelector('img');
        const imgSrc = img ? (img.src || img.getAttribute('data-src') || '') : '';

        if (name) {
            results.push({ name, slug, bodyType, price, imgSrc });
        }
    }
    return results;
}"""


def fetch_all_models_playwright(brand_slug: str, page) -> list[dict]:
    """Fetch ALL models for a brand via /models?brand={slug} using Playwright."""
    url = f"{BASE_URL}/models?brand={brand_slug}"
    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(2000)
        # Scroll to load all
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        raw = page.evaluate(EXTRACT_MODELS_JS, brand_slug)
        models = []
        for r in raw:
            model = {
                "name": r["name"],
                "slug": r["slug"],
                "body_type": r.get("bodyType") or None,
                "price_from_usd": r.get("price") or None,
                "source": SOURCE,
            }
            img = r.get("imgSrc", "")
            if img and "model-images" in img:
                model["image_url"] = img
            models.append(model)
        return models
    except Exception as e:
        print(f"  Playwright error for {brand_slug}: {e}")
        return []


# ------------------------------------------------- database upserts


def upsert_brand(rec: dict) -> bool:
    """Upsert a brand row.

    Tries on_conflict=slug first (simple unique on slug).
    Falls back to on_conflict=source,slug (composite unique) if the first fails.
    """
    rec = {**rec, "updated_at": DB.now_iso()}

    # Try slug-only constraint first
    r = DB._pg_request(
        "POST",
        "brands?on_conflict=slug",
        headers={"Prefer": "return=representation,resolution=merge-duplicates"},
        json=rec,
    )
    if r.status_code in (200, 201):
        try:
            return r.json()[0].get("id")
        except (IndexError, KeyError, TypeError):
            return True
    if r.status_code == 204:
        return True

    # Fallback: composite unique (source, slug)
    if r.status_code in (400, 409):
        r2 = DB._pg_request(
            "POST",
            "brands?on_conflict=source,slug",
            headers={"Prefer": "return=representation,resolution=merge-duplicates"},
            json=rec,
        )
        if r2.status_code in (200, 201):
            try:
                return r2.json()[0].get("id")
            except (IndexError, KeyError, TypeError):
                return True
        if r2.status_code == 204:
            return True
        print(f"  brand upsert FAIL {r2.status_code}: {r2.text[:300]}")
        return False

    print(f"  brand upsert FAIL {r.status_code}: {r.text[:300]}")
    return False


def upsert_model(rec: dict) -> bool:
    """Upsert a model row.

    Tries on_conflict=slug first, falls back to on_conflict=source,slug.
    """
    rec = {**rec, "updated_at": DB.now_iso()}

    r = DB._pg_request(
        "POST",
        "models?on_conflict=brand_id,slug,source",
        headers={"Prefer": "return=minimal,resolution=merge-duplicates"},
        json=rec,
    )
    if r.status_code in (200, 201, 204):
        return True
    print(f"  model upsert FAIL {r.status_code}: {r.text[:300]}")
    return False


def get_brand_id(slug: str) -> int | None:
    """Look up brand id by slug."""
    r = DB._pg_request("GET", f"brands?slug=eq.{slug}&select=id")
    if r.status_code == 200:
        rows = r.json()
        if rows:
            return rows[0]["id"]
    return None


# ------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description="Import Chinese EV brands from chinaevpro.com")
    ap.add_argument("--brands", type=str, default="",
                    help="Comma-separated brand slugs to process (default: all)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process only first N brands (0 = all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Scrape only, print results, skip DB writes")
    args = ap.parse_args()

    if not args.dry_run and not DB.USE_POSTGRES:
        sys.exit("Need Postgres (SUPABASE_URL + SUPABASE_KEY)")

    print("=== import_chinaevpro.py ===\n")

    # 1. Get brand slugs
    print("Fetching brand slugs from /brands…")
    all_slugs = fetch_brand_slugs()
    print(f"  Found {len(all_slugs)} brands\n")

    if args.brands:
        wanted = {s.strip().lower() for s in args.brands.split(",")}
        all_slugs = [s for s in all_slugs if s in wanted]
        print(f"  Filtered to {len(all_slugs)}: {all_slugs}\n")

    if args.limit:
        all_slugs = all_slugs[: args.limit]
        print(f"  Limited to {len(all_slugs)} brands\n")

    if not all_slugs:
        print("Nothing to process.")
        return

    # 2. Start Playwright for full model catalog
    pw_page = None
    if HAS_PLAYWRIGHT and not args.dry_run:
        print("Starting Playwright for full model catalog...")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  viewport={"width": 1366, "height": 900})
        pw_page = ctx.new_page()

    started = time.time()
    brands_ok = 0
    brands_fail = 0
    models_ok = 0
    models_fail = 0

    for bi, slug in enumerate(all_slugs, 1):
        elapsed = int(time.time() - started)
        print(f"[{bi}/{len(all_slugs)}] {slug} ({elapsed}s elapsed)")

        html = _fetch(f"{BASE_URL}/brands/{slug}")
        if not html:
            print(f"  SKIP — could not fetch page")
            brands_fail += 1
            continue

        data = parse_brand_page(slug, html)
        brand = data["brand"]
        models = data["models"]

        # Fetch FULL model catalog via Playwright (not just 6 featured)
        if pw_page:
            full_models = fetch_all_models_playwright(slug, pw_page)
            if full_models:
                # Merge: full_models is authoritative, keep RSC models as fallback
                existing_slugs = {m["slug"] for m in full_models}
                for m in models:
                    if m["slug"] not in existing_slugs:
                        full_models.append(m)
                models = full_models

        print(f"  brand: {brand['name']}, logo={'yes' if brand['logo_url'] else 'no'}, "
              f"models={len(models)}")

        if args.dry_run:
            # Print what would be written
            for mi, model in enumerate(models):
                p = model.get("price_from_usd")
                print(f"    [{mi+1}] {model['name']:25} {model.get('body_type','?'):18} "
                      f"${p:>7,}" if p else
                      f"    [{mi+1}] {model['name']:25} {model.get('body_type','?'):18} "
                      f"$    N/A")
            brands_ok += 1
            models_ok += len(models)
            continue

        # Upsert brand
        result = upsert_brand(brand)
        if result:
            brands_ok += 1
        else:
            brands_fail += 1
            continue

        # Get brand_id for FK
        brand_id = get_brand_id(slug)
        if not brand_id:
            print(f"  WARNING: could not resolve brand_id for {slug}")

        # Upsert models
        for mi, model in enumerate(models):
            if brand_id:
                model["brand_id"] = brand_id
            ok = upsert_model(model)
            if ok:
                models_ok += 1
            else:
                models_fail += 1

        # Small delay to be polite
        if bi < len(all_slugs):
            time.sleep(0.5)

    if pw_page:
        browser.close()
        pw.stop()

    elapsed = int(time.time() - started)
    print(f"\n=== Done in {elapsed}s ===")
    print(f"  Brands:  {brands_ok} ok, {brands_fail} failed")
    print(f"  Models:  {models_ok} ok, {models_fail} failed")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
