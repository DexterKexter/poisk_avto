"""
recon_autocango.py v5 — autocango is Nuxt SSR, data is INLINE in HTML.

v4: XHR fired 4 calls but all were Nuxt/i18n bootstraps. No /api/web call
on first page load. Conclusion: Nuxt server-side rendered the cars
straight into HTML — no API call needed for first-page data.

v5:
  1. Fetch /usedcar/excludeSold=true HTML
  2. Search for Nuxt inline data:
       - <script id="__NUXT_DATA__">...
       - window.__NUXT__ = {...}
       - window.__INITIAL_STATE__ = {...}
       - data-state="..." on root element
  3. If found, walk tree to find car list and dump first car.
  4. Also dump first 6KB of HTML so we can spot the structure visually.
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

TARGET_URL = "https://www.autocango.com/usedcar/excludeSold=true"

# Various Nuxt / inline data patterns
NUXT_DATA_RE = re.compile(
    r'<script\s+id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
WINDOW_NUXT_RE = re.compile(
    r'window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*</script>', re.DOTALL
)
INITIAL_STATE_RE = re.compile(
    r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>', re.DOTALL
)
ANY_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]*type="application/json"[^>]*(?:id="([^"]+)")?[^>]*>(.*?)</script>',
    re.DOTALL,
)

CAR_HINT_KEYS = {
    "price", "year", "model", "make", "brand", "manufacturer",
    "vin", "id", "carid", "msrp", "fob", "exw", "fca",
    "fueltype", "displacement", "horsepower", "mileage",
    "image", "imageurl", "photo", "thumbnail",
    "transmission", "energytype", "saleinfo", "configinfo",
}


def walk(node, path="$", out=None, depth=0, max_depth=15):
    if out is None:
        out = []
    if depth > max_depth:
        return out
    if isinstance(node, list):
        if node and isinstance(node[0], dict):
            keys = {str(k).lower() for k in node[0].keys()}
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


def report_cars(label: str, obj) -> bool:
    """Look for car-shaped list in `obj` and print first car. Returns True if found."""
    cands = walk(obj)
    cands.sort(key=lambda x: (-x["score"], -x["len"]))
    print(f"\n  {label}: {len(cands)} array(s) of dicts, top 5:")
    for c in cands[:5]:
        flag = "🎯" if c["score"] >= 3 else ("✨" if c["score"] >= 1 else "  ")
        print(f"  {flag} score={c['score']} len={c['len']:>4} {c['path']}")
        print(f"        keys: {c['first_keys'][:15]}")

    if cands and cands[0]["score"] >= 2:
        best = cands[0]
        print(f"\n  🎯 Best: {best['path']} ({best['len']} items)")
        if best["sample_3"]:
            sample = best["sample_3"][0]
            print(f"\n  ===== FIRST CAR =====")
            print(json.dumps(sample, ensure_ascii=False, indent=2)[:4000])
            print(f"  ===== END =====")
        save = os.path.join(OUT_DIR, "autocango_v5_best.json")
        with open(save, "w", encoding="utf-8") as f:
            json.dump({"path": best["path"], "cars": best["sample_3"]},
                      f, ensure_ascii=False, indent=2)
        print(f"  Saved → {save}")
        return True
    return False


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "United States",
        "render": "html",
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(3)
        ],
    }
    print(f"Fetching {TARGET_URL}…")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        sys.exit(f"OXY HTTP {r.status_code}: {r.text[:300]}")
    results = r.json().get("results", []) or []
    if not results:
        sys.exit("no results")
    content = results[0].get("content")
    if not isinstance(content, str):
        sys.exit(f"content not string: {type(content).__name__}")

    print(f"HTML length: {len(content)}")
    print(f"Target HTTP: {results[0].get('status_code')}")
    print(f"Final URL:   {results[0].get('url')}")

    full_path = os.path.join(OUT_DIR, "autocango_v5_full.html")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Full HTML → {full_path}")

    # Print first 6KB so we see the page structure
    print(f"\n========== First 6KB HTML ==========")
    print(content[:6000])
    print(f"========== /First 6KB ==========")

    # 1. <script id="__NUXT_DATA__">
    m = NUXT_DATA_RE.search(content)
    if m:
        try:
            nd = json.loads(m.group(1))
            print(f"\n✅ <script id=__NUXT_DATA__> found ({len(m.group(1))} chars)")
            print(f"   Top-level type: {type(nd).__name__}")
            if isinstance(nd, list):
                print(f"   List of {len(nd)} items")
            elif isinstance(nd, dict):
                print(f"   Keys: {list(nd.keys())[:10]}")
            with open(os.path.join(OUT_DIR, "autocango_nuxt_data.json"), "w", encoding="utf-8") as f:
                json.dump(nd, f, ensure_ascii=False, indent=2)
            if report_cars("Cars in __NUXT_DATA__", nd):
                return
        except Exception as e:
            print(f"⚠️  __NUXT_DATA__ tag found but parse failed: {e}")

    # 2. window.__NUXT__ = {...}
    m = WINDOW_NUXT_RE.search(content)
    if m:
        try:
            nd = json.loads(m.group(1))
            print(f"\n✅ window.__NUXT__ found ({len(m.group(1))} chars)")
            with open(os.path.join(OUT_DIR, "autocango_window_nuxt.json"), "w", encoding="utf-8") as f:
                json.dump(nd, f, ensure_ascii=False, indent=2)
            if report_cars("Cars in window.__NUXT__", nd):
                return
        except Exception as e:
            print(f"⚠️  window.__NUXT__ parse failed: {e}")

    # 3. window.__INITIAL_STATE__
    m = INITIAL_STATE_RE.search(content)
    if m:
        try:
            nd = json.loads(m.group(1))
            print(f"\n✅ window.__INITIAL_STATE__ found ({len(m.group(1))} chars)")
            if report_cars("Cars in __INITIAL_STATE__", nd):
                return
        except Exception:
            pass

    # 4. ANY <script type="application/json"> — Nuxt 3 payload
    found_any = False
    for i, (script_id, body) in enumerate(ANY_JSON_SCRIPT_RE.findall(content)):
        body = body.strip()
        if len(body) < 200:
            continue
        try:
            obj = json.loads(body)
        except Exception:
            continue
        found_any = True
        print(f"\n✅ <script type=application/json id={script_id!r}> "
              f"({len(body)} chars)")
        print(f"   Top-level type: {type(obj).__name__}")
        if isinstance(obj, list):
            print(f"   List length: {len(obj)}")
            print(f"   Types of first 30 items:")
            for j, item in enumerate(obj[:30]):
                t = type(item).__name__
                preview = (str(item)[:60] + "…") if len(str(item)) > 60 else str(item)
                print(f"     [{j}] {t}: {preview}")
        elif isinstance(obj, dict):
            print(f"   Top keys: {list(obj.keys())[:15]}")

        # Search for any of the ACU/ACN IDs we saw in HTML within this JSON
        id_matches = re.findall(r'\b[A-Z]{2,4}\d{6,10}\b', content)
        unique_ids = sorted(set(id_matches))[:3]  # take first 3
        print(f"\n   Looking up first 3 IDs in JSON body…")
        for cid in unique_ids:
            idx = body.find(cid)
            if idx >= 0:
                # Print 800 chars surrounding the ID
                start = max(0, idx - 300)
                end = min(len(body), idx + 500)
                snippet = body[start:end]
                print(f"\n   ✅ Found '{cid}' at position {idx}, context:")
                print(f"   ...{snippet}...")
                print()

        # Dump entire parsed JSON to artifact for offline inspection
        out_path = os.path.join(OUT_DIR, f"autocango_v5_script_{i}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"   Saved → {out_path}")

        if report_cars(f"Cars in script_{i}", obj):
            return

    if not found_any:
        print("\n❌ No inline JSON found")

    # 5. Last resort: regex-scan HTML for car IDs (ACN/ACU-prefix etc)
    id_matches = re.findall(r'\b[A-Z]{2,4}\d{6,10}\b', content)
    print(f"\n  ID-like tokens in HTML: {len(set(id_matches))} unique")
    if id_matches:
        print(f"  First 10: {sorted(set(id_matches))[:10]}")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
