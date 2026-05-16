"""
recon_autocango.py v2 — autocango not Next.js, find where cars actually live.

v1 results:
  - HTTP 200, HTML 743KB
  - No __NEXT_DATA__
  - No real inline JSON state (matched empty placeholder)
  - 0 car-like arrays via walker

v2 strategy:
  1. Print first 16KB of HTML to stdout (see actual structure)
  2. Look for ALL inline JSON patterns:
     - <script type="application/json">
     - <script type="application/ld+json">
     - var XXX = {...}; / window.XXX = {...};
     - data-* attributes with JSON
  3. Capture XHR — maybe data loads via API after page render
  4. Find <a href> links to detail pages (ACN-prefixed IDs)

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

TARGET_URL = "https://www.autocango.com/newcar"

# Regex for various inline JSON patterns
JSON_SCRIPT_RE = re.compile(
    r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>',
    re.DOTALL,
)
VAR_JSON_RE = re.compile(
    r'(?:var|let|const|window\.)\s*(\w+)\s*=\s*(\{[^;<]{200,}\})\s*[;<]',
    re.DOTALL,
)
HREF_RE = re.compile(r'href="([^"]+)"')
ACN_ID_RE = re.compile(r'ACN\d{6,10}')

CAR_HINT_KEYS = {
    "price", "year", "model", "make", "brand", "manufacturer",
    "vin", "id", "carid", "msrp", "fob", "exw",
    "fueltype", "displacement", "horsepower",
    "image", "imageurl", "photo", "thumbnail",
    "seatcount", "transmission",
}


def walk(node, path="$", out=None, depth=0, max_depth=10):
    if out is None:
        out = []
    if depth > max_depth:
        return out
    if isinstance(node, list):
        if node and isinstance(node[0], dict):
            keys = {k.lower() for k in node[0].keys() if isinstance(k, str)}
            score = len(keys & CAR_HINT_KEYS)
            out.append({
                "path": path, "len": len(node), "score": score,
                "first_keys": list(node[0].keys())[:25],
                "sample_3": node[:3],
            })
    elif isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}.{k}", out, depth + 1, max_depth)
    return out


def fetch_with_xhr() -> dict:
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
    print(f"\nFetching {TARGET_URL} with xhr=True…")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return {}
    return r.json()


def fetch_html_only() -> str | None:
    """Get HTML body (without xhr suppression)."""
    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "China",
        "render": "html",
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(3)
        ],
    }
    print(f"\nFetching {TARGET_URL} for HTML body…")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}")
        return None
    results = r.json().get("results", []) or []
    if not results:
        return None
    content = results[0].get("content")
    return content if isinstance(content, str) else None


def analyze_html(html: str) -> None:
    print(f"\n========== HTML analysis ({len(html)} chars) ==========")

    # Save full
    full_path = os.path.join(OUT_DIR, "autocango_full.html")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Full HTML → {full_path}")

    # Print head
    print(f"\n----- First 4KB of HTML -----")
    print(html[:4000])
    print(f"----- /First 4KB -----")

    # All <script type="application/json"> blocks
    json_blocks = JSON_SCRIPT_RE.findall(html)
    print(f"\nFound {len(json_blocks)} <script type=application/(ld+)json> blocks")
    for i, block in enumerate(json_blocks[:5]):
        block_stripped = block.strip()
        if not block_stripped:
            continue
        print(f"\n  Block {i+1} ({len(block)} chars): first 200 chars:")
        print(f"  {block_stripped[:200]}")
        try:
            obj = json.loads(block_stripped)
            print(f"  ✅ Valid JSON, type: {type(obj).__name__}")
            if isinstance(obj, dict):
                print(f"     top keys: {list(obj.keys())[:10]}")
                # Walk for cars
                cars_found = walk(obj)
                if cars_found:
                    cars_found.sort(key=lambda x: (-x["score"], -x["len"]))
                    best = cars_found[0]
                    if best["score"] >= 2:
                        print(f"  🎯 Best candidate: {best['path']} ({best['len']} items)")
                        print(f"     keys: {best['first_keys']}")
                        save = os.path.join(OUT_DIR, f"autocango_jsonblock_{i+1}.json")
                        with open(save, "w", encoding="utf-8") as f:
                            json.dump(obj, f, ensure_ascii=False, indent=2)
                        print(f"     Saved → {save}")
                        if best["sample_3"]:
                            print(f"     ===== FIRST CAR =====")
                            print(json.dumps(best["sample_3"][0],
                                             ensure_ascii=False, indent=2)[:2000])
                            print(f"     ===== END =====")
        except Exception as e:
            print(f"  Not valid JSON: {e}")

    # All var/window/let/const = {...} patterns
    print(f"\nLooking for `var/window/let/const X = {{...}}` blobs…")
    vars_found = VAR_JSON_RE.findall(html)
    print(f"Found {len(vars_found)} candidate blobs")
    for var_name, blob in vars_found[:10]:
        try:
            obj = json.loads(blob)
            print(f"  {var_name}: ✅ JSON ({len(blob)} chars)")
            if isinstance(obj, dict):
                print(f"     top keys: {list(obj.keys())[:10]}")
                cars_found = walk(obj)
                if cars_found and cars_found[0]["score"] >= 2:
                    best = cars_found[0]
                    print(f"  🎯 Car array at {best['path']} ({best['len']} items)")
        except Exception:
            print(f"  {var_name}: blob found ({len(blob)} chars) but invalid JSON")

    # ACN IDs visible
    acn_ids = sorted(set(ACN_ID_RE.findall(html)))
    print(f"\nFound {len(acn_ids)} unique ACN-prefixed IDs in HTML")
    if acn_ids:
        print(f"  First 10: {acn_ids[:10]}")

    # Internal links to detail pages
    hrefs = HREF_RE.findall(html)
    detail_links = sorted({h for h in hrefs
                            if "autocango.com" in h
                            and ("/newcar/" in h or "ACN" in h)
                            and h != "/newcar"})
    print(f"\nInternal autocango links to newcar/detail: {len(detail_links)}")
    for link in detail_links[:15]:
        print(f"  {link}")


def analyze_xhr(data: dict) -> None:
    results = data.get("results", []) or []
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        print("\nNo XHR block in response")
        return
    captured = xhr_block.get("content", []) or []
    print(f"\n========== XHR ({len(captured)} captured) ==========")
    api_calls = []
    for req in captured:
        url = req.get("url", "") or ""
        if any(s in url for s in (
            "sentry", "google", "doubleclick", "/ads/", "/assets/",
            "/static/", "fonts.", "tracker", "/log?",
        )):
            continue
        size = len(req.get("response_body") or "")
        if size < 100:
            continue
        method = req.get("method") or "?"
        print(f"  {method} {req.get('status_code')} {size:>7}b: {url[:180]}")
        if "autocango" in url or "/api" in url.lower():
            api_calls.append(req)
    if api_calls:
        save = os.path.join(OUT_DIR, "autocango_xhr_api.json")
        with open(save, "w", encoding="utf-8") as f:
            json.dump([{
                "url": r.get("url"),
                "method": r.get("method"),
                "status": r.get("status_code"),
                "response_body_preview": (r.get("response_body") or "")[:3000],
            } for r in api_calls], f, ensure_ascii=False, indent=2)
        print(f"\n  Saved {len(api_calls)} API responses → {save}")


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    # Step 1: full HTML for inspection
    html = fetch_html_only()
    if html:
        analyze_html(html)

    # Step 2: xhr capture for API discovery
    data = fetch_with_xhr()
    if data:
        analyze_xhr(data)

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
