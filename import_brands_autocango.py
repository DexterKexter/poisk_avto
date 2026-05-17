"""
import_brands_autocango.py — scrape /ucbrand and populate `brands` table.

For each brand:
  - slug (URL token, e.g. "BMW", "Land Rover")
  - name (display, parsed from "Honda(60451)" → "Honda")
  - logo_url (if visible in featured grid; null for tail of A-Z list)
  - source_url (/usedcar/brandName=X)
  - cars_count (parsed from text)

Usage: python import_brands_autocango.py
Env: SUPABASE_URL, SUPABASE_KEY
"""

import json
import os
import sys
import traceback

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "autocango"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def fetch_brands() -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 4000},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()
        page.goto("https://www.autocango.com/ucbrand",
                  wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2500)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        result = page.evaluate(
            r"""() => {
                const byslug = {};

                // 1. A-Z list: <a href="...brandName=X"> with text "Brand(N)"
                for (const a of document.querySelectorAll('a[href*="brandName="]')) {
                    const href = a.getAttribute('href');
                    const m = href.match(/brandName=([^&\/]+)/);
                    if (!m) continue;
                    const slug = decodeURIComponent(m[1]);
                    const img = a.querySelector('img');
                    const text = (a.innerText || '').trim();
                    const cm = text.match(/^(.+?)\s*\((\d+)\)\s*$/);
                    const name = cm ? cm[1].trim() : (img?.alt || text || slug);
                    const count = cm ? parseInt(cm[2], 10) : null;

                    const existing = byslug[slug] || {
                        slug, name: slug, logo_url: null, count: null,
                        href: new URL(href, location.origin).href,
                    };
                    if (img?.src && !existing.logo_url) existing.logo_url = img.src;
                    if (name && !name.includes('(')) existing.name = name;
                    if (count !== null) existing.count = count;
                    byslug[slug] = existing;
                }

                // 2. Featured grid: small <img alt="Brand"> with ancestor <a brandName>
                for (const img of document.querySelectorAll('img[alt]')) {
                    const r = img.getBoundingClientRect();
                    if (!(r.width > 20 && r.width < 100
                          && r.height > 20 && r.height < 100)) continue;
                    const alt = img.alt.trim();
                    if (!alt || alt.length > 50) continue;
                    const a = img.closest('a[href*="brandName="]');
                    if (!a) continue;
                    const m = a.getAttribute('href').match(/brandName=([^&\/]+)/);
                    if (!m) continue;
                    const slug = decodeURIComponent(m[1]);
                    const existing = byslug[slug] || {
                        slug, name: alt, logo_url: null, count: null,
                        href: new URL(a.getAttribute('href'), location.origin).href,
                    };
                    if (img.src && !existing.logo_url) existing.logo_url = img.src;
                    if (!existing.name || existing.name === slug) existing.name = alt;
                    byslug[slug] = existing;
                }

                return Object.values(byslug);
            }"""
        )
        browser.close()
        return result


def main() -> None:
    print("Fetching brands from autocango.com/ucbrand…", flush=True)
    brands = fetch_brands()
    print(f"  found {len(brands)} brands", flush=True)
    if not brands:
        print("Nothing to import", flush=True)
        return

    with_logo = sum(1 for b in brands if b.get("logo_url"))
    print(f"  with logo: {with_logo}", flush=True)
    print(f"  with count: {sum(1 for b in brands if b.get('count') is not None)}", flush=True)

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres (Supabase) for brands table")

    saved = 0
    for b in brands:
        rec = {
            "slug": b["slug"],
            "name": b["name"],
            "logo_url": b.get("logo_url"),
            "source": SOURCE,
            "source_url": b.get("href"),
            "cars_count": b.get("count") or 0,
            "updated_at": DB.now_iso(),
        }
        r = DB._pg_request(
            "POST",
            "brands?on_conflict=source,slug",
            headers={"Prefer": "return=minimal,resolution=merge-duplicates"},
            json=rec,
        )
        if r.status_code in (200, 201, 204):
            saved += 1
        else:
            print(f"  FAIL {b['slug']}: {r.status_code} {r.text[:200]}", flush=True)

    print(f"\nUpserted {saved}/{len(brands)} brands", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
