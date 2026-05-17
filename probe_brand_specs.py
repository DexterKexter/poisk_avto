"""Verify model URL pattern + extract all BMW models from Nuxt payload."""
import json, sys, re
sys.stdout.reconfigure(line_buffering=True)
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")


def deref(data, v):
    if isinstance(v, int) and 0 <= v < len(data):
        return data[v]
    return v


def extract_models_for_brand(data, brand_code):
    """Find every list-of-dicts where parentId resolves to brand_code."""
    models = []
    for v in data:
        if not isinstance(v, list) or len(v) < 5:
            continue
        first = deref(data, v[0])
        if not isinstance(first, dict):
            continue
        if not all(k in first for k in ("id", "name", "parentId")):
            continue
        parent_idx = first.get("parentId")
        parent_val = deref(data, parent_idx)
        if parent_val != brand_code:
            continue
        for item_idx in v:
            item = deref(data, item_idx)
            if not isinstance(item, dict):
                continue
            models.append({
                "id": deref(data, item.get("id")),
                "name": deref(data, item.get("name")),
                "parentId": parent_val,
            })
        break
    return models


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 4000})
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()

    page.goto("https://www.autocango.com/carspecs/brandName=BMW",
              wait_until="load", timeout=60000)
    page.wait_for_timeout(2500)
    nuxt = page.evaluate("""() => document.getElementById('__NUXT_DATA__').textContent""")
    data = json.loads(nuxt)

    models = extract_models_for_brand(data, "M4L")
    print(f"BMW models extracted: {len(models)}")
    for m in models[:10]:
        print(f"  code={m['id']:<8} name={m['name']}")

    if not models:
        sys.exit(1)

    # Now try guessing the URL for first model and verify
    m = models[0]
    candidates = [
        f"https://www.autocango.com/cs/carspecs-BMW-{m['name'].replace(' ', '-')}-{m['id']}",
        f"https://www.autocango.com/cs/carspecs-{m['name'].replace(' ', '-')}-{m['id']}",
    ]
    for url in candidates:
        print(f"\n=== Try {url} ===")
        try:
            page.goto(url, wait_until="load", timeout=45000)
            page.wait_for_timeout(1500)
            print(f"  Final URL: {page.url}")
            title = page.title()
            print(f"  Title: {title[:120]}")
            txt = page.evaluate("""() => document.body.innerText.slice(0, 800)""")
            print(f"  Body head: {txt!r}")
            if "Model Year" in txt or "Engine" in txt:
                print("  ✓ HAS SPEC FIELDS")
                break
        except Exception as e:
            print(f"  goto err: {e}")

    browser.close()
