"""Test en.guazi.com — dump everything about car cards on listing page."""
import json, os, sys
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 3000}, locale="en-US")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()

    print("=== Loading BMW page ===", flush=True)
    page.goto("https://en.guazi.com/used-cars/bmw/", wait_until="networkidle", timeout=45_000)
    page.wait_for_timeout(5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3000)

    # Dump ALL links on the page
    data = page.evaluate(r"""() => {
        const r = {};

        // All <a> hrefs
        const allLinks = Array.from(document.querySelectorAll('a[href]'))
            .map(a => ({href: a.getAttribute('href'), text: (a.innerText||'').substring(0,80).replace(/\n/g,' ')}))
            .filter(l => l.href && l.href.length > 5);
        // Group: product-like
        r.productLinks = allLinks.filter(l => l.href.includes('product') || l.href.includes('.html'));
        // All non-nav links
        r.otherLinks = allLinks.filter(l => !l.href.startsWith('#') && !l.href.includes('javascript'))
            .slice(0, 30);

        // All images with "Used" in alt
        r.usedImages = Array.from(document.querySelectorAll('img[alt*="Used"]')).map(img => {
            // Walk up to find nearest <a> ancestor
            let el = img;
            let parentHref = null;
            for (let i = 0; i < 10; i++) {
                el = el.parentElement;
                if (!el) break;
                if (el.tagName === 'A') {
                    parentHref = el.getAttribute('href');
                    break;
                }
                // Also check for onClick or data attributes
                if (el.getAttribute('data-href') || el.getAttribute('data-url')) {
                    parentHref = el.getAttribute('data-href') || el.getAttribute('data-url');
                    break;
                }
            }
            return {
                alt: img.alt,
                src: img.src?.substring(0, 120) || '',
                parentHref,
                parentTag: el?.tagName || 'none',
                parentClasses: el?.className?.substring(0, 100) || '',
            };
        });

        // Count various elements
        r.counts = {
            totalLinks: document.querySelectorAll('a').length,
            linksWithHref: document.querySelectorAll('a[href]').length,
            productLinks: document.querySelectorAll('a[href*="product"]').length,
            htmlLinks: document.querySelectorAll('a[href$=".html"]').length,
            detailLinks: document.querySelectorAll('a[href*="detail"]').length,
            usedImgs: document.querySelectorAll('img[alt*="Used"]').length,
            allImgs: document.querySelectorAll('img').length,
        };

        // Try to find the first product URL by clicking a car image
        const firstUsedImg = document.querySelector('img[alt*="Used"]');
        if (firstUsedImg) {
            r.firstUsedImgParentHTML = firstUsedImg.parentElement?.outerHTML?.substring(0, 500) || '';
            // Walk up further
            let ancestor = firstUsedImg;
            for (let i = 0; i < 15; i++) {
                ancestor = ancestor.parentElement;
                if (!ancestor) break;
                const a = ancestor.querySelector('a[href]');
                if (a && a.getAttribute('href')?.length > 10) {
                    r.nearestAncestorLink = a.getAttribute('href');
                    break;
                }
            }
        }

        return r;
    }""")

    print(f"\n=== Counts ===", flush=True)
    print(json.dumps(data.get('counts', {}), indent=2), flush=True)

    print(f"\n=== 'Used' images ({len(data.get('usedImages',[]))}) ===", flush=True)
    for img in data.get('usedImages', [])[:8]:
        print(f"  alt: {img['alt'][:70]}", flush=True)
        print(f"    src: {img['src']}", flush=True)
        print(f"    parentHref: {img['parentHref']}", flush=True)
        print(f"    parentTag: {img['parentTag']} classes: {img['parentClasses'][:80]}", flush=True)

    print(f"\n=== Product/HTML links ({len(data.get('productLinks',[]))}) ===", flush=True)
    for l in data.get('productLinks', [])[:10]:
        print(f"  {l['href'][:120]}  text={l['text'][:50]}", flush=True)

    print(f"\n=== First Used img parent HTML ===", flush=True)
    print(data.get('firstUsedImgParentHTML', 'none'), flush=True)

    print(f"\n=== Nearest ancestor link ===", flush=True)
    print(data.get('nearestAncestorLink', 'none'), flush=True)

    browser.close()
