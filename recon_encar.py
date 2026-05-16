"""
recon_encar.py — STEP 1: probe ONE encar URL to figure out how the site works.

We send the listing page through Oxylabs with:
  - geo_location="South Korea"  (in case the site blocks non-KR traffic)
  - render="html"               (run headless browser, JS executes)
  - xhr=True                    (capture every background HTTP call the page makes)
  - scroll 3 times              (in case the list lazy-loads on scroll)

Then we report:
  - HTTP status and final URL (after redirects)
  - Content type and length
  - Whether __NEXT_DATA__ was found (means Next.js — same trick as dongchedi)
  - Whether any "window.__INITIAL_STATE__" was found (Vue/React SSR)
  - JSON-LD script blocks count
  - First 16 KB of HTML saved for manual inspection
  - All XHR calls the page made (URL + method + status + response size)
  - Any XHR that looks like an API → full body saved

Output goes to ./recon_artifacts/ as files we can read after the run.
Cost: ~$0.04 (one render+xhr request).

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

# The single URL we probe in this step. Picked because car.encar.com
# is the modern listing UI that real users browse — anything modern that
# encar uses for data fetching will be visible here.
TARGET_URL = "https://car.encar.com/list/car"

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
INITIAL_STATE_RE = re.compile(
    r'window\.__(?:INITIAL_STATE|NUXT|PROPS)__\s*=\s*(\{.*?\})\s*[;<]', re.DOTALL
)


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "South Korea",
        "render": "html",
        "xhr": True,
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(3)
        ],
    }

    print(f"Probing {TARGET_URL}")
    print("Payload: render=html, xhr=True, geo=South Korea, scrolls=3")
    print("Sending to Oxylabs… (takes ~30-60s for a render+xhr request)\n")

    r = requests.post(
        OXY_URL, auth=(OXY_USER, OXY_PASS),
        json=payload, timeout=300,
    )
    print(f"Oxylabs HTTP: {r.status_code}")

    if r.status_code != 200:
        print(f"ERROR body: {r.text[:500]}")
        sys.exit(1)

    data = r.json()
    results = data.get("results", []) or []
    print(f"Results returned: {len(results)}")

    main_result = next((res for res in results if res.get("type") != "xhr"), None)
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)

    # ---------- Main page result ----------
    print("\n========== MAIN PAGE ==========")
    if not main_result:
        print("WARNING: no main (non-xhr) result captured")
    else:
        print(f"Target HTTP status: {main_result.get('status_code')}")
        print(f"Final URL: {main_result.get('url')}")
        content = main_result.get("content")
        if isinstance(content, str):
            print(f"Content type: string ({len(content)} chars)")
            stripped = content.lstrip()[:1]
            looks_like = "html" if stripped == "<" else ("json" if stripped in "{[" else "other")
            print(f"Looks like: {looks_like}")

            head_ext = ".html" if looks_like == "html" else ".txt"
            head_path = os.path.join(OUT_DIR, f"main_head{head_ext}")
            with open(head_path, "w", encoding="utf-8") as f:
                f.write(content[:16000])
            print(f"First 16KB saved → {head_path}")

            if NEXT_DATA_RE.search(content):
                m = NEXT_DATA_RE.search(content)
                try:
                    nd = json.loads(m.group(1))
                    keys = list(nd.keys())
                    print(f"✅ __NEXT_DATA__ FOUND ({len(m.group(1))} chars). "
                          f"Top keys: {keys}")
                    nd_path = os.path.join(OUT_DIR, "main_next_data.json")
                    with open(nd_path, "w", encoding="utf-8") as f:
                        json.dump(nd, f, ensure_ascii=False, indent=2)
                    print(f"   Full content → {nd_path}")
                except Exception as e:
                    print(f"⚠️  __NEXT_DATA__ tag found but JSON invalid: {e}")
            else:
                print("❌ __NEXT_DATA__ NOT found (so probably not Next.js)")

            init = INITIAL_STATE_RE.search(content)
            if init:
                print(f"✅ window.__INITIAL_STATE__/__NUXT__ found "
                      f"({len(init.group(1))} chars)")
            else:
                print("❌ window.__INITIAL_STATE__ not found")

            jsonld = JSON_LD_RE.findall(content)
            print(f"JSON-LD blocks: {len(jsonld)}")
        elif isinstance(content, dict):
            print(f"Content type: dict (already JSON). Top keys: "
                  f"{list(content.keys())[:20]}")
            head_path = os.path.join(OUT_DIR, "main_head.json")
            with open(head_path, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            print(f"Saved → {head_path}")
        else:
            print(f"Content type: {type(content).__name__} — unexpected")

    # ---------- XHR captures ----------
    print("\n========== XHR CAPTURES ==========")
    if not xhr_block:
        print("WARNING: xhr=True was set but no XHR block returned by Oxylabs")
    else:
        captured = xhr_block.get("content", []) or []
        print(f"Total XHR requests captured: {len(captured)}")

        api_calls = []
        print("\nAll XHR calls (method | status | size | URL):")
        for req in captured:
            url = req.get("url", "") or ""
            print(f"  {req.get('method'):4s} | {req.get('status_code')} | "
                  f"{len(req.get('response_body') or ''):>6} | {url[:160]}")
            # API-looking ones
            if any(s in url.lower() for s in
                   ("/api", "/search", "/vehicle", "/list", "/readside", "encar.com/")):
                if req.get("response_body"):
                    api_calls.append(req)

        if api_calls:
            api_path = os.path.join(OUT_DIR, "main_xhr_api_responses.json")
            with open(api_path, "w", encoding="utf-8") as f:
                json.dump(api_calls, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Saved {len(api_calls)} API-looking responses → {api_path}")
        else:
            print("\n❌ No API-looking XHR calls captured")

    print("\n========== DONE ==========")
    print(f"Browse ./{OUT_DIR}/ for full artifacts.")
    print("Upload as workflow artifact (the workflow does this automatically).")


if __name__ == "__main__":
    main()
