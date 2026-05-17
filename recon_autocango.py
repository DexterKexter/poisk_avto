"""
recon_autocango.py — merge brand grid (with logos) + A-Z list (with counts).

Page has TWO brand sections:
  - Top grid: 40x40 logos with alt=brand name (no count)
  - Bottom A-Z list: text links with "Brand(N)" format (no logo)
Same brands appear in both. Need to merge by slug.
"""

import json
import os
import sys
import traceback

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def main() -> None:
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
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        # Collect EVERY (slug, logo, count) — both from grid imgs and text links
        result = page.evaluate(
            r"""() => {
                const byslug = {};

                // 1. Walk all <a href="...brandName=X"> — extract slug, count, logo if any
                for (const a of document.querySelectorAll('a[href*="brandName="]')) {
                    const href = a.getAttribute('href');
                    const m = href.match(/brandName=([^&\/]+)/);
                    if (!m) continue;
                    const slug = decodeURIComponent(m[1]);
                    const img = a.querySelector('img');
                    const text = (a.innerText || '').trim();
                    // Parse "Honda(60451)" -> name + count
                    const cm = text.match(/^(.+?)\s*\((\d+)\)\s*$/);
                    const name = cm ? cm[1].trim() : (img?.alt || text || slug);
                    const count = cm ? parseInt(cm[2], 10) : null;

                    const existing = byslug[slug] || {slug, name: slug,
                                                      logo_url: null, count: null,
                                                      href: new URL(href, location.origin).href};
                    // Merge: keep logo if any, prefer named count
                    if (img?.src && !existing.logo_url) {
                        existing.logo_url = img.src;
                    }
                    if (name && !name.includes('(')) existing.name = name;
                    if (count !== null) existing.count = count;
                    byslug[slug] = existing;
                }

                // 2. Walk all <img alt> that look like brand logos (40x40 area)
                for (const img of document.querySelectorAll('img[alt]')) {
                    const r = img.getBoundingClientRect();
                    if (!(r.width > 20 && r.width < 100 && r.height > 20 && r.height < 100)) continue;
                    const alt = img.alt.trim();
                    if (!alt || alt.length > 50) continue;
                    // Find ancestor link with brandName
                    const a = img.closest('a[href*="brandName="]');
                    if (!a) continue;
                    const m = a.getAttribute('href').match(/brandName=([^&\/]+)/);
                    if (!m) continue;
                    const slug = decodeURIComponent(m[1]);
                    const existing = byslug[slug] || {slug, name: alt,
                                                      logo_url: null, count: null};
                    if (img.src && !existing.logo_url) existing.logo_url = img.src;
                    if (!existing.name || existing.name === slug) existing.name = alt;
                    byslug[slug] = existing;
                }

                return Object.values(byslug);
            }"""
        )

        # Report
        print(f"Total brands: {len(result)}")
        with_logo = [b for b in result if b.get("logo_url")]
        with_count = [b for b in result if b.get("count") is not None]
        print(f"  With logo:  {len(with_logo)}")
        print(f"  With count: {len(with_count)}")

        # Sort by count desc, show top 30
        result.sort(key=lambda b: -(b.get("count") or 0))
        print(f"\nTop 30 by car count:")
        for b in result[:30]:
            logo = "🖼️" if b.get("logo_url") else "  "
            print(f"  {logo} {b.get('count', 0):>7} | {b['slug']:25} | {b['name']:30} "
                  f"| logo={ (b.get('logo_url') or '')[:60] }")

        save = os.path.join(OUT_DIR, "ucbrand_merged.json")
        with open(save, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nSaved → {save}")

        browser.close()
    print("DONE")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
