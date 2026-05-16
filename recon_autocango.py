"""
recon_autocango.py v3 — capture POST request bodies for /api/web/newcar/search.

v2 found the API: POST https://www.autocango.com/api/web/newcar/search.
But we only saved response. Now we need the REQUEST body to replicate.

v3:
  1. XHR capture with FULL request + response printed
  2. Pretty-print request body & response body of each POST to /api/web/newcar/*
  3. Save everything as artifact

Then if response shows cars — we know how to call the API directly.
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

TARGET_URL = "https://www.autocango.com/newcar"


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "China",
        "render": "html",
        "xhr": True,
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(4)
        ],
    }
    print(f"Fetching {TARGET_URL} with xhr=True…")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        sys.exit(f"OXY HTTP {r.status_code}: {r.text[:300]}")

    results = r.json().get("results", []) or []
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        sys.exit("No XHR block captured")

    captured = xhr_block.get("content", []) or []
    print(f"\nCaptured {len(captured)} XHR calls\n")

    # Filter to newcar/search ones
    relevant = []
    for req in captured:
        url = req.get("url", "") or ""
        if "newcar/search" in url or "autocango.com/api" in url:
            relevant.append(req)

    print(f"Relevant POSTs ({len(relevant)}):")
    for i, req in enumerate(relevant, 1):
        url = req.get("url", "")
        method = req.get("method", "?")
        status = req.get("status_code", "?")
        request_body = req.get("request_body") or ""
        response_body = req.get("response_body") or ""

        print(f"\n========== CALL {i}: {method} {url} ==========")
        print(f"Status: {status}")
        print(f"Request body ({len(request_body)} chars):")
        print(f"  {request_body[:1500]}")
        if request_body:
            try:
                rb = json.loads(request_body)
                print(f"  Parsed: {json.dumps(rb, ensure_ascii=False, indent=2)[:1500]}")
            except Exception:
                pass

        print(f"\nResponse body ({len(response_body)} chars), first 2000 chars:")
        print(f"  {response_body[:2000]}")

        try:
            resp = json.loads(response_body)
            if isinstance(resp, dict):
                print(f"\n  ✅ JSON dict, top keys: {list(resp.keys())}")
                # Look for car list
                def find_car_list(obj, depth=0):
                    if depth > 6:
                        return None
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                first = v[0]
                                if any(hint in str(first).lower() for hint in
                                       ("price", "model", "make", "brand", "msrp")):
                                    return (k, v)
                            result = find_car_list(v, depth + 1)
                            if result:
                                return result
                    return None
                found = find_car_list(resp)
                if found:
                    key, cars = found
                    print(f"  🎯 Car list at '{key}' ({len(cars)} cars)")
                    print(f"  First car keys: {list(cars[0].keys())}")
                    print(f"  ===== FIRST CAR =====")
                    print(json.dumps(cars[0], ensure_ascii=False, indent=2)[:3000])
                    print(f"  ===== END =====")
        except Exception as e:
            print(f"  Not JSON: {e}")

    # Save everything
    out_path = os.path.join(OUT_DIR, "autocango_v3_full.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([{
            "url": r.get("url"),
            "method": r.get("method"),
            "status": r.get("status_code"),
            "request_body": r.get("request_body"),
            "request_headers": r.get("request_headers"),
            "response_body": r.get("response_body"),
        } for r in relevant], f, ensure_ascii=False, indent=2)
    print(f"\nSaved → {out_path}")
    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
