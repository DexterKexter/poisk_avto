"""Test en.guazi.com login + listing access."""
import json, os, sys

EMAIL = os.environ.get("GUAZI_EMAIL", "")
PASSWORD = os.environ.get("GUAZI_PASSWORD", "")
if not EMAIL or not PASSWORD:
    sys.exit("GUAZI_EMAIL and GUAZI_PASSWORD required")

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1366, "height": 2000},
        locale="en-US",
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    page = ctx.new_page()

    # 1. Find login page
    print("=== 1. Loading en.guazi.com ===", flush=True)
    page.goto("https://en.guazi.com/", wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(3000)
    title = page.title()
    print(f"  Title: {title}", flush=True)

    # Look for sign-in link
    signin_links = page.evaluate("""() => {
        const links = [];
        document.querySelectorAll('a').forEach(a => {
            const text = (a.innerText || '').trim().toLowerCase();
            const href = a.getAttribute('href') || '';
            if (text.includes('sign') || text.includes('login') || text.includes('log in') ||
                href.includes('sign') || href.includes('login') || href.includes('auth')) {
                links.push({text: a.innerText.trim(), href});
            }
        });
        return links;
    }""")
    print(f"  Sign-in links: {signin_links}", flush=True)

    # 2. Try to navigate to login page
    login_url = None
    for link in signin_links:
        if link.get("href") and link["href"].startswith("/"):
            login_url = "https://en.guazi.com" + link["href"]
            break
        elif link.get("href") and link["href"].startswith("http"):
            login_url = link["href"]
            break

    if not login_url:
        # Try common paths
        for path in ["/sign-in", "/login", "/auth/login", "/signin"]:
            page.goto(f"https://en.guazi.com{path}", wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_timeout(2000)
            has_input = page.evaluate("() => !!document.querySelector('input[type=\"email\"], input[type=\"password\"], input[name=\"email\"]')")
            if has_input:
                login_url = f"https://en.guazi.com{path}"
                print(f"  Found login form at {login_url}", flush=True)
                break

    if login_url:
        print(f"\n=== 2. Logging in at {login_url} ===", flush=True)
        if page.url != login_url:
            page.goto(login_url, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(2000)

        # Dump form structure
        form_info = page.evaluate("""() => ({
            inputs: Array.from(document.querySelectorAll('input')).map(i => ({
                type: i.type, name: i.name, placeholder: i.placeholder,
                id: i.id, className: i.className.substring(0, 50)
            })),
            buttons: Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.innerText.trim().substring(0, 50), type: b.type
            })),
            bodySnippet: document.body?.innerText?.substring(0, 1000) || ''
        })""")
        print(f"  Inputs: {json.dumps(form_info['inputs'], indent=2)}", flush=True)
        print(f"  Buttons: {json.dumps(form_info['buttons'], indent=2)}", flush=True)

        # Try filling email + password
        email_filled = False
        for selector in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="mail"]',
                         'input[placeholder*="Email"]', 'input[type="text"]']:
            try:
                el = page.query_selector(selector)
                if el:
                    el.fill(EMAIL)
                    email_filled = True
                    print(f"  Filled email via {selector}", flush=True)
                    break
            except:
                pass

        pw_filled = False
        for selector in ['input[type="password"]', 'input[name="password"]',
                         'input[placeholder*="assword"]']:
            try:
                el = page.query_selector(selector)
                if el:
                    el.fill(PASSWORD)
                    pw_filled = True
                    print(f"  Filled password via {selector}", flush=True)
                    break
            except:
                pass

        if email_filled and pw_filled:
            # Click submit
            for selector in ['button[type="submit"]', 'button:has-text("Sign")',
                             'button:has-text("Log")', 'button:has-text("Submit")']:
                try:
                    btn = page.query_selector(selector)
                    if btn:
                        btn.click()
                        print(f"  Clicked submit via {selector}", flush=True)
                        break
                except:
                    pass

            page.wait_for_timeout(5000)
            print(f"  After login - URL: {page.url}", flush=True)
            print(f"  After login - Title: {page.title()}", flush=True)

            # Check if we got cookies
            cookies = ctx.cookies()
            auth_cookies = [c for c in cookies if 'token' in c['name'].lower()
                           or 'session' in c['name'].lower() or 'auth' in c['name'].lower()]
            print(f"  Auth-like cookies: {len(auth_cookies)}", flush=True)
            for c in auth_cookies[:3]:
                print(f"    {c['name']}={c['value'][:20]}...", flush=True)
    else:
        print("  No login page found, trying direct click on Sign in button", flush=True)
        page.goto("https://en.guazi.com/", wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(3000)
        try:
            page.click("text=Sign in", timeout=5000)
            page.wait_for_timeout(3000)
            print(f"  After click - URL: {page.url}", flush=True)
            print(f"  After click - body: {page.evaluate('() => document.body.innerText.substring(0, 800)')}", flush=True)
        except Exception as e:
            print(f"  Click failed: {e}", flush=True)

    # 3. Try listing page after login
    print(f"\n=== 3. Checking listings after auth ===", flush=True)
    page.goto("https://en.guazi.com/used-cars/bmw/", wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3000)

    result = page.evaluate("""() => ({
        title: document.title,
        imgAlts: Array.from(document.querySelectorAll('img[alt^="Used"]')).map(i => i.alt).slice(0, 5),
        detailLinks: Array.from(document.querySelectorAll('a[href*="/detail/"]')).map(a => a.href).slice(0, 5),
        bodyLen: document.body?.innerText?.length || 0,
        bodySnippet: (document.body?.innerText || '').substring(0, 1500),
    })""")
    print(f"  Title: {result['title']}", flush=True)
    print(f"  'Used' img alts: {result['imgAlts']}", flush=True)
    print(f"  Detail links: {result['detailLinks']}", flush=True)
    print(f"  Body length: {result['bodyLen']}", flush=True)
    if result['detailLinks']:
        print(f"\n  *** LISTINGS FOUND! ***", flush=True)
    else:
        print(f"\n  Body preview:\n{result['bodySnippet'][:800]}", flush=True)

    browser.close()
