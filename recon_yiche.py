"""
recon_yiche.py v3 — find car catalog API endpoints on mapi.yiche.com.

v2 showed:
  - car.yiche.com/ works (728KB HTML, 204 model links)
  - car.yiche.com/han/ → Tencent captcha (model detail pages protected)
  - mapi.yiche.com is API host
  - homepage uses /web_api/{module}_api/api/v1/{action} pattern

v3 captures XHR while opening car.yiche.com/ (the open catalog hub)
to discover the API endpoints used for car data. Then probes a few
likely API URLs directly (no render, $0.002 each) to confirm they
work without captcha.

Env: OXY_USER, OXY_PASS
"""

import json
import os
import re
import sys

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)


def probe_xhr(name: str, url: str, scrolls: int = 4) -> None:
    """Open URL via Oxylabs render+xhr; print and save all non-junk API calls."""
    print(f"\n========== {name}: {url} ==========")
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
        "xhr": True,
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(scrolls)
        ],
    }
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}")
        return
    results = r.json().get("results", []) or []
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        print("  No XHR captured")
        return

    captured = xhr_block.get("content", []) or []
    print(f"  XHR total: {len(captured)}")

    api_calls = []
    print(f"  Method | Status | Size | URL")
    for req in captured:
        url2 = req.get("url", "") or ""
        if any(s in url2 for s in (
            "sentry", "google", "doubleclick", "/ads/", "/assets/",
            "/static/", "fonts.", "tracker", "apm-engine",
            "miaozhen", "tanx.com", "/log?", "/pv?",
        )):
            continue
        size = len(req.get("response_body") or "")
        method = req.get("method") or "?"
        # Only show meaningful responses
        if size < 100 and method == "OPTIONS":
            continue
        print(f"  {method:6s} | {req.get('status_code')} | {size:>7} | {url2[:200]}")
        if size > 200 and ("yiche.com" in url2 or "/api" in url2.lower()):
            api_calls.append(req)

    if api_calls:
        out_path = os.path.join(OUT_DIR, f"yiche_v3_{name}_xhr_api.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)
        print(f"  Saved {len(api_calls)} api responses → {out_path}")


def probe_api(name: str, url: str) -> None:
    """Hit an API URL directly (no render). Quick test if it returns JSON."""
    print(f"\n========== {name}: {url} ==========")
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
    }
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=120)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return
    results = r.json().get("results", []) or []
    if not results:
        print("  no results")
        return
    status = results[0].get("status_code")
    content = results[0].get("content")
    print(f"  Target HTTP: {status}")
    if not isinstance(content, str):
        print(f"  Content: {type(content).__name__}, value: {content!r}"[:300])
        return
    print(f"  Size: {len(content)}")
    print(f"  First 500 chars: {content[:500]!r}")
    # Try to parse as JSON
    try:
        j = json.loads(content)
        if isinstance(j, dict):
            print(f"  ✅ JSON dict, top keys: {list(j.keys())}")
            # Print first chunk of formatted JSON to see structure
            print(f"  ----- JSON preview (3KB) -----")
            print(json.dumps(j, ensure_ascii=False, indent=2)[:3000])
            print(f"  ----- END preview -----")
        elif isinstance(j, list):
            print(f"  ✅ JSON list of {len(j)}")
            if j:
                print(f"  ----- first item -----")
                print(json.dumps(j[0], ensure_ascii=False, indent=2)[:2000])
        path = os.path.join(OUT_DIR, f"yiche_v3_api_{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
        print(f"  Saved → {path}")
    except Exception:
        print("  Not JSON")


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    # Step 1: XHR capture on the open catalog hub
    probe_xhr("car_hub", "https://car.yiche.com/")

    # Step 2: Hit the REAL endpoints found by step 1 directly,
    # without render. If they return JSON without browser context,
    # we have a $0.002/request path. URL-encoded param={} for empty.
    REAL_APIS = [
        ("hot_serials",
         "https://mapi.yiche.com/web_api/car_model_api/api/v1/serial/"
         "search_hot_serials?cid=508&param=%7B%7D"),
        ("hot_masters",
         "https://mapi.yiche.com/web_api/car_model_api/api/v1/master/"
         "search_hot_masters?cid=508&param=%7B%22type%22%3A2%7D"),
        ("area_list",
         "https://mapi.yiche.com/web_app/api/v1/city/get_area_list"
         "?cid=508&param=%7B%7D"),
    ]
    for name, url in REAL_APIS:
        probe_api(name, url)

    print("\n========== DONE ==========")
    print("If XHR on car_hub showed an API URL — that's our target.")
    print("Any guess that returns JSON dict can be paginated/parameterized.")


if __name__ == "__main__":
    main()
