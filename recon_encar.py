"""
recon_encar.py — STEP 6: capture XHR on detail page to find the data API.

Step 5 confirmed detail page at fem.encar.com/cars/detail/{Id} returns
HTTP 200 but no __NEXT_DATA__ — it's a React app (react-helmet) that
loads data via XHR after page render.

Step 6 enables xhr=True to capture every background HTTP call the
detail page makes. We then save all api.encar.com responses to find the
endpoint that returns the full car JSON (including VIN, options, etc).

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

TARGET_ID = "41203231"
TARGET_URL = f"https://fem.encar.com/cars/detail/{TARGET_ID}"

VIN_RE = re.compile(r'[A-HJ-NPR-Z0-9]{17}')


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "South Korea",
        "render": "html",
        "xhr": True,
        # A few scrolls so any lazy-loaded sections (gallery, options,
        # accident report) trigger their fetches too.
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2} for _ in range(4)
        ],
    }

    print(f"Probing detail page WITH xhr capture: {TARGET_URL}")
    print("Payload: render=html, xhr=True, geo=South Korea, scrolls=4\n")

    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
    print(f"Oxylabs HTTP: {r.status_code}")
    if r.status_code != 200:
        sys.exit(f"OXY error body: {r.text[:300]}")

    data = r.json()
    results = data.get("results", []) or []
    print(f"Results returned: {len(results)}\n")

    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        print("⚠️  No XHR block in results — checking other result types:")
        for i, res in enumerate(results):
            print(f"  [{i}] type={res.get('type')}, status={res.get('status_code')}")
        return

    captured = xhr_block.get("content", []) or []
    print(f"Total XHR requests captured: {len(captured)}\n")

    # ---------- Print every call ----------
    api_calls = []
    print("All XHR calls (method | status | size | URL):")
    for req in captured:
        url = req.get("url", "") or ""
        method = req.get("method", "?")
        status = req.get("status_code", "?")
        size = len(req.get("response_body") or "")
        print(f"  {method:4s} | {status} | {size:>7} | {url[:200]}")
        # Skip ads / sentry / static
        ignore = ("ingest.sentry.io", "googletagmanager",
                  "RealMedia/ads", "/assets/", "/static/",
                  "/translate", "exchange-rate")
        if any(s in url for s in ignore):
            continue
        if size > 0 and ("api.encar.com" in url or "encar.com/api" in url
                          or "/cars/" in url or "/vehicles" in url):
            api_calls.append(req)

    print(f"\nFiltered to {len(api_calls)} API calls likely carrying car data")

    # ---------- For each likely API call, peek at content ----------
    for i, req in enumerate(api_calls):
        url = req.get("url", "")
        body = req.get("response_body", "")
        print(f"\n========== API CALL #{i+1} ==========")
        print(f"URL: {url}")
        print(f"Method: {req.get('method')}, status: {req.get('status_code')}, "
              f"size: {len(body)}")

        # Try to parse as JSON
        try:
            j = json.loads(body)
            if isinstance(j, dict):
                top_keys = list(j.keys())
                print(f"JSON dict, top keys ({len(top_keys)}): {top_keys[:30]}")
            elif isinstance(j, list):
                print(f"JSON list of {len(j)}")
                if j and isinstance(j[0], dict):
                    print(f"  first item keys: {list(j[0].keys())[:30]}")
        except Exception:
            print(f"Not JSON. First 200 chars: {body[:200]!r}")
            continue

        # Look for VIN in body
        vins = VIN_RE.findall(body)
        if vins:
            print(f"✅ VIN-pattern found in body: {set(vins)}")

        # Save full body to file
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', url[:80])
        out_path = os.path.join(OUT_DIR, f"api_{i+1}_{safe_name[:60]}.json")
        try:
            j = json.loads(body)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False, indent=2)
        except Exception:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(body)
        print(f"Saved → {out_path}")

    # Also save everything captured (raw)
    all_path = os.path.join(OUT_DIR, "detail_xhr_all.json")
    with open(all_path, "w", encoding="utf-8") as f:
        # Only metadata + first 2KB of each body to avoid huge file
        compact = []
        for req in captured:
            compact.append({
                "method": req.get("method"),
                "url": req.get("url"),
                "status_code": req.get("status_code"),
                "response_body_preview": (req.get("response_body") or "")[:2000],
                "response_body_full_size": len(req.get("response_body") or ""),
            })
        json.dump(compact, f, ensure_ascii=False, indent=2)
    print(f"\nAll XHR (compact) → {all_path}")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
