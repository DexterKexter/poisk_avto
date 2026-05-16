"""
recon_autocango.py v4 — focus on /usedcar, try US geo.

We're parsing /usedcar this time. We know from /newcar that:
  - Site is Nuxt.js (Vue)
  - API endpoint pattern: POST https://www.autocango.com/api/web/newcar/search

So /usedcar likely has: POST https://www.autocango.com/api/web/usedcar/search

v4 strategy:
  1. Open /usedcar via Oxylabs with geo=United States, xhr=True.
  2. Capture POST requests to /api/web/usedcar/* including request body.
  3. Print everything: URL, headers (if available), request body, response.

Env: OXY_USER, OXY_PASS
"""

import json
import os
import sys

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

TARGET_URL = "https://www.autocango.com/usedcar"


def probe(geo: str) -> dict:
    print(f"\n========== geo={geo} ==========")
    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": geo,
        "render": "html",
        "xhr": True,
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(5)
        ],
    }
    print(f"  POSTing oxylabs (render=html, xhr=True, scrolls=5)…")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return {}
    return r.json()


def analyze(geo: str, data: dict) -> bool:
    """Returns True if we found cars."""
    results = data.get("results", []) or []
    if not results:
        print("  no results")
        return False

    # HTML body
    main = next((res for res in results if res.get("type") != "xhr"), None)
    if main:
        print(f"  Target HTTP: {main.get('status_code')}")
        print(f"  Final URL:   {main.get('url')}")
        content = main.get("content", "")
        if isinstance(content, str):
            print(f"  HTML length: {len(content)}")
            head_path = os.path.join(OUT_DIR, f"usedcar_{geo}_head.html")
            with open(head_path, "w", encoding="utf-8") as f:
                f.write(content[:30000])
            print(f"  First 30KB saved → {head_path}")

    # XHR
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        print("  No XHR block")
        return False
    captured = xhr_block.get("content", []) or []
    print(f"  XHR captured: {len(captured)}")

    api_calls = []
    print(f"\n  Filtered API calls (autocango + size>100):")
    for req in captured:
        url = req.get("url", "") or ""
        if any(s in url for s in (
            "sentry", "google", "doubleclick", "/ads/", "/assets/",
            "/static/", "fonts.", "tracker", "/log?",
            "shareaholic", "_nuxt", "_i18n",
        )):
            continue
        size = len(req.get("response_body") or "")
        if size < 100:
            continue
        method = req.get("method")
        status = req.get("status_code")
        print(f"    {method} {status} {size:>6}b: {url[:160]}")
        if "autocango" in url and "api" in url.lower():
            api_calls.append(req)

    if not api_calls:
        return False

    print(f"\n  ===== {len(api_calls)} API responses =====")
    for i, req in enumerate(api_calls, 1):
        url = req.get("url", "")
        method = req.get("method", "?")
        request_body = req.get("request_body") or ""
        response_body = req.get("response_body") or ""

        print(f"\n  --- API {i}: {method} {url} ---")
        if request_body:
            print(f"  Request body ({len(request_body)} chars):")
            print(f"  {request_body[:1500]}")
            try:
                rb = json.loads(request_body)
                print(f"  Parsed request: {json.dumps(rb, ensure_ascii=False, indent=2)[:1000]}")
            except Exception:
                pass

        print(f"\n  Response body ({len(response_body)} chars), first 2KB:")
        print(f"  {response_body[:2000]}")

        try:
            resp = json.loads(response_body)
            if isinstance(resp, dict):
                print(f"\n  ✅ JSON dict, top keys: {list(resp.keys())}")
                # Find list of cars
                def find_list(o, path="$", depth=0):
                    if depth > 6:
                        return None
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                first_keys = str(list(v[0].keys())).lower()
                                if any(h in first_keys for h in ("price", "model", "make", "msrp", "fob")):
                                    return (f"{path}.{k}", v)
                            r = find_list(v, f"{path}.{k}", depth + 1)
                            if r: return r
                    return None
                found = find_list(resp)
                if found:
                    path, cars = found
                    print(f"  🎯 Cars at {path} ({len(cars)} items)")
                    print(f"  First car keys: {list(cars[0].keys())[:30]}")
                    print(f"\n  ===== FIRST CAR =====")
                    print(json.dumps(cars[0], ensure_ascii=False, indent=2)[:3000])
                    print(f"  ===== END =====")
        except Exception as e:
            print(f"  Not JSON: {e}")

    # Save raw
    out_path = os.path.join(OUT_DIR, f"usedcar_{geo}_xhr.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([{
            "url": r.get("url"),
            "method": r.get("method"),
            "status": r.get("status_code"),
            "request_body": r.get("request_body"),
            "response_body": r.get("response_body"),
        } for r in api_calls], f, ensure_ascii=False, indent=2)
    print(f"\n  Saved → {out_path}")
    return True


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    # Try US geo first — autocango targets foreign buyers
    for geo in ("United States", "Singapore", "China"):
        data = probe(geo)
        if data:
            found = analyze(geo, data)
            if found:
                print(f"\n🎯 SUCCESS with geo={geo}")
                break
        else:
            print("  fetch failed, trying next geo")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
