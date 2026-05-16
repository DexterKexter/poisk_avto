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
import traceback

# Force unbuffered stdout so prints appear immediately in CI logs
sys.stdout.reconfigure(line_buffering=True)

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

API_URL = "https://www.autocango.com/api/web/usedcar/search"


def try_post(label: str, oxy_payload: dict) -> None:
    print(f"\n========== {label} ==========", flush=True)
    print(f"  Oxylabs payload: {json.dumps(oxy_payload, ensure_ascii=False)[:400]}", flush=True)
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                          json=oxy_payload, timeout=120)
    except Exception as e:
        print(f"  EXCEPTION during POST: {e}", flush=True)
        traceback.print_exc()
        return
    print(f"  Oxylabs HTTP: {r.status_code}", flush=True)
    if r.status_code != 200:
        print(f"  Oxy body: {r.text[:300]}", flush=True)
        return
    try:
        data = r.json()
    except Exception as e:
        print(f"  oxy response not JSON: {e}, body: {r.text[:300]}", flush=True)
        return
    results = data.get("results", []) or []
    if not results:
        print("  no results", flush=True)
        return
    target_status = results[0].get("status_code")
    content = results[0].get("content")
    print(f"  Target HTTP: {target_status}", flush=True)
    if isinstance(content, str):
        print(f"  Content size: {len(content)}", flush=True)
        print(f"  First 500 chars: {content[:500]}", flush=True)
        try:
            j = json.loads(content)
            print(f"  ✅ JSON {type(j).__name__}, top: "
                  f"{list(j.keys())[:15] if isinstance(j, dict) else len(j)}",
                  flush=True)
            save = os.path.join(OUT_DIR, f"usedcar_search_{label}.json")
            with open(save, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False, indent=2)
            print(f"  Saved → {save}", flush=True)

            def find_list(o, path="$", depth=0):
                if depth > 5:
                    return None
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            return f"{path}.{k}", v
                        r2 = find_list(v, f"{path}.{k}", depth + 1)
                        if r2:
                            return r2
                return None

            found = find_list(j)
            if found:
                path, cars = found
                print(f"  🎯 Cars at {path} ({len(cars)} items)", flush=True)
                print(f"  First car keys: {list(cars[0].keys())[:30]}", flush=True)
                print(f"\n  ===== FIRST CAR =====", flush=True)
                print(json.dumps(cars[0], ensure_ascii=False, indent=2)[:4000],
                      flush=True)
                print(f"  ===== END =====", flush=True)
        except Exception as e:
            print(f"  Not JSON: {e}", flush=True)
    elif isinstance(content, dict):
        print(f"  Content is dict, keys: {list(content.keys())[:15]}", flush=True)
        print(json.dumps(content, ensure_ascii=False, indent=2)[:2000], flush=True)
    else:
        print(f"  Content type: {type(content).__name__}", flush=True)


def main() -> None:
    print("Starting recon_autocango v7…", flush=True)
    if not OXY_USER or not OXY_PASS:
        print("ERROR: OXY_USER / OXY_PASS not set", flush=True)
        sys.exit(1)
    print(f"OXY creds present: USER len={len(OXY_USER)}, PASS len={len(OXY_PASS)}",
          flush=True)

    body = json.dumps({"page": 1, "pageSize": 20, "excludeSold": True})

    for label, payload in [
        ("V1_method_payload", {
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
        }),
        ("V2_request_method", {
            "source": "universal",
            "url": API_URL,
            "geo_location": "United States",
            "request_method": "POST",
            "request_body": body,
        }),
        ("V3_body_field", {
            "source": "universal",
            "url": API_URL,
            "geo_location": "United States",
            "method": "POST",
            "body": body,
        }),
        ("V4_simple_get", {
            "source": "universal",
            "url": API_URL,
            "geo_location": "United States",
        }),
    ]:
        try:
            try_post(label, payload)
        except Exception as e:
            print(f"  TOP-LEVEL EXCEPTION in {label}: {e}", flush=True)
            traceback.print_exc()

    print("\n========== DONE ==========", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("FATAL exception in main:", flush=True)
        traceback.print_exc()
        sys.exit(1)
