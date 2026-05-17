"""
recon_autocango.py v10 — DOM scraping via playwright.

Phase A from v9 confirmed: playwright passes WAF and loads full HTML.
Phase B (direct API) hits 403 due to CSRF/signature checks.

v10: skip the API entirely. After page renders, query the DOM for
car cards using CSS selectors. Try several common patterns until
we find the right one, then extract fields.
"""

import json
import os
import re
import sys
import traceback

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

LISTING_URL = "https://www.autocango.com/usedcar/excludeSold=true"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def main() -> None:
    print("recon_autocango v10: DOM scraping", flush=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        print(f"\nLoading {LISTING_URL}…", flush=True)
        page.goto(LISTING_URL, wait_until="networkidle", timeout=60_000)
        print(f"  Title: {page.title()!r}", flush=True)
        page.wait_for_timeout(2000)  # extra time for Vue to render

        # Use JS to discover the card structure programmatically.
        print("\nProbing DOM for car cards…", flush=True)
        probe = page.evaluate(
            """() => {
                // Look for href patterns that likely lead to detail pages
                const links = Array.from(document.querySelectorAll('a[href*="/usedcar/"]'));
                const detailLinks = links.filter(a => /\\/(?:usedcar|car)\\/[A-Z]+\\d{6,}/.test(a.href));

                // Find unique card containers by walking up from detail links
                const cards = [];
                const seenContainers = new Set();
                for (const a of detailLinks.slice(0, 30)) {
                    let el = a;
                    // Walk up to find a "card-like" container
                    for (let i = 0; i < 5; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        // A reasonable card is 200-2000px tall and 100-800px wide
                        const r = el.getBoundingClientRect();
                        if (r.height > 100 && r.height < 2000 && el.children.length >= 2) {
                            if (!seenContainers.has(el)) {
                                seenContainers.add(el);
                                cards.push({
                                    tag: el.tagName,
                                    classes: el.className,
                                    inner_h: el.innerHTML.length,
                                    children: el.children.length,
                                });
                            }
                            break;
                        }
                    }
                }

                return {
                    detailLinkCount: detailLinks.length,
                    firstHrefs: detailLinks.slice(0, 5).map(a => a.href),
                    cardSamples: cards.slice(0, 3),
                };
            }"""
        )
        print(f"  Detail-link count: {probe['detailLinkCount']}", flush=True)
        print(f"  Sample hrefs:", flush=True)
        for h in probe["firstHrefs"]:
            print(f"    {h}", flush=True)
        print(f"  Card containers found:", flush=True)
        for c in probe["cardSamples"]:
            print(f"    {c['tag']}.{c['classes']!r} ({c['children']} children, "
                  f"{c['inner_h']} chars)", flush=True)

        # Now extract structured data: for each unique car link, capture surrounding text
        print("\nExtracting cars from DOM…", flush=True)
        cars = page.evaluate(
            """() => {
                const out = [];
                const seenIds = new Set();
                const links = document.querySelectorAll('a[href*="/usedcar/"]');

                for (const a of links) {
                    const m = a.href.match(/\\/(usedcar|car)\\/([A-Z]+\\d{6,})/);
                    if (!m) continue;
                    const id = m[2];
                    if (seenIds.has(id)) continue;
                    seenIds.add(id);

                    // Find parent that contains the most info
                    let card = a;
                    for (let i = 0; i < 6; i++) {
                        const parent = card.parentElement;
                        if (!parent) break;
                        const r = parent.getBoundingClientRect();
                        if (r.height > 300 || parent.children.length >= 3) {
                            card = parent;
                            break;
                        }
                        card = parent;
                    }

                    out.push({
                        id: id,
                        href: a.href,
                        // Get all text inside card (separated by | for readability)
                        text: card.innerText.replace(/\\n+/g, ' | ').trim().slice(0, 600),
                        // Get all images
                        images: Array.from(card.querySelectorAll('img'))
                            .map(i => i.src).filter(s => s).slice(0, 5),
                        // Get attributes that might hold data
                        data_attrs: Array.from(card.attributes)
                            .filter(a => a.name.startsWith('data-'))
                            .map(a => ({name: a.name, value: a.value})),
                    });
                }
                return out;
            }"""
        )

        print(f"  Found {len(cars)} unique car cards\n", flush=True)
        if cars:
            print("===== FIRST 3 CARS =====", flush=True)
            for i, c in enumerate(cars[:3], 1):
                print(f"\n--- Car {i} (id={c['id']}) ---", flush=True)
                print(f"  href: {c['href']}", flush=True)
                print(f"  text: {c['text']}", flush=True)
                print(f"  images: {c['images'][:2]}", flush=True)
                if c["data_attrs"]:
                    print(f"  data-attrs: {c['data_attrs']}", flush=True)

            # Save all
            save = os.path.join(OUT_DIR, "playwright_cars_dom.json")
            with open(save, "w", encoding="utf-8") as f:
                json.dump(cars, f, ensure_ascii=False, indent=2)
            print(f"\nSaved → {save}", flush=True)

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
