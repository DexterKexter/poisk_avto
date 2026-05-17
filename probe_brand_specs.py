"""Inspect XHR + Nuxt payload on /carspecs/brandName=BMW to find model URLs."""
import json, sys, re
sys.stdout.reconfigure(line_buffering=True)
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 4000})
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()

    # 1. Capture XHR/Fetch requests
    xhrs = []
    def on_response(resp):
        url = resp.url
        ct = resp.headers.get("content-type", "")
        if "json" in ct and ("autocango.com" in url or "/api/" in url):
            xhrs.append({"url": url, "status": resp.status, "ct": ct})
    page.on("response", on_response)

    page.goto("https://www.autocango.com/carspecs/brandName=BMW",
              wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)

    print(f"\n=== JSON XHR responses ({len(xhrs)}) ===")
    for x in xhrs[:30]:
        print(f"  [{x['status']}] {x['url'][:140]}")

    # 2. Re-fetch one JSON XHR ourselves to see body shape
    for x in xhrs:
        if "carspecs" in x["url"].lower() or "brand" in x["url"].lower():
            print(f"\n=== Fetching body of: {x['url']} ===")
            try:
                body = page.evaluate(f"""async () => {{
                    const r = await fetch({json.dumps(x['url'])}, {{credentials: 'include'}});
                    const t = await r.text();
                    return t.slice(0, 3000);
                }}""")
                print(body)
            except Exception as e:
                print(f"  fetch failed: {e}")
            break

    # 3. Dump head of __NUXT_DATA__ payload
    print("\n=== __NUXT_DATA__ head ===")
    nuxt = page.evaluate("""() => {
        const s = document.getElementById('__NUXT_DATA__');
        return s ? s.textContent : null;
    }""")
    if nuxt:
        print(f"  total size: {len(nuxt)}")
        # Find strings that look like 5-char model codes
        codes = re.findall(r'"([A-Z][A-Z0-9]{3,7})"', nuxt)
        codes_unique = list(dict.fromkeys(codes))
        print(f"  candidate codes (first 30): {codes_unique[:30]}")
        # Find slug-like strings BMW-Model-X
        slugs = re.findall(r'"(BMW[\w\-]+)"', nuxt)
        print(f"  BMW slugs (first 20): {slugs[:20]}")
        # Find URLs
        urls = re.findall(r'"(/cs/carspecs-[^"]+)"', nuxt)
        print(f"  /cs/carspecs- URLs in payload: {len(urls)}")
        for u in urls[:10]: print(f"    {u}")

    browser.close()
