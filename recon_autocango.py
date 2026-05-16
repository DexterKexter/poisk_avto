"""
recon_autocango.py — one-shot probe of autocango.com to plan a parser.

Target: https://www.autocango.com/newcar (Chinese new-car export platform).

Fires ONE Oxylabs request with render=html (no xhr — that suppresses the
HTML body). Then for the returned HTML:
  - saves first 16KB and the full __NEXT_DATA__ if present
  - looks for inline JSON blobs (window.__NUXT__, __INITIAL_STATE__)
  - walks the tree to find arrays of car-like dicts
  - prints the full first car so we can map fields without opening artifacts

If __NEXT_DATA__ is missing, fires a SECOND request with xhr=True to
catch any API calls the page makes.

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

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
INITIAL_STATE_RE = re.compile(
    r'window\.__(?:INITIAL_STATE|NUXT|PROPS|APP_PROPS)__\s*=\s*(\{.*?\})\s*[;<]',
    re.DOTALL,
)
JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)

CAR_HINT_KEYS = {
    "price", "year", "model", "make", "brand", "manufacturer",
    "vin", "id", "carid", "no",
    "fob", "exw", "msrp", "rmb", "usd",
    "displacement", "horsepower", "transmission", "fuel",
    "image", "imageurl", "photo", "thumbnail",
    "displacement", "seats",
}


def walk(node, path="$", out=None, depth=0, max_depth=12):
    """Find arrays of dicts that look like cars."""
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


def probe(url: str, *, xhr: bool, scrolls: int = 3) -> dict:
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "render": "html",
    }
    if xhr:
        payload["xhr"] = True
    payload["browser_instructions"] = [
        {"type": "scroll_to_bottom", "wait_time_s": 2}
        for _ in range(scrolls)
    ]
    print(f"\n→ POST oxylabs (xhr={xhr})")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    print(f"  oxy http {r.status_code}")
    if r.status_code != 200:
        print(f"  body: {r.text[:400]}")
        return {}
    return r.json()


def analyze_html(content: str) -> None:
    print(f"\nHTML length: {len(content)} chars")
    head_path = os.path.join(OUT_DIR, "autocango_listing_head.html")
    with open(head_path, "w", encoding="utf-8") as f:
        f.write(content[:16000])
    print(f"First 16KB → {head_path}")

    # __NEXT_DATA__
    m = NEXT_DATA_RE.search(content)
    if m:
        try:
            nd = json.loads(m.group(1))
            nd_path = os.path.join(OUT_DIR, "autocango_next_data.json")
            with open(nd_path, "w", encoding="utf-8") as f:
                json.dump(nd, f, ensure_ascii=False, indent=2)
            print(f"\n✅ __NEXT_DATA__ found ({len(m.group(1))} chars) → {nd_path}")
            print(f"   top keys: {list(nd.keys())}")
            pp = nd.get("props", {}).get("pageProps", {})
            print(f"   pageProps keys: {list(pp.keys())}")
            _drill(nd)
            return
        except Exception as e:
            print(f"⚠️  __NEXT_DATA__ JSON invalid: {e}")
    else:
        print("\n❌ __NEXT_DATA__ not found")

    # window.__INITIAL_STATE__ / Nuxt
    init = INITIAL_STATE_RE.search(content)
    if init:
        print(f"✅ window inline JSON found ({len(init.group(1))} chars)")
        try:
            iobj = json.loads(init.group(1))
            init_path = os.path.join(OUT_DIR, "autocango_initial_state.json")
            with open(init_path, "w", encoding="utf-8") as f:
                json.dump(iobj, f, ensure_ascii=False, indent=2)
            print(f"   Saved → {init_path}")
            _drill(iobj)
            return
        except Exception as e:
            print(f"   (couldn't parse as JSON: {e})")

    # JSON-LD
    jsonld = JSON_LD_RE.findall(content)
    print(f"JSON-LD blocks: {len(jsonld)}")
    if jsonld:
        for i, block in enumerate(jsonld[:3]):
            try:
                obj = json.loads(block)
                p = os.path.join(OUT_DIR, f"autocango_jsonld_{i+1}.json")
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(obj, f, ensure_ascii=False, indent=2)
                print(f"  jsonld {i+1} → {p}, type={obj.get('@type') if isinstance(obj, dict) else 'list'}")
            except Exception:
                pass


def _drill(nd) -> None:
    print("\n========== CAR-LIKE ARRAYS ==========")
    cands = walk(nd)
    cands.sort(key=lambda x: (-x["score"], -x["len"]))
    print(f"Found {len(cands)} arrays of dicts")
    for c in cands[:10]:
        flag = "🎯" if c["score"] >= 3 else ("✨" if c["score"] >= 1 else "  ")
        print(f"{flag} score={c['score']} len={c['len']:>4}  {c['path']}")
        print(f"     keys: {c['first_keys']}")

    if cands and cands[0]["score"] >= 2:
        winner = cands[0]
        first_path = os.path.join(OUT_DIR, "autocango_best_car.json")
        with open(first_path, "w", encoding="utf-8") as f:
            json.dump(winner["sample_3"][0] if winner["sample_3"] else {},
                      f, ensure_ascii=False, indent=2)
        print(f"\n🎯 Best candidate: {winner['path']} ({winner['len']} items)")
        print(f"   Sample → {first_path}")
        if winner["sample_3"]:
            print("\n========== FULL FIRST CAR ==========")
            print(f"Total fields: {len(winner['sample_3'][0])}")
            print(json.dumps(winner["sample_3"][0], ensure_ascii=False, indent=2))
            print("========== END FIRST CAR ==========")


def analyze_xhr(data: dict) -> None:
    results = data.get("results", []) or []
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        print("\nNo XHR block in fallback response")
        return
    captured = xhr_block.get("content", []) or []
    print(f"\nXHR captured: {len(captured)} calls")
    print("All XHR calls (method | status | size | URL):")
    api_calls = []
    for req in captured:
        url = req.get("url", "") or ""
        if any(s in url for s in ("sentry.io", "googletagmanager",
                                   "google-analytics", "/ads/", "/assets/",
                                   "/static/", "fonts.googleapis")):
            continue
        size = len(req.get("response_body") or "")
        print(f"  {req.get('method'):4s} | {req.get('status_code')} | "
              f"{size:>6} | {url[:180]}")
        if size > 100 and ("api" in url.lower() or "/cars" in url.lower()
                            or "/products" in url.lower()
                            or "/list" in url.lower()
                            or "autocango" in url):
            api_calls.append(req)

    if api_calls:
        out_path = os.path.join(OUT_DIR, "autocango_xhr_api.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(api_calls)} API-looking responses → {out_path}")


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    print(f"Probing autocango listing: {TARGET_URL}")

    # 1. HTML probe (no xhr — so body comes back).
    data = probe(TARGET_URL, xhr=False)
    if not data:
        sys.exit("First probe failed")
    results = data.get("results", []) or []
    if not results:
        sys.exit("No results")
    print(f"Target HTTP: {results[0].get('status_code')}")
    print(f"Final URL: {results[0].get('url')}")
    content = results[0].get("content")
    if not isinstance(content, str):
        print(f"Content is {type(content).__name__}, not HTML — printing as JSON:")
        if isinstance(content, (dict, list)):
            head_path = os.path.join(OUT_DIR, "autocango_listing_head.json")
            with open(head_path, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            print(f"Saved → {head_path}")
        return

    analyze_html(content)

    # 2. If no __NEXT_DATA__ found, also try XHR capture.
    has_next = bool(NEXT_DATA_RE.search(content))
    has_init = bool(INITIAL_STATE_RE.search(content))
    if not (has_next or has_init):
        print("\n--- Inline JSON not found; trying XHR capture as fallback ---")
        data2 = probe(TARGET_URL, xhr=True, scrolls=4)
        if data2:
            analyze_xhr(data2)

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
