"""
recon_autocango_specs.py — explore /carspecs section.

We see /carspecs in the navigation. Likely has structured technical
specifications per make/model (engine, transmission, dimensions, fuel
economy, etc) — would be valuable for the frontend to show "compare
this used car to factory specs".

Strategy:
  1. Open /carspecs main page, list brand links
  2. Drill into one brand's spec page, see its structure
  3. Drill into one model's spec page, see what fields available
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


def probe(page, label: str, url: str, dump_inline_json: bool = False) -> str:
    """Load URL, save full HTML, return rendered text."""
    print(f"\n========== {label}: {url} ==========")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(2500)
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return ""
    title = page.title()
    html = page.content()
    print(f"  Title: {title!r}")
    print(f"  HTML size: {len(html)}")
    fname = f"specs_{label}.html"
    with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved → recon_artifacts/{fname}")

    if dump_inline_json:
        # Look for inline JSON (Nuxt 3 payload)
        m = re.search(
            r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
            html, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1))
                print(f"  ✅ inline JSON ({len(m.group(1))} chars)")
                if isinstance(obj, list):
                    print(f"     type=list, len={len(obj)}")
                elif isinstance(obj, dict):
                    print(f"     keys: {list(obj.keys())[:10]}")
                jpath = os.path.join(OUT_DIR, f"specs_{label}.json")
                with open(jpath, "w", encoding="utf-8") as f:
                    json.dump(obj, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
    return html


def main() -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox","--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width":1366,"height":4000},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        # ===== 1. /carspecs main page =====
        html = probe(page, "01_main", "https://www.autocango.com/carspecs",
                     dump_inline_json=True)

        # Look for all internal hrefs to spec-related pages
        hrefs = sorted(set(re.findall(r'href="(/carspecs[^"]*)"', html)))
        print(f"\n  /carspecs links found: {len(hrefs)}")
        for h in hrefs[:30]:
            print(f"    {h}")

        # Find brand-spec links pattern (likely /carspecs/X or /spec/X)
        brand_links = page.evaluate(
            """() => {
                const out = [];
                for (const a of document.querySelectorAll('a[href*="spec"]')) {
                    const text = a.innerText.trim().slice(0, 50);
                    const img = a.querySelector('img');
                    out.push({
                        href: a.getAttribute('href'),
                        text: text,
                        logo: img?.src || null,
                    });
                }
                // Dedupe by href
                const seen = new Set();
                return out.filter(x => {
                    if (seen.has(x.href)) return false;
                    seen.add(x.href); return true;
                });
            }""")
        print(f"\n  All 'spec' links: {len(brand_links)}")
        for b in brand_links[:30]:
            print(f"    {b['text']:30} | {b['href']}")

        # ===== 2. Drill into a brand's spec page =====
        # Pick first brand with logo + spec link
        brand_url = None
        for b in brand_links:
            if b["logo"] and "spec" in (b["href"] or "") and b["text"]:
                brand_url = b["href"]
                if not brand_url.startswith("http"):
                    brand_url = "https://www.autocango.com" + brand_url
                break
        if not brand_url:
            # fallback: try a known brand
            brand_url = "https://www.autocango.com/carspecs/BMW"

        html2 = probe(page, "02_brand", brand_url, dump_inline_json=True)

        # Look for model links inside the brand spec page
        model_links = page.evaluate(
            """() => {
                const out = [];
                for (const a of document.querySelectorAll('a[href]')) {
                    const href = a.getAttribute('href') || '';
                    if (!href.includes('spec') && !href.includes('carspecs')) continue;
                    const text = a.innerText.trim().slice(0, 60);
                    if (!text) continue;
                    out.push({href, text});
                }
                const seen = new Set();
                return out.filter(x => {
                    if (seen.has(x.href)) return false;
                    seen.add(x.href); return true;
                });
            }""")
        print(f"\n  Inside brand page — spec-links: {len(model_links)}")
        for m in model_links[:30]:
            print(f"    {m['text']:40} | {m['href']}")

        # ===== 3. Drill into one model's spec page =====
        model_url = None
        for m in model_links:
            href = m["href"]
            # Avoid going back to /carspecs root
            if (href and href != "/carspecs"
                and "/carspecs/" in href
                and href.count("/") >= 3):
                model_url = href if href.startswith("http") \
                    else "https://www.autocango.com" + href
                break
        if not model_url:
            print("\n  No model-level spec URL found; skipping drill-down")
        else:
            html3 = probe(page, "03_model", model_url, dump_inline_json=True)
            # Print first 4KB of text to see what fields are there
            text = page.evaluate(
                """() => document.body.innerText.replace(/\\s+/g,' ').slice(0, 4000)""")
            print(f"\n  Body text (first 4KB):\n  {text[:4000]}")

        browser.close()
    print("\nDONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
