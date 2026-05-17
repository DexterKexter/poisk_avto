"""
recon_autocango.py v11 — find where IDs actually live in DOM.

v10 found 0 hrefs matching /usedcar/ACU... Cards probably don't use
regular links — maybe data-* attributes, onclick handlers, or different
URL pattern. Need to investigate.

Strategy: search ENTIRE rendered DOM for the ID strings we know are
present (e.g. ACU90381487). For each match, get the surrounding element
and its parent. Tells us where IDs live structurally.
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
    print("recon_autocango v11", flush=True)
    from playwright.sync_api import sync_playwright

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
        page = ctx.new_page()

        print(f"Loading {LISTING_URL}…", flush=True)
        page.goto(LISTING_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)

        # Scroll to bottom to trigger any lazy load
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        print(f"  Title: {page.title()!r}", flush=True)
        html = page.content()
        print(f"  HTML size: {len(html)}", flush=True)

        # 1. Find ALL hrefs to understand URL patterns
        print("\n========== ALL UNIQUE hrefs (containing /usedcar or /car) ==========",
              flush=True)
        hrefs = page.evaluate(
            """() => {
                const all = Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(h => /\\/(usedcar|car|detail|listing)\\//i.test(h));
                return [...new Set(all)].slice(0, 30);
            }"""
        )
        for h in hrefs:
            print(f"  {h}", flush=True)

        # 2. Find where the known IDs live in the DOM tree
        print("\n========== Where do ACU/ACN IDs appear? ==========", flush=True)
        ids_location = page.evaluate(
            """() => {
                const out = [];
                const idPattern = /\\b[A-Z]{2,4}\\d{6,10}\\b/;
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null);
                let node;
                const seen = new Set();
                while ((node = walker.nextNode())) {
                    const m = node.textContent.match(idPattern);
                    if (m && !seen.has(m[0])) {
                        seen.add(m[0]);
                        const parent = node.parentElement;
                        out.push({
                            id: m[0],
                            parent_tag: parent.tagName,
                            parent_class: parent.className,
                            parent_html: parent.outerHTML.slice(0, 300),
                        });
                        if (out.length >= 5) break;
                    }
                }
                return out;
            }"""
        )
        if ids_location:
            for loc in ids_location:
                print(f"\n  ID {loc['id']}:", flush=True)
                print(f"    tag: {loc['parent_tag']}", flush=True)
                print(f"    class: {loc['parent_class']}", flush=True)
                print(f"    html: {loc['parent_html']}", flush=True)
        else:
            print("  No IDs found in text nodes — they may be in attributes only",
                  flush=True)

        # 3. Find IDs in attributes
        print("\n========== IDs found in element attributes ==========", flush=True)
        in_attrs = page.evaluate(
            """() => {
                const out = [];
                const idPattern = /\\b[A-Z]{2,4}\\d{6,10}\\b/;
                const seen = new Set();
                for (const el of document.querySelectorAll('*')) {
                    for (const attr of el.attributes) {
                        const m = attr.value.match(idPattern);
                        if (m && !seen.has(m[0] + attr.name)) {
                            seen.add(m[0] + attr.name);
                            out.push({
                                id: m[0],
                                tag: el.tagName,
                                attr: attr.name,
                                value: attr.value.slice(0, 200),
                                class: el.className.slice(0, 100),
                            });
                            if (out.length >= 10) return out;
                        }
                    }
                }
                return out;
            }"""
        )
        for loc in in_attrs:
            print(f"  <{loc['tag']} {loc['attr']}={loc['value']!r}> "
                  f"class={loc['class']!r}", flush=True)

        # 4. Look for repeating card-like structures
        print("\n========== Candidate car-card containers ==========", flush=True)
        cards = page.evaluate(
            """() => {
                // Find divs that contain a price ($, ¥) AND a year (20XX) AND an image
                const dollarOrYen = /\\$|¥|USD|FOB/i;
                const yearRe = /\\b(20\\d{2})\\b/;
                const candidates = [];
                for (const div of document.querySelectorAll('div, article, li, section')) {
                    const text = div.innerText || '';
                    if (text.length > 1000 || text.length < 30) continue;
                    if (!dollarOrYen.test(text)) continue;
                    if (!yearRe.test(text)) continue;
                    if (!div.querySelector('img')) continue;
                    candidates.push({
                        tag: div.tagName,
                        class: div.className.slice(0, 100),
                        text_preview: text.replace(/\\s+/g, ' ').slice(0, 200),
                        outer_h: div.outerHTML.length,
                    });
                    if (candidates.length >= 5) break;
                }
                return candidates;
            }"""
        )
        for c in cards:
            print(f"  <{c['tag']}.{c['class']!r}> {c['outer_h']}b", flush=True)
            print(f"    text: {c['text_preview']}", flush=True)

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
