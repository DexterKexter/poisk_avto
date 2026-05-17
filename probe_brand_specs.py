"""Decode Nuxt 3 payload to find model entries with brand/model/code."""
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

    page.goto("https://www.autocango.com/carspecs/brandName=BMW",
              wait_until="load", timeout=60000)
    page.wait_for_timeout(2500)

    nuxt = page.evaluate("""() => document.getElementById('__NUXT_DATA__').textContent""")
    print(f"Payload size: {len(nuxt)}")

    # Nuxt 3 payload is a flat JSON array where ints point to other indices
    data = json.loads(nuxt)
    print(f"Array length: {len(data)}")
    print(f"First 10 elements:")
    for i, v in enumerate(data[:10]):
        print(f"  [{i}] {type(v).__name__}: {repr(v)[:200]}")

    # Find indices that contain 'BMW' literally
    bmw_indices = [i for i, v in enumerate(data) if v == "BMW"]
    print(f"\nIndices where 'BMW' string lives: {bmw_indices[:5]}")

    # Find dicts that reference "BMW" via pointer
    print(f"\nDicts (keys) referencing BMW idx:")
    bmw_set = set(bmw_indices)
    seen_dicts = 0
    for i, v in enumerate(data):
        if isinstance(v, dict) and any(val in bmw_set for val in v.values() if isinstance(val, int)):
            print(f"  [{i}] keys via pointer:")
            for k_idx, val_idx in v.items():
                if isinstance(val_idx, int) and 0 <= val_idx < len(data):
                    key_name = data[k_idx] if isinstance(k_idx, str) else "?"
                    val_data = data[val_idx]
                    print(f"    {key_name} (idx {val_idx}) = {repr(val_data)[:80]}")
            seen_dicts += 1
            if seen_dicts >= 5:
                break

    # Look for arrays of dicts (likely the model list)
    print(f"\nLarge arrays (>20 items, dict-like):")
    for i, v in enumerate(data):
        if isinstance(v, list) and len(v) > 20:
            # Check if first elem is a dict (or int pointing to dict)
            first = v[0]
            if isinstance(first, int) and 0 <= first < len(data):
                target = data[first]
                if isinstance(target, dict):
                    print(f"  [{i}] list of {len(v)} dicts. First dict keys:")
                    for k_idx in list(target.keys())[:15]:
                        key_name = data[k_idx] if isinstance(k_idx, str) else k_idx
                        print(f"    {key_name}")
                    break

    # Search for 5-char codes that match URL pattern, plus their neighbor data
    print(f"\nLook at one specific model code 'BDMEE' context:")
    code_idx = None
    for i, v in enumerate(data):
        if v == "BDMEE":
            code_idx = i
            break
    if code_idx is not None:
        print(f"  Index of 'BDMEE' string: {code_idx}")
        # Find dicts that point to it
        for i, v in enumerate(data):
            if isinstance(v, dict) and code_idx in v.values():
                print(f"  Used in dict [{i}]:")
                for k_idx, val_idx in v.items():
                    if isinstance(val_idx, int) and 0 <= val_idx < len(data):
                        key_name = data[k_idx] if isinstance(k_idx, str) else "?"
                        val_data = data[val_idx]
                        print(f"    {key_name} = {repr(val_data)[:80]}")
                break

    browser.close()
