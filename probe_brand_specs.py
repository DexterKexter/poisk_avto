"""Decode Nuxt 3 payload — walk all top-level state buckets to find model list."""
import json, sys
sys.stdout.reconfigure(line_buffering=True)
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")


def deref(data, v, depth=0, maxdepth=3):
    """Resolve an int pointer one level. Limited recursion to avoid loops."""
    if isinstance(v, int) and 0 <= v < len(data) and depth < maxdepth:
        return data[v]
    return v


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
    print(f"Array length: {len(data)}")

    # Index 3 has hash keys → state objects
    print("\n=== State buckets (idx 3 hash map) ===")
    state_map = data[3]
    for hash_key, idx in state_map.items():
        state_obj = data[idx]
        print(f"  hash={hash_key[:16]}... idx={idx} type={type(state_obj).__name__}")
        if isinstance(state_obj, dict):
            for k, vi in list(state_obj.items())[:8]:
                inner = deref(data, vi)
                kind = type(inner).__name__
                size = len(inner) if hasattr(inner, '__len__') else '-'
                print(f"    {k}: idx={vi} ({kind}, size={size})")

    # Pinia store usually has the route-loaded data
    print("\n=== Index 17142 (pinia store) ===")
    if len(data) > 17142:
        pinia = data[17142]
        print(f"  type: {type(pinia).__name__}")
        if isinstance(pinia, dict):
            for k, vi in list(pinia.items())[:30]:
                inner = deref(data, vi)
                kind = type(inner).__name__
                size = len(inner) if hasattr(inner, '__len__') else '-'
                preview = repr(inner)[:60] if not isinstance(inner, (dict, list)) else ''
                print(f"    {k}: idx={vi} ({kind}, size={size}) {preview}")

    # Find ALL lists with >50 elements (likely the BMW model list of 58)
    print("\n=== Large list candidates (50-200 items) ===")
    cand = []
    for i, v in enumerate(data):
        if isinstance(v, list) and 50 <= len(v) <= 200:
            cand.append((i, len(v)))
    print(f"  found {len(cand)} candidates")
    for i, ln in cand[:10]:
        # Look at first element
        first = data[i][0] if data[i] else None
        first_deref = deref(data, first)
        kind = type(first_deref).__name__
        print(f"  [{i}] list of {ln}, first elem: {kind}")
        if isinstance(first_deref, dict):
            for k in list(first_deref.keys())[:10]:
                vi = first_deref[k]
                inner = deref(data, vi)
                print(f"      {k}: idx={vi} -> {repr(inner)[:60]}")

    browser.close()
