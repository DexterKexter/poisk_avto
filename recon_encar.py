"""
recon_encar.py — STEP 5: probe ONE detail page to find VIN and other fields.

Listing has 28 fields but no VIN. Now we fetch the detail page of a known
car (Id from previous run) to see what extra fields are available there.

We try fem.encar.com/cars/detail/{Id} — the modern Next.js frontend that
the listing links to. If __NEXT_DATA__ contains car data → win.

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

# Detail page of the BMW 520i we saw earlier in the listing.
TARGET_ID = "41203231"
TARGET_URL = f"https://fem.encar.com/cars/detail/{TARGET_ID}"

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# Detail page fields we're hoping to find.
DETAIL_HINT_KEYS = {
    "vin", "vehicleno", "vehiclenumber", "carregisterno",
    "price", "mileage", "year",
    "owner", "ownerchanged", "ownerhistory",
    "accident", "accidenthistory", "damage",
    "option", "options", "addedoption",
    "manufacturer", "model", "modelgroup",
    "description", "memo", "comment",
    "inspection", "diagnosis", "report",
}


def walk(node, path="$", out=None, depth=0, max_depth=15):
    if out is None:
        out = []
    if depth > max_depth:
        return out
    if isinstance(node, dict):
        keys = {k.lower() for k in node.keys() if isinstance(k, str)}
        score = len(keys & DETAIL_HINT_KEYS)
        if score >= 3:
            out.append({
                "path": path,
                "score": score,
                "keys": list(node.keys()),
                "preview": _truncate_values(node),
            })
        for k, v in node.items():
            walk(v, f"{path}.{k}", out, depth + 1, max_depth)
    elif isinstance(node, list):
        # Only walk first item of any list (assume homogeneous).
        if node:
            walk(node[0], f"{path}[0]", out, depth + 1, max_depth)
    return out


def _truncate_values(d, max_str=100):
    """Make dict printable: short scalar values, summarized containers."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            out[k] = f"<{type(v).__name__} {len(v)}>"
        elif isinstance(v, str) and len(v) > max_str:
            out[k] = v[:max_str] + "…"
        else:
            out[k] = v
    return out


def find_vin_strings(node, path="$", out=None, depth=0, max_depth=15):
    """Find any value that looks like a VIN: 17 alphanumeric (no I, O, Q)."""
    if out is None:
        out = []
    if depth > max_depth:
        return out
    VIN_RE = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')
    if isinstance(node, str):
        if VIN_RE.match(node):
            out.append({"path": path, "value": node})
    elif isinstance(node, dict):
        for k, v in node.items():
            find_vin_strings(v, f"{path}.{k}", out, depth + 1, max_depth)
    elif isinstance(node, list):
        for i, v in enumerate(node[:5]):
            find_vin_strings(v, f"{path}[{i}]", out, depth + 1, max_depth)
    return out


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "South Korea",
        "render": "html",
    }

    print(f"Probing detail page: {TARGET_URL}")
    print("Payload: render=html, geo=South Korea (no scrolls, no xhr)\n")

    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
    if r.status_code != 200:
        sys.exit(f"OXY HTTP {r.status_code}: {r.text[:300]}")

    results = r.json().get("results", []) or []
    if not results:
        sys.exit("no results")

    main_result = results[0]
    print(f"Target HTTP status: {main_result.get('status_code')}")
    print(f"Final URL: {main_result.get('url')}\n")

    content = main_result.get("content")
    if not isinstance(content, str):
        sys.exit(f"content is {type(content).__name__}")

    print(f"HTML length: {len(content)} chars")

    head_path = os.path.join(OUT_DIR, "detail_head.html")
    with open(head_path, "w", encoding="utf-8") as f:
        f.write(content[:16000])
    print(f"First 16KB → {head_path}")

    m = NEXT_DATA_RE.search(content)
    if not m:
        print("⚠️  __NEXT_DATA__ NOT found on detail page.")
        print("First 500 chars of HTML:")
        print(content[:500])
        return

    try:
        nd = json.loads(m.group(1))
    except Exception as e:
        sys.exit(f"__NEXT_DATA__ invalid JSON: {e}")

    print(f"\n✅ __NEXT_DATA__ found ({len(m.group(1))} chars)")
    nd_path = os.path.join(OUT_DIR, "detail_next_data.json")
    with open(nd_path, "w", encoding="utf-8") as f:
        json.dump(nd, f, ensure_ascii=False, indent=2)
    print(f"   Saved → {nd_path}")

    # ---------- props.pageProps overview ----------
    pp = nd.get("props", {}).get("pageProps", {})
    print(f"\n========== props.pageProps OVERVIEW ==========")
    print(f"pageProps top keys: {list(pp.keys())}")
    for k, v in pp.items():
        if isinstance(v, dict):
            print(f"  {k}: dict, keys: {list(v.keys())[:15]}")
        elif isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
        else:
            s = str(v)
            print(f"  {k}: {type(v).__name__} = {s[:80]}")

    # ---------- VIN hunt: look for 17-char strings ----------
    print("\n========== VIN HUNT ==========")
    vins = find_vin_strings(nd)
    if vins:
        for v in vins[:5]:
            print(f"  ✅ VIN-like: {v['value']!r}  at  {v['path']}")
    else:
        print("  ❌ No 17-char VIN-pattern string found in __NEXT_DATA__")

    # ---------- Detail-shaped dicts ----------
    print("\n========== DETAIL-SHAPED DICTS ==========")
    cands = walk(nd)
    cands.sort(key=lambda x: -x["score"])
    print(f"Found {len(cands)} dicts with 3+ detail-like fields\n")
    for c in cands[:5]:
        print(f"🎯 score={c['score']}  {c['path']}")
        print(f"   keys: {c['keys'][:25]}")
        print(f"   values: {json.dumps(c['preview'], ensure_ascii=False, indent=2)[:1500]}")
        print()

    # ---------- Dump the most likely car detail ----------
    if cands:
        best = cands[0]
        print(f"\n🎯 Best candidate: {best['path']}")
        # Save the full content of that dict (not just preview)
        # Navigate to it
        path_parts = re.findall(r'\.([^.\[\]]+)|\[(\d+)\]', best["path"])
        obj = nd
        try:
            for key, idx in path_parts:
                if key:
                    obj = obj[key]
                else:
                    obj = obj[int(idx)]
            best_path = os.path.join(OUT_DIR, "detail_best_dict.json")
            with open(best_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            print(f"   Saved → {best_path}")
        except Exception as e:
            print(f"   (navigation failed: {e})")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
