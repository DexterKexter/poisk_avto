"""
recon_encar.py — STEP 7: probe the discovered API endpoint without render.

Step 6 found that fem.encar.com loads car data via XHR to
  https://api.encar.com/v1/readside/vehicles?vehicleIds=...&include=...
which returns JSON with VIN, photos, options, spec, etc.

Step 7 tries to hit this endpoint DIRECTLY through Oxylabs without
render=html. If it returns 200 with JSON → we have a $0.002 fast path
for the scrape step. If 403/blocked → we'll have to fall back to render.

We try with our known listing ID (41203231) and ask for all known includes.

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

# Includes seen in the captured XHR + a few likely extras.
INCLUDES = ("SPEC,ADVERTISEMENT,PHOTOS,CATEGORY,MANAGE,CONTACT,VIEW,"
            "OPTIONS,CONDITION,PARTNERSHIP,CONTENTS,VEHICLETYPE")

# Try the listing ID; if it 404s we'll try alternates.
TARGET_IDS = ["41203231"]

API_URL = (
    "https://api.encar.com/v1/readside/vehicles"
    f"?vehicleIds={','.join(TARGET_IDS)}"
    f"&include={INCLUDES}"
)

VIN_RE = re.compile(r'[A-HJ-NPR-Z0-9]{17}')


def probe(url: str, label: str, *, render: bool = False) -> dict:
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "South Korea",
    }
    if render:
        payload["render"] = "html"

    print(f"\n========== {label} ==========")
    print(f"URL: {url}")
    print(f"render: {render}, geo: South Korea")

    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
    if r.status_code != 200:
        print(f"OXY HTTP {r.status_code}: {r.text[:300]}")
        return {"oxy_status": r.status_code, "error": r.text[:300]}

    data = r.json()
    results = data.get("results", []) or []
    if not results:
        print("no results")
        return {"oxy_status": 200, "error": "no results"}

    res = results[0]
    target_status = res.get("status_code")
    content = res.get("content")
    print(f"Target HTTP status: {target_status}")
    print(f"Final URL: {res.get('url')}")
    print(f"Content type: {type(content).__name__}")

    summary = {"oxy_status": 200, "target_status": target_status,
               "url_final": res.get("url")}

    if isinstance(content, dict):
        # Direct JSON
        print(f"Content is JSON dict, top keys: {list(content.keys())[:15]}")
        summary["json_top_keys"] = list(content.keys())
        path = os.path.join(OUT_DIR, f"step7_{label}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        summary["saved"] = path
        return summary

    if isinstance(content, list):
        print(f"Content is JSON list of {len(content)}")
        summary["json_list_len"] = len(content)
        if content and isinstance(content[0], dict):
            print(f"  first item keys: {list(content[0].keys())[:30]}")
        path = os.path.join(OUT_DIR, f"step7_{label}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        summary["saved"] = path
        return summary

    # String content
    print(f"Length: {len(content)}")
    print(f"First 300 chars: {content[:300]!r}")

    # Maybe wrapped JSON
    try:
        j = json.loads(content)
        print("(content is JSON string — parsed)")
        if isinstance(j, list):
            print(f"  list of {len(j)}")
            if j and isinstance(j[0], dict):
                print(f"  first item keys: {list(j[0].keys())[:30]}")
        elif isinstance(j, dict):
            print(f"  dict top keys: {list(j.keys())[:15]}")
        path = os.path.join(OUT_DIR, f"step7_{label}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
        summary["saved"] = path
        summary["parsed_json"] = True

        vins = VIN_RE.findall(content)
        if vins:
            print(f"✅ VIN-pattern found: {set(vins)}")
    except Exception:
        # Not JSON — could be HTML 403 page
        path = os.path.join(OUT_DIR, f"step7_{label}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content[:16000])
        summary["saved_html"] = path

    return summary


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    print(f"Step 7: probe encar API endpoint directly.")
    print(f"Target IDs: {TARGET_IDS}")
    print(f"Includes: {INCLUDES}\n")

    # First try: no render (cheap path)
    print("\n--- A. Direct API call WITHOUT render (~$0.002) ---")
    a = probe(API_URL, "A_no_render", render=False)

    # If A succeeded with JSON we're done. Otherwise try with render as fallback.
    if a.get("target_status") == 200 and (a.get("json_top_keys")
                                          or a.get("json_list_len")
                                          or a.get("parsed_json")):
        print("\n🎯 SUCCESS without render — the API is openly accessible.")
        print("    Future scrape_encar.py can use this path for ~$0.002 per batch of 5.")
    else:
        print(f"\nA failed (status {a.get('target_status')}). "
              "Trying again WITH render as fallback…")
        b = probe(API_URL, "B_with_render", render=True)
        if b.get("target_status") == 200:
            print("\n⚠️  Works only with render=html (~$0.04 each, same as detail page).")
        else:
            print(f"\n❌ Both A and B failed. Need to investigate auth/headers.")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
