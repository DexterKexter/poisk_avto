"""Quick probe: what does /carspecs/brandName=BMW actually render?"""
import sys
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

    for url in ["https://www.autocango.com/carspecs/brandName=BMW",
                "https://www.autocango.com/carspecs?brand=BMW",
                "https://www.autocango.com/carspecs"]:
        print(f"\n========== {url} ==========", flush=True)
        try:
            page.goto(url, wait_until="load", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as e:
            print(f"  goto: {e}", flush=True)
            continue
        print(f"  Title: {page.title()!r}")
        print(f"  Final URL: {page.url}")
        # Body text first 3KB
        text = page.evaluate("() => document.body.innerText.replace(/\\s+/g,' ').slice(0,3000)")
        print(f"  Body text: {text[:3000]}")
        # All /cs/carspecs links
        links = page.evaluate("""() => {
            const out = [];
            for (const a of document.querySelectorAll('a[href*="/cs/carspecs-"]')) {
                out.push({text: a.innerText.trim().slice(0,80), href: a.getAttribute('href')});
            }
            return out.slice(0, 15);
        }""")
        print(f"  /cs/carspecs links: {len(links)}")
        for l in links[:15]: print(f"    {l['text']:60} | {l['href']}")
    browser.close()
