"""enrich_brand_logos.py — pull all autocango brand logos from /ucbrand and
upsert into the `brands` table.

Previously this script visited individual brand pages (/usedcar/brandName=X)
which return only the ME4.webp placeholder. The /ucbrand index page is the
single place where every brand badge is rendered (both the featured grid and
the A-Z list), so we scrape that page once and bulk-update.

Idempotent: only updates rows whose logo_url is currently NULL or placeholder.

Usage: python enrich_brand_logos.py
Env:   SUPABASE_URL, SUPABASE_KEY
"""

import os
import sys
import time
import traceback

import db as DB

sys.stdout.reconfigure(line_buffering=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")

PLACEHOLDER_LOGO = "ME4.webp"  # autocango default for brands without badge


def scrape_all_brand_logos() -> dict[str, str]:
    """Return {slug → logo_url} for every brand visible on /ucbrand."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 4000},
            locale="en-US",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()
        page.goto("https://www.autocango.com/ucbrand",
                  wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2500)
        # Force lazy-loaded images to render
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        result = page.evaluate(r"""() => {
            const out = {};
            // Each brand link has an inner <img> with the badge.
            for (const a of document.querySelectorAll('a[href*="brandName="]')) {
                const m = a.getAttribute('href').match(/brandName=([^&\/]+)/);
                if (!m) continue;
                const slug = decodeURIComponent(m[1]);
                const img = a.querySelector('img');
                if (img && img.src && !out[slug]) out[slug] = img.src;
            }
            return out;
        }""")
        browser.close()
        return result or {}


def main() -> None:
    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres for brand enrichment")

    print("Scraping /ucbrand for all brand logos via Playwright…", flush=True)
    started = time.time()
    logos = scrape_all_brand_logos()
    real = {s: u for s, u in logos.items() if PLACEHOLDER_LOGO not in u}
    print(f"  fetched {len(logos)} brand links, {len(real)} real (non-placeholder)",
          flush=True)

    if not real:
        sys.exit("No real logos discovered — page may have changed")

    # Fetch existing brands needing logo
    r = DB._pg_request(
        "GET", "brands?select=id,slug,name,logo_url&limit=1000")
    if r.status_code != 200:
        sys.exit(f"DB read failed: {r.status_code} {r.text[:200]}")
    brands = r.json()

    updated = skipped_already = skipped_no_logo = 0
    for b in brands:
        slug = b["slug"]
        existing = b.get("logo_url") or ""
        if existing and PLACEHOLDER_LOGO not in existing:
            skipped_already += 1
            continue
        new_logo = real.get(slug)
        # Also try case-insensitive match (slugs in DB sometimes lowercased)
        if not new_logo:
            for k, v in real.items():
                if k.lower() == slug.lower():
                    new_logo = v; break
        if not new_logo:
            skipped_no_logo += 1
            continue
        upd = DB._pg_request(
            "PATCH", f"brands?id=eq.{b['id']}",
            json={"logo_url": new_logo, "updated_at": DB.now_iso()})
        if upd.status_code in (200, 204):
            updated += 1
        else:
            print(f"  PATCH fail {b['id']} {slug}: {upd.status_code}",
                  flush=True)

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s.")
    print(f"  Updated:           {updated}")
    print(f"  Already had logo:  {skipped_already}")
    print(f"  No logo found:     {skipped_no_logo}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
