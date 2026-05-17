"""
recon_autocango.py — extract FULL brand list with logos from /ucbrand.

From v1: brands are <a href="/usedcar/brandName=X"> with <img> inside.
Logo is 40x40, alt=brand name. There are 60+ brands total.

This run: extract ALL such pairs (no size filtering, just match by URL
pattern), dedupe, save complete list.
"""

import json
import os
import re
import sys
import traceback

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def main() -> None:
    print("recon_autocango: full brand list from /ucbrand", flush=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 4000},  # tall to render all
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        url = "https://www.autocango.com/ucbrand"
        print(f"Loading {url}…", flush=True)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2000)
        # Scroll to bottom to lazy-load any deferred images
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        # Extract every <a href="/usedcar/brandName=...">
        brands = page.evaluate(
            r"""() => {
                const out = [];
                const seen = new Set();
                for (const a of document.querySelectorAll('a[href*="brandName="]')) {
                    const href = a.getAttribute('href');
                    const m = href.match(/brandName=([^&\/]+)/);
                    if (!m) continue;
                    const slug = decodeURIComponent(m[1]);
                    if (seen.has(slug)) continue;
                    seen.add(slug);

                    const img = a.querySelector('img');
                    out.push({
                        slug,
                        name: img?.alt || a.innerText.trim() || slug,
                        logo_url: img?.src || null,
                        href: new URL(href, location.origin).href,
                        // any text in card (might include count of cars)
                        text: a.innerText.trim().slice(0, 100),
                    });
                }
                return out;
            }"""
        )

        print(f"\n  Extracted {len(brands)} unique brands\n", flush=True)
        for b in brands:
            logo = b.get("logo_url") or "(no logo)"
            print(f"    {b['slug']:25} | {b['name']:25} | {logo[:80]}", flush=True)

        save = os.path.join(OUT_DIR, "ucbrand_full.json")
        with open(save, "w", encoding="utf-8") as f:
            json.dump(brands, f, ensure_ascii=False, indent=2)
        print(f"\nSaved → {save}", flush=True)

        # Also test going INTO one brand page to see models / car count
        if brands:
            sample_brand = "BYD"
            sample_url = f"https://www.autocango.com/usedcar/brandName={sample_brand}"
            print(f"\n========== Drilling into {sample_brand} brand page ==========",
                  flush=True)
            page.goto(sample_url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(2000)
            sample = page.evaluate(
                r"""() => {
                    // Total count if shown
                    const text = document.body.innerText;
                    const countMatch = text.match(/(\d+)\s+(?:results|cars|items)/i);
                    const cards = document.querySelectorAll('div.car-item');
                    // Unique models from car titles
                    const models = new Set();
                    for (const card of cards) {
                        const link = card.querySelector('a[href*="/sku/"]');
                        if (!link) continue;
                        const m = link.href.match(/usedcar-[^-]+-(.+?)-[A-Z]{2,4}\d+/);
                        if (m) models.add(m[1]);
                    }
                    return {
                        count_text: countMatch ? countMatch[0] : null,
                        cards_visible: cards.length,
                        unique_models: [...models],
                    };
                }"""
            )
            print(f"  cards visible: {sample['cards_visible']}", flush=True)
            print(f"  count text: {sample['count_text']}", flush=True)
            print(f"  unique models on page 1: {sample['unique_models']}", flush=True)

        browser.close()
    print("\nDONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
