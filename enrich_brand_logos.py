"""
enrich_brand_logos.py — visit each brand page to find missing logos.

import_brands_autocango.py captured 35 logos from the featured grid.
Remaining 268 brands have only a text link. For each, open
/usedcar/brandName=X and grab the first logo-shaped image from the
page header (likely the brand badge).

Idempotent: skips brands that already have logo_url.

Usage: python enrich_brand_logos.py [--limit N]
Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import os
import re
import sys
import time
import traceback

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "autocango"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def find_logo_js() -> str:
    """JS that returns the most logo-like image URL on the brand page."""
    return r"""(brandName) => {
        // Looking for autocango brand-logo URLs: https://i1.autocango.com/brand/CODE.webp
        // First scan for any <img src> matching this pattern
        for (const img of document.querySelectorAll('img[src*="/brand/"]')) {
            const src = img.src;
            if (/\/brand\/[A-Z0-9]+\.webp/i.test(src)) {
                return src;
            }
        }
        // Fallback: any <img> with alt matching the brand name and small size
        for (const img of document.querySelectorAll('img[alt]')) {
            const alt = (img.alt || '').trim();
            if (alt.toLowerCase() === brandName.toLowerCase()) {
                const r = img.getBoundingClientRect();
                if (r.width > 15 && r.width < 200) return img.src;
            }
        }
        return null;
    }"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres for brand enrichment")

    # Fetch brands lacking logo
    r = DB._pg_request(
        "GET",
        f"brands?source=eq.{SOURCE}&logo_url=is.null"
        f"&select=id,slug,source_url&limit={args.limit}",
    )
    if r.status_code != 200:
        sys.exit(f"Failed to fetch brands: {r.status_code} {r.text[:200]}")
    brands = r.json()
    print(f"Found {len(brands)} brands without logo", flush=True)
    if not brands:
        return

    from playwright.sync_api import sync_playwright

    started = time.time()
    enriched = failed = 0

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
        # Warm WAF cookies
        warm = ctx.new_page()
        try:
            warm.goto("https://www.autocango.com/usedcar/excludeSold=true",
                      wait_until="networkidle", timeout=60_000)
        except Exception:
            pass
        warm.close()
        page = ctx.new_page()
        finder = find_logo_js()

        for i, b in enumerate(brands, 1):
            slug = b["slug"]
            url = b.get("source_url") or f"https://www.autocango.com/usedcar/brandName={slug}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(800)
                logo = page.evaluate(finder, slug)
            except Exception as e:
                logo = None
                print(f"  [{i}/{len(brands)}] {slug:25} EXCEPTION: {str(e)[:80]}", flush=True)

            if logo:
                upd = DB._pg_request(
                    "PATCH",
                    f"brands?id=eq.{b['id']}",
                    json={"logo_url": logo, "updated_at": DB.now_iso()},
                )
                if upd.status_code in (200, 204):
                    enriched += 1
                    if i % 20 == 0 or i <= 5:
                        elapsed = int(time.time() - started)
                        print(f"  [{i}/{len(brands)}] {slug:25} ✅ ({elapsed}s elapsed)",
                              flush=True)
                else:
                    failed += 1
                    print(f"  [{i}/{len(brands)}] {slug:25} db fail: "
                          f"{upd.status_code}", flush=True)
            else:
                failed += 1
                if i % 30 == 0 or i <= 5:
                    print(f"  [{i}/{len(brands)}] {slug:25} ❌ no logo",
                          flush=True)

        browser.close()

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. Enriched: {enriched}, no-logo: {failed}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
