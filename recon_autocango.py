"""
recon_autocango.py v7 — try direct POST to /api/web/usedcar/search via Oxylabs.

v6 showed SSR HTML contains a Nuxt 3 compressed payload (pointers-by-index)
that's painful to decompress. Easier path: hit the underlying POST API
directly with the right body. Skip SSR.

We know /newcar fires POST https://www.autocango.com/api/web/newcar/search.
By symmetry /usedcar fires POST https://www.autocango.com/api/web/usedcar/search.

This script tries POST via Oxylabs with explicit method+payload, varying
both geo and the payload shape to discover what works.

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

API_URL = "https://www.autocango.com/api/web/usedcar/search"


def try_post(label: str, oxy_payload: dict) -> None:
    print(f"\n========== {label} ==========")
    print(f"  Oxylabs payload: {json.dumps(oxy_payload, ensure_ascii=False)[:400]}")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=oxy_payload, timeout=120)
    print(f"  Oxylabs HTTP: {r.status_code}")
    if r.status_code != 200:
        print(f"  Oxy body: {r.text[:300]}")
        return
    data = r.json()
    results = data.get("results", []) or []
    if not results:
        print("  no results")
        return
    target_status = results[0].get("status_code")
    content = results[0].get("content")
    print(f"  Target HTTP: {target_status}")
    if isinstance(content, str):
        print(f"  Content size: {len(content)}")
        print(f"  First 500 chars: {content[:500]}")
        try:
            j = json.loads(content)
            print(f"  ✅ JSON dict, top keys: {list(j.keys()) if isinstance(j, dict) else type(j).__name__}")
            # Save full
            save = os.path.join(OUT_DIR, f"usedcar_search_{label}.json")
            with open(save, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False, indent=2)
            print(f"  Saved → {save}")
            # Find car list
            def find_list(o, path="$", depth=0):
                if depth > 5: return None
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            return f"{path}.{k}", v
                        r = find_list(v, f"{path}.{k}", depth + 1)
                        if r: return r
                return None
            found = find_list(j)
            if found:
                path, cars = found
                print(f"  🎯 Cars at {path} ({len(cars)} items)")
                print(f"  First car keys: {list(cars[0].keys())[:30]}")
                print(f"\n  ===== FIRST CAR =====")
                print(json.dumps(cars[0], ensure_ascii=False, indent=2)[:4000])
                print(f"  ===== END =====")
        except Exception as e:
            print(f"  Not JSON: {e}")
    elif isinstance(content, dict):
        print(f"  Content is dict already, keys: {list(content.keys())}")
        print(json.dumps(content, ensure_ascii=False, indent=2)[:2000])


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    body = json.dumps({"page": 1, "pageSize": 20, "excludeSold": True})

    # Variant 1: oxylabs with method=POST + payload
    try_post("V1_method_payload", {
        "source": "universal",
        "url": API_URL,
        "geo_location": "United States",
        "method": "POST",
        "payload": body,
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.autocango.com",
            "Referer": "https://www.autocango.com/usedcar",
        },
    })

    # Variant 2: oxylabs with request_method (some sources use this)
    try_post("V2_request_method", {
        "source": "universal",
        "url": API_URL,
        "geo_location": "United States",
        "request_method": "POST",
        "request_body": body,
    })

    # Variant 3: oxylabs with body field
    try_post("V3_body_field", {
        "source": "universal",
        "url": API_URL,
        "geo_location": "United States",
        "method": "POST",
        "body": body,
    })

    # Variant 4: just GET to see what the server says
    try_post("V4_simple_get", {
        "source": "universal",
        "url": API_URL,
        "geo_location": "United States",
    })

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
