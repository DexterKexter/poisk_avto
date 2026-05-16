"""
recon_dongchedi_dates.py — find publication-date fields in dongchedi skuDetail.

We've been parsing dongchedi cards but never extracted a "published_at"
date. This recon picks one existing source_id from cars[dongchedi], fetches
its card page via Oxylabs render, drills into props.pageProps.skuDetail,
and prints every field that looks date-shaped (ISO string or unix timestamp).

After we know which key holds the publish date, we update parse_card() in
scrape_dongchedi.py to populate cars.published_at.

Env: OXY_USER, OXY_PASS, SUPABASE_URL, SUPABASE_KEY
"""

import json
import os
import re
import sys

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

CARD_URL = "https://www.dongchedi.com/usedcar/{id}"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Heuristics for "this looks like a date":
ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}')
DATE_KEY_HINTS = ("time", "date", "at", "publish", "online", "create",
                  "update", "modif", "regist", "first", "last")


def is_date_like_value(value) -> bool:
    if isinstance(value, str):
        return bool(ISO_DATE_RE.match(value)) or bool(
            re.search(r'\d{4}[-/年]\d{1,2}', value)
        )
    if isinstance(value, (int, float)):
        # Unix seconds (1e9..4e9 ≈ 2001..2096) or milliseconds (1e12..4e12).
        return (1e9 < value < 4e9) or (1e12 < value < 4e12)
    return False


def key_has_date_hint(key: str) -> bool:
    if not isinstance(key, str):
        return False
    lk = key.lower()
    return any(h in lk for h in DATE_KEY_HINTS)


def walk_for_dates(node, path="$", out=None, depth=0, max_depth=10):
    """Collect fields where EITHER the value looks like a date OR
    the key contains a date-hint word. Catches both real dates and
    suspicious-but-empty fields."""
    if out is None:
        out = []
    if depth > max_depth:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            val_match = is_date_like_value(v)
            key_match = key_has_date_hint(k)
            if val_match or key_match:
                out.append({
                    "path": f"{path}.{k}",
                    "key": k,
                    "value": v,
                    "value_is_date": val_match,
                    "key_has_hint": key_match,
                    "value_type": type(v).__name__,
                })
            walk_for_dates(v, f"{path}.{k}", out, depth + 1, max_depth)
    elif isinstance(node, list):
        for i, item in enumerate(node[:3]):
            walk_for_dates(item, f"{path}[{i}]", out, depth + 1, max_depth)
    return out


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    # Pull one source_id from cars[dongchedi]
    r = DB._pg_request(
        "GET",
        "cars?source=eq.dongchedi&select=source_id,mark,model&limit=1&order=last_seen.desc",
    )
    if r.status_code != 200 or not r.json():
        sys.exit(f"Could not get sample id from Supabase: {r.text[:200]}")
    sample = r.json()[0]
    card_id = sample["source_id"]
    print(f"Sample card: id={card_id} ({sample.get('mark')} {sample.get('model')})")

    url = CARD_URL.format(id=card_id)
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
    }
    print(f"Fetching {url}\n")
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=180)
    if r.status_code != 200:
        sys.exit(f"OXY HTTP {r.status_code}: {r.text[:300]}")

    results = r.json().get("results", []) or []
    if not results:
        sys.exit("no results")
    content = results[0].get("content", "")
    if not isinstance(content, str):
        sys.exit("content not html")

    m = NEXT_DATA_RE.search(content)
    if not m:
        sys.exit("__NEXT_DATA__ not found")
    nd = json.loads(m.group(1))

    try:
        sku = nd["props"]["pageProps"]["skuDetail"]
    except (KeyError, TypeError):
        sys.exit("skuDetail not found in __NEXT_DATA__")

    print(f"✅ skuDetail loaded: {len(sku)} top-level keys\n")

    sku_path = os.path.join(OUT_DIR, f"dongchedi_skuDetail_{card_id}.json")
    with open(sku_path, "w", encoding="utf-8") as f:
        json.dump(sku, f, ensure_ascii=False, indent=2)
    print(f"Full skuDetail → {sku_path}\n")

    # Also save the WHOLE __NEXT_DATA__ — date might live outside skuDetail.
    full_path = os.path.join(OUT_DIR, f"dongchedi_next_data_{card_id}.json")
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(nd, f, ensure_ascii=False, indent=2)
    print(f"Full __NEXT_DATA__ → {full_path}\n")

    # Inspect important_params / other_params lists explicitly
    for list_key in ("important_params", "other_params"):
        items = sku.get(list_key) or []
        print(f"========== {list_key} ({len(items)} items) ==========")
        for it in items:
            if isinstance(it, dict):
                # Most dongchedi params look like {"name": "上牌时间", "value": "2024-03"}
                name = it.get("name", "")
                value = it.get("value", "")
                print(f"  {name} = {value!r}")
            else:
                print(f"  {it}")
        print()

    # Print ALL skuDetail top-level keys for context
    print("========== skuDetail ALL TOP-LEVEL KEYS ==========")
    for k in sku.keys():
        v = sku[k]
        if isinstance(v, (str, int, float, bool)) or v is None:
            v_str = repr(v)[:80]
        elif isinstance(v, list):
            v_str = f"<list {len(v)}>"
        elif isinstance(v, dict):
            v_str = f"<dict keys={list(v.keys())[:6]}>"
        else:
            v_str = type(v).__name__
        print(f"  {k}: {v_str}")

    # Also peek at pageProps top-level (in case date lives outside skuDetail)
    pp = nd.get("props", {}).get("pageProps", {})
    print("\n========== props.pageProps TOP-LEVEL KEYS ==========")
    for k in pp.keys():
        v = pp[k]
        if isinstance(v, (str, int, float, bool)) or v is None:
            v_str = repr(v)[:80]
        elif isinstance(v, list):
            v_str = f"<list {len(v)}>"
        elif isinstance(v, dict):
            v_str = f"<dict keys={list(v.keys())[:8]}>"
        else:
            v_str = type(v).__name__
        print(f"  {k}: {v_str}")

    # Find date-shaped values OR keys with date-hint name — walk WHOLE __NEXT_DATA__
    dates = walk_for_dates(nd)
    # Sort: real dates first, then hint-only, then by path
    dates.sort(key=lambda d: (not d["value_is_date"], not d["key_has_hint"], d["path"]))

    print(f"\n========== DATE-LIKE FIELDS ({len(dates)}) ==========")
    for d in dates[:60]:
        if d["value_is_date"] and d["key_has_hint"]:
            flag = "🎯🎯"  # both — most likely the answer
        elif d["value_is_date"]:
            flag = "✅"
        elif d["key_has_hint"]:
            flag = "⚠️ "  # hint but empty/zero
        else:
            flag = "  "
        v = d["value"]
        v_str = repr(v) if isinstance(v, str) else str(v)
        print(f"{flag} {d['path']} ({d['value_type']}) = {v_str[:80]}")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
