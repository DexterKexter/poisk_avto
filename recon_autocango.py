"""
recon_autocango.py — probe /ucbrand to extract brand list with logos.

We want to build a normalized `brands` table. autocango's /ucbrand
page should list all brands they handle for export, each with logo,
name, and likely a count of available cars or models.
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
    print("recon_autocango: /ucbrand", flush=True)
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

        url = "https://www.autocango.com/ucbrand"
        print(f"Loading {url}…", flush=True)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2000)

        print(f"  Title: {page.title()!r}", flush=True)
        html = page.content()
        print(f"  HTML size: {len(html)}", flush=True)

        with open(os.path.join(OUT_DIR, "ucbrand.html"), "w", encoding="utf-8") as f:
            f.write(html)

        # 1. Probe for brand-card-like structure
        print("\n========== BRAND ELEMENTS ==========", flush=True)
        brands = page.evaluate(
            r"""() => {
                // Find all unique images that look like logos (alt or filename)
                const logos = [];
                const seen = new Set();
                for (const img of document.querySelectorAll('img')) {
                    const src = img.src;
                    if (!src || src.startsWith('data:')) continue;
                    if (seen.has(src)) continue;
                    seen.add(src);
                    if (!/\.(png|jpe?g|webp|svg)/i.test(src)) continue;
                    // Logo characteristics: small (<200px), alt with brand name
                    const r = img.getBoundingClientRect();
                    // include all imgs for now, classify later
                    logos.push({
                        src,
                        alt: img.alt || '',
                        title: img.title || '',
                        width: r.width|0, height: r.height|0,
                        parent_tag: img.parentElement?.tagName,
                        parent_class: img.parentElement?.className?.slice(0,80) || '',
                        // Closest link & text
                        link: img.closest('a')?.href || null,
                        link_text: img.closest('a')?.innerText?.trim().slice(0,80) || '',
                    });
                }
                return logos;
            }"""
        )
        print(f"  Total <img>: {len(brands)}", flush=True)

        # Filter to brand-logos: roughly square, smallish, in <a>
        brand_logos = [b for b in brands
                       if b["link"]
                       and 30 < b["width"] < 300
                       and 30 < b["height"] < 300
                       and abs(b["width"] - b["height"]) < 100]
        print(f"  Filtered brand-like logos: {len(brand_logos)}", flush=True)

        print("\n  First 25 candidates:", flush=True)
        for b in brand_logos[:25]:
            label = b["alt"] or b["title"] or b["link_text"]
            print(f"    {label!r:30} | {b['width']}x{b['height']} | {b['link']}", flush=True)

        # 2. Look for any structured brand list (data-brand attributes etc)
        print("\n========== STRUCTURED BRAND DATA ==========", flush=True)
        structured = page.evaluate(
            r"""() => {
                const out = [];
                // Common patterns: .brand-item, .brand-card, [data-brand]
                const sels = ['.brand-item', '.brand-card', '[data-brand]',
                              '.ucbrand-item', '[class*="brand"]'];
                const seen = new Set();
                for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        const link = el.querySelector('a') || el.closest('a');
                        const img = el.querySelector('img');
                        out.push({
                            sel,
                            tag: el.tagName,
                            class: el.className?.slice(0, 100) || '',
                            text: (el.innerText || '').trim().slice(0, 120),
                            href: link?.href || null,
                            logo: img?.src || null,
                            outer_h: el.outerHTML.length,
                        });
                        if (out.length >= 20) return out;
                    }
                    if (out.length >= 20) break;
                }
                return out;
            }"""
        )
        print(f"  Structured elements found: {len(structured)}", flush=True)
        for s in structured[:15]:
            print(f"    [{s['sel']}] {s['tag']}.{s['class']!r} text={s['text']!r}", flush=True)
            if s['href']:
                print(f"       href={s['href']}", flush=True)

        # 3. URL pattern analysis: all links from page
        print("\n========== ALL UNIQUE href patterns (brand-related) ==========", flush=True)
        hrefs = page.evaluate(
            r"""() => {
                const all = Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && (h.includes('brand') || h.includes('ucbrand')
                                       || /\/[a-z]+\/?$/i.test(h)));
                return [...new Set(all)].slice(0, 60);
            }"""
        )
        for h in hrefs:
            print(f"    {h}", flush=True)

        # Save filtered brand logos
        if brand_logos:
            save = os.path.join(OUT_DIR, "ucbrand_logos.json")
            with open(save, "w", encoding="utf-8") as f:
                json.dump(brand_logos, f, ensure_ascii=False, indent=2)
            print(f"\nSaved {len(brand_logos)} brand candidates → {save}", flush=True)

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
