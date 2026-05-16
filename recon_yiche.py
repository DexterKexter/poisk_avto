"""
recon_yiche.py — probe yiche.com structure to plan a parser.

Yiche (易车) is the #2 Chinese auto portal — new cars, used cars, prices,
dealer info. Direct fetch returns 403 from non-Chinese IPs, so we go
through Oxylabs with geo_location="China".

Probes 3 URLs to understand the site:
  1. https://www.yiche.com/                 — homepage (detect stack)
  2. https://car.yiche.com/                 — new-car catalog hub
  3. https://www.yiche.com/newcar/          — alternative new-car path

For each: render=html, save first 16KB, look for __NEXT_DATA__ /
window.__INITIAL_STATE__ / __NUXT__ / JSON-LD. If found — walk for
car-like arrays. If not — re-try with xhr=True to catch API calls.

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
    ("01_homepage",  "https://www.yiche.com/"),
    ("02_car_hub",   "https://car.yiche.com/"),
    ("03_newcar",    "https://www.yiche.com/newcar/"),
]

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

# Heuristic keys for "this looks like a car"
CAR_HINT_KEYS = {
    "price", "msrp", "rmb", "wan", "year", "model", "brand", "make",
    "manufacturer", "carid", "carName", "carname", "seriesid",
    "displacement", "horsepower", "fuel", "fueltype", "transmission",
    "image", "imageurl", "photo", "thumbnail",
}


def walk(node, path="$", out=None, depth=0, max_depth=12):
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


def fetch(url: str, *, xhr: bool, scrolls: int = 3) -> dict:
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
    }
    if xhr:
        payload["xhr"] = True
    payload["browser_instructions"] = [
        {"type": "scroll_to_bottom", "wait_time_s": 2}
        for _ in range(scrolls)
    ]
    print(f"  POST oxylabs (xhr={xhr})")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    print(f"  oxy http {r.status_code}")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return {}
    return r.json()


def analyze_html(name: str, content: str) -> bool:
    """Return True if found useful inline JSON, False otherwise."""
    print(f"\nHTML length: {len(content)} chars")
    head_path = os.path.join(OUT_DIR, f"yiche_{name}_head.html")
    with open(head_path, "w", encoding="utf-8") as f:
        f.write(content[:16000])
    print(f"First 16KB → {head_path}")

    # 1. __NEXT_DATA__
    m = NEXT_DATA_RE.search(content)
    if m:
        try:
            nd = json.loads(m.group(1))
            nd_path = os.path.join(OUT_DIR, f"yiche_{name}_next_data.json")
            with open(nd_path, "w", encoding="utf-8") as f:
                json.dump(nd, f, ensure_ascii=False, indent=2)
            print(f"✅ __NEXT_DATA__ found ({len(m.group(1))} chars) → {nd_path}")
            print(f"   top keys: {list(nd.keys())}")
            _drill(name, nd)
            return True
        except Exception as e:
            print(f"⚠️  __NEXT_DATA__ invalid: {e}")

    # 2. window.__INITIAL_STATE__ / __NUXT__
    init = INITIAL_STATE_RE.search(content)
    if init:
        try:
            iobj = json.loads(init.group(1))
            init_path = os.path.join(OUT_DIR, f"yiche_{name}_initial_state.json")
            with open(init_path, "w", encoding="utf-8") as f:
                json.dump(iobj, f, ensure_ascii=False, indent=2)
            print(f"✅ window.__INITIAL_STATE__/__NUXT__ found "
                  f"({len(init.group(1))} chars) → {init_path}")
            _drill(name, iobj)
            return True
        except Exception as e:
            print(f"⚠️  inline JSON invalid: {e}")

    # 3. JSON-LD
    jsonld = JSON_LD_RE.findall(content)
    print(f"JSON-LD blocks: {len(jsonld)}")
    if jsonld:
        for i, block in enumerate(jsonld[:2]):
            try:
                obj = json.loads(block)
                p = os.path.join(OUT_DIR, f"yiche_{name}_jsonld_{i+1}.json")
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(obj, f, ensure_ascii=False, indent=2)
                if isinstance(obj, dict):
                    print(f"  jsonld {i+1}: @type={obj.get('@type')!r}")
            except Exception:
                pass

    print("❌ No inline JSON tree found")
    return False


def _drill(name: str, root) -> None:
    cands = walk(root)
    cands.sort(key=lambda x: (-x["score"], -x["len"]))
    print(f"\n  Car-like arrays found: {len(cands)}")
    for c in cands[:6]:
        flag = "🎯" if c["score"] >= 3 else ("✨" if c["score"] >= 1 else "  ")
        print(f"  {flag} score={c['score']} len={c['len']:>4} {c['path']}")
        print(f"        keys: {c['first_keys'][:15]}")
    if cands and cands[0]["score"] >= 2:
        winner = cands[0]
        sample_path = os.path.join(OUT_DIR, f"yiche_{name}_best_car.json")
        with open(sample_path, "w", encoding="utf-8") as f:
            json.dump(winner["sample_3"][0] if winner["sample_3"] else {},
                      f, ensure_ascii=False, indent=2)
        print(f"  🎯 Best → {sample_path}")
        print(f"\n  ===== FIRST CAR =====")
        print(json.dumps(winner["sample_3"][0] if winner["sample_3"] else {},
                         ensure_ascii=False, indent=2)[:3000])
        print(f"  ===== END =====")


def analyze_xhr(name: str, data: dict) -> None:
    results = data.get("results", []) or []
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        print("  No XHR block returned")
        return
    captured = xhr_block.get("content", []) or []
    print(f"  XHR captured: {len(captured)} calls")
    api_calls = []
    print("  Method | Status | Size | URL")
    for req in captured:
        url = req.get("url", "") or ""
        if any(s in url for s in ("sentry.io", "googletagmanager",
                                   "google-analytics", "/ads/", "/assets/",
                                   "/static/", "fonts.", "doubleclick",
                                   "tracker", "/pv?", "/log?",
                                   "miaozhen", "tanx.com")):
            continue
        size = len(req.get("response_body") or "")
        print(f"  {req.get('method'):4s} | {req.get('status_code')} | "
              f"{size:>6} | {url[:180]}")
        if size > 200 and ("yiche.com" in url or "/api" in url.lower()):
            api_calls.append(req)
    if api_calls:
        out_path = os.path.join(OUT_DIR, f"yiche_{name}_xhr_api.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)
        print(f"  Saved {len(api_calls)} api-looking responses → {out_path}")


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    for name, url in TARGETS:
        print(f"\n========== {name}: {url} ==========")
        data = fetch(url, xhr=False)
        if not data:
            print("FAILED")
            continue
        results = data.get("results", []) or []
        if not results:
            print("No results")
            continue
        target_status = results[0].get("status_code")
        final_url = results[0].get("url")
        print(f"Target HTTP: {target_status}")
        print(f"Final URL: {final_url}")
        content = results[0].get("content")
        if not isinstance(content, str):
            print(f"Content is {type(content).__name__}, skip")
            continue

        found_json = analyze_html(name, content)

        if not found_json:
            print("\n--- Re-probing with xhr=True to catch API calls ---")
            data2 = fetch(url, xhr=True, scrolls=4)
            if data2:
                analyze_xhr(name, data2)

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
