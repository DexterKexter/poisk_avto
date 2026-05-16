"""
recon_yiche.py v6 — try yiche sub-domains we haven't touched yet.

car.yiche.com path is rate-limited / bot-flagged now (v5 captured 0 XHR
where v2 got 13). Try alternative entry points:

  1. app.yiche.com/qichebaojiadaquan/   — "Full car price catalog"
                                          (saw this link in v2 dump)
  2. data.yiche.com/                    — data sub-domain (guess)
  3. m.yiche.com/qichebaojiadaquan/     — mobile site (less protection)

For each: HTML + XHR capture; look for inline JSON or API endpoints.
Cost ~\$0.15.

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

TARGETS = [
    ("01_baojia_app",  "https://app.yiche.com/qichebaojiadaquan/"),
    ("02_data",        "https://data.yiche.com/"),
    ("03_baojia_m",    "https://m.yiche.com/qichebaojiadaquan/"),
    ("04_car_m",       "https://car.m.yiche.com/"),
]

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
INITIAL_STATE_RE = re.compile(
    r'window\.__(?:INITIAL_STATE|NUXT|PROPS|APP_PROPS)__\s*=\s*(\{.*?\})\s*[;<]',
    re.DOTALL,
)


def probe(name: str, url: str) -> None:
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
            for _ in range(3)
        ],
    }
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return
    results = r.json().get("results", []) or []

    # Main HTML
    main = next((res for res in results if res.get("type") != "xhr"),
                results[0] if results else None)
    if main:
        target_status = main.get("status_code")
        final_url = main.get("url")
        content = main.get("content") or ""
        print(f"  Target HTTP: {target_status}")
        print(f"  Final URL:   {final_url}")
        if isinstance(content, str):
            print(f"  HTML length: {len(content)} chars")
            # Save full content (for short pages; truncate long)
            path = os.path.join(OUT_DIR, f"yiche_v6_{name}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  Saved → {path}")
            # Look for inline JSON
            if NEXT_DATA_RE.search(content):
                m = NEXT_DATA_RE.search(content)
                try:
                    nd = json.loads(m.group(1))
                    print(f"  ✅ __NEXT_DATA__ found ({len(m.group(1))} chars)")
                    print(f"     top keys: {list(nd.keys())}")
                    pp = nd.get("props", {}).get("pageProps", {})
                    if pp:
                        print(f"     pageProps: {list(pp.keys())}")
                except Exception as e:
                    print(f"  __NEXT_DATA__ invalid: {e}")
            if INITIAL_STATE_RE.search(content):
                print(f"  ✅ inline window.* JSON found")
            # Quick scan for car-data hints
            hints = ("seriesId", "serialId", "carId", "msrp", "price",
                     "MasterId", "MasterName", "SerialName")
            found_hints = [h for h in hints if h in content]
            if found_hints:
                print(f"  Car hints in HTML: {found_hints}")

    # XHR
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if xhr_block:
        captured = xhr_block.get("content", []) or []
        print(f"\n  XHR captured: {len(captured)}")
        api_urls = []
        for req in captured:
            url2 = req.get("url", "") or ""
            if any(s in url2 for s in (
                "sentry", "google", "doubleclick", "/ads/", "/assets/",
                "/static/", "fonts.", "apm-engine", "/log?",
                "miaozhen", "tanx.com",
            )):
                continue
            size = len(req.get("response_body") or "")
            if size < 200:
                continue
            print(f"    {req.get('method')} {req.get('status_code')} "
                  f"{size:>7}b: {url2}")
            api_urls.append(req)
        if api_urls:
            save = os.path.join(OUT_DIR, f"yiche_v6_{name}_xhr.json")
            with open(save, "w", encoding="utf-8") as f:
                json.dump([{
                    "url": r.get("url"),
                    "method": r.get("method"),
                    "status": r.get("status_code"),
                    "response_body_preview": (r.get("response_body") or "")[:2000],
                } for r in api_urls], f, ensure_ascii=False, indent=2)
            print(f"  XHR saved → {save}")


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")
    for name, url in TARGETS:
        probe(name, url)
    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
