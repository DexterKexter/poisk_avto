"""Inspect HTML around BMW model cards to find URL/code."""
import json, sys
sys.stdout.reconfigure(line_buffering=True)
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
        args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, viewport={"width":1366,"height":4000})
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()
    page.goto("https://www.autocango.com/carspecs/brandName=BMW",
              wait_until="load", timeout=60000)
    page.wait_for_timeout(3000)

    # 1. Inspect element around "BMW X3" text
    print("\n=== Outer HTML around 'BMW X3' ===")
    snippet = page.evaluate("""() => {
        for (const el of document.querySelectorAll('*')) {
            const t = (el.innerText || '').trim();
            if (t.startsWith('BMW X3') && t.includes('Check') && t.length < 200) {
                return el.outerHTML.slice(0, 2000);
            }
        }
        return 'not found';
    }""")
    print(snippet)

    # 2. Any data-* attributes on model cards
    print("\n=== Data attributes ===")
    attrs = page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        for (const el of document.querySelectorAll('*')) {
            for (const a of el.attributes) {
                if (a.name.startsWith('data-') && !seen.has(a.name)) {
                    seen.add(a.name);
                    out.push({name: a.name, sample: a.value.slice(0, 80)});
                }
            }
        }
        return out.slice(0, 20);
    }""")
    for a in attrs: print(f"  {a['name']:30} = {a['sample']}")

    # 3. Look for ALL hrefs on the page
    print("\n=== ALL unique hrefs (first 40) ===")
    hrefs = page.evaluate("""() => {
        const seen = new Set();
        for (const a of document.querySelectorAll('a[href]')) {
            seen.add(a.getAttribute('href'));
        }
        return [...seen].slice(0, 40);
    }""")
    for h in hrefs: print(f"  {h}")

    # 4. Look for Nuxt 3 JSON script
    print("\n=== Inline JSON scripts ===")
    scripts = page.evaluate("""() => {
        const out = [];
        for (const s of document.querySelectorAll('script')) {
            const type = s.getAttribute('type') || '';
            const size = (s.textContent || '').length;
            if (type === 'application/json' && size > 1000) {
                out.push({id: s.id, type: type, size: size});
            }
        }
        return out;
    }""")
    for s in scripts: print(f"  id={s['id']!r} size={s['size']}")

    # 5. Try clicking "Check 55 Models" button and see URL change
    print("\n=== Click BMW X3 model card to see URL change ===")
    try:
        page.click("text=BMW X3", timeout=5000)
        page.wait_for_timeout(2000)
        print(f"  Final URL after click: {page.url}")
    except Exception as e:
        print(f"  click failed: {e}")

    browser.close()
