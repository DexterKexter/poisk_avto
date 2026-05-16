"""
recon_encar.py — STEP 3: dig into __NEXT_DATA__ to locate car list and fields.

Step 2 confirmed encar is Next.js SSR with __NEXT_DATA__ in HTML.
Now we drill into the JSON tree to find:
  - which path holds the array of cars (likely props.pageProps.*)
  - how many cars per page
  - what fields each car has (looking for VIN, price, year, mileage…)

Output:
  - recon_artifacts/next_data_full.json    — full __NEXT_DATA__
  - recon_artifacts/page_props_overview.txt — readable top-level structure
  - recon_artifacts/car_list_sample.json   — first 3 cars from best candidate
  - stdout: ranked list of arrays-of-objects with car-like fields

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

TARGET_URL = "https://car.encar.com/list/car"

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# Heuristic: a car-shaped dict typically has 2+ of these (case-insensitive).
CAR_HINT_KEYS = {
    "price", "year", "mileage", "model", "modelnm", "modelname",
    "manufacturer", "manufacturernm", "make",
    "vin", "carid", "id", "no", "vehicleid",
    "color", "fueltype", "fuel", "transmission",
    "image", "imagepath", "thumbnail",
}


def walk(node, path="$", out=None, depth=0, max_depth=12):
    """Recursively find arrays-of-dicts. Score by car-likeness of keys."""
    if out is None:
        out = []
    if depth > max_depth:
        return out

    if isinstance(node, list):
        if node and isinstance(node[0], dict):
            first = node[0]
            keys = {k.lower() for k in first.keys() if isinstance(k, str)}
            score = len(keys & CAR_HINT_KEYS)
            out.append({
                "path": path,
                "len": len(node),
                "score": score,
                "first_keys": list(first.keys()),
                "sample_3": node[:3],
            })
        # Don't recurse into list children (avoids noise from nested arrays).
    elif isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}.{k}", out, depth + 1, max_depth)
    return out


def describe(value, max_str=80):
    """One-line description of a value."""
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return f"list[{len(value)}] of dicts; first keys: {list(value[0].keys())[:10]}"
        return f"list[{len(value)}] of {type(value[0]).__name__ if value else '?'}"
    if isinstance(value, dict):
        return f"dict; keys: {list(value.keys())[:12]}"
    s = str(value)
    return f"{type(value).__name__} = {s[:max_str]}{'...' if len(s) > max_str else ''}"


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    payload = {
        "source": "universal",
        "url": TARGET_URL,
        "geo_location": "South Korea",
        "render": "html",
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2} for _ in range(3)
        ],
    }

    print(f"Probing {TARGET_URL}")
    print("Fetching HTML, extracting __NEXT_DATA__, finding car list…\n")

    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
    if r.status_code != 200:
        sys.exit(f"OXY HTTP {r.status_code}: {r.text[:300]}")

    results = r.json().get("results", []) or []
    if not results:
        sys.exit("no results")
    content = results[0].get("content")
    if not isinstance(content, str):
        sys.exit(f"content is {type(content).__name__}, expected string")

    print(f"Got HTML: {len(content)} chars, final URL: {results[0].get('url')}\n")

    m = NEXT_DATA_RE.search(content)
    if not m:
        sys.exit("__NEXT_DATA__ tag NOT found")
    try:
        nd = json.loads(m.group(1))
    except Exception as e:
        sys.exit(f"__NEXT_DATA__ invalid JSON: {e}")

    full_path = os.path.join(OUT_DIR, "next_data_full.json")
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(nd, f, ensure_ascii=False, indent=2)
    print(f"✅ __NEXT_DATA__ saved → {full_path} ({len(m.group(1))} chars)\n")

    # ---------- Overview of props.pageProps ----------
    page_props = nd.get("props", {}).get("pageProps", {})
    print("========== props.pageProps OVERVIEW ==========")
    print(f"pageProps top keys: {list(page_props.keys())}\n")
    overview_lines = [f"props.pageProps keys: {list(page_props.keys())}", ""]
    for k, v in page_props.items():
        line = f"  {k}: {describe(v)}"
        print(line)
        overview_lines.append(line)
    overview_path = os.path.join(OUT_DIR, "page_props_overview.txt")
    with open(overview_path, "w", encoding="utf-8") as f:
        f.write("\n".join(overview_lines))
    print(f"\nSaved → {overview_path}\n")

    # ---------- Find car-like arrays ----------
    print("========== SEARCHING FOR CAR ARRAYS ==========")
    candidates = walk(nd)
    candidates.sort(key=lambda x: (-x["score"], -x["len"]))

    print(f"Total arrays-of-dicts found: {len(candidates)}")
    print("\nTop 10 (by car-likeness score):\n")
    for c in candidates[:10]:
        flag = "🎯" if c["score"] >= 3 else ("✨" if c["score"] >= 2 else "  ")
        print(f"{flag} score={c['score']} len={c['len']:>5}  {c['path']}")
        print(f"     keys: {c['first_keys'][:15]}")
        print()

    # Save top 3 candidates' samples
    for i, c in enumerate(candidates[:3]):
        sample_path = os.path.join(OUT_DIR, f"candidate_{i+1}_sample.json")
        with open(sample_path, "w", encoding="utf-8") as f:
            json.dump({
                "path": c["path"],
                "total_items_at_path": c["len"],
                "score": c["score"],
                "first_3_items": c["sample_3"],
            }, f, ensure_ascii=False, indent=2)

    if candidates and candidates[0]["score"] >= 2:
        winner = candidates[0]
        # Save the best one's first item under a fixed name too
        first_car_path = os.path.join(OUT_DIR, "best_car_sample.json")
        with open(first_car_path, "w", encoding="utf-8") as f:
            json.dump(winner["sample_3"][0] if winner["sample_3"] else {},
                      f, ensure_ascii=False, indent=2)
        print(f"\n🎯 Most likely car list: {winner['path']}")
        print(f"   ({winner['len']} cars on this page)")
        print(f"   Sample of 1st car → {first_car_path}")

        # Also dump full first car to stdout so we don't need to open the zip.
        if winner["sample_3"]:
            first = winner["sample_3"][0]
            print("\n========== FULL FIRST CAR (all fields) ==========")
            print(f"Total fields: {len(first)}")
            print(json.dumps(first, ensure_ascii=False, indent=2))
            print("========== END FIRST CAR ==========\n")
    else:
        print("\n⚠️  No high-confidence car list found — manual inspection needed.")

    print("\n========== DONE ==========")
    print(f"All artifacts in ./{OUT_DIR}/")


if __name__ == "__main__":
    main()
