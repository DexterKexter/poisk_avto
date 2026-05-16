"""
recon_encar.py — pagination probe: try 3 variants to get "page 2" of cars.

Current collect_encar.py uses car.encar.com/list/car?page=N which returns
250 cars only for page 1. Pages 2-5 return 0. So the page param doesn't
actually paginate.

This script tries three alternatives:
  A. Same Next.js URL but inject "from":200 into the search dict.
  B. Same Next.js URL with explicit ?from=200 query param.
  C. Direct call to api.encar.com/search/car/list/general — the underlying
     search API the Next.js page uses internally. Sort/offset/limit go via
     the `sr` parameter: %7CMobileModifiedDate%7Coffset%7Climit.

Whichever returns DIFFERENT car IDs from page-1 wins → we update
collect_encar.py to use that strategy.

Env: OXY_USER, OXY_PASS
"""

import json
import os
import re
import sys
import urllib.parse

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"
OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def build_listing_url_a(from_offset: int) -> str:
    """Variant A: inject 'from' into the search dict."""
    search = {
        "type": "car",
        "action": "(And.Hidden.N._.CarType.A.)",
        "toggle": {},
        "layer": "",
        "sort": "MobileModifiedDate",
        "from": from_offset,
    }
    qs = urllib.parse.urlencode({"search": json.dumps(search, separators=(",", ":"))})
    return f"https://car.encar.com/list/car?{qs}"


def build_listing_url_b(from_offset: int) -> str:
    """Variant B: explicit ?from=N query param outside search."""
    search = {
        "type": "car",
        "action": "(And.Hidden.N._.CarType.A.)",
        "toggle": {},
        "layer": "",
        "sort": "MobileModifiedDate",
    }
    qs = urllib.parse.urlencode({
        "from": from_offset,
        "search": json.dumps(search, separators=(",", ":")),
    })
    return f"https://car.encar.com/list/car?{qs}"


def build_api_url(offset: int, limit: int = 20) -> str:
    """Variant C: direct search API."""
    q = "(And.Hidden.N._.CarType.A.)"
    sr = f"|MobileModifiedDate|{offset}|{limit}"
    qs = urllib.parse.urlencode({
        "count": "true",
        "q": q,
        "sr": sr,
    })
    return f"https://api.encar.com/search/car/list/general?{qs}"


def probe(url: str, *, render: bool) -> tuple[int, str, str]:
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "South Korea",
    }
    if render:
        payload["render"] = "html"
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        return (r.status_code, "", r.text[:200])
    results = r.json().get("results", []) or []
    if not results:
        return (200, "", "no results")
    target_status = results[0].get("status_code", 0)
    content = results[0].get("content", "")
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False)
    elif not isinstance(content, str):
        content = str(content)
    return (target_status, content, "")


def extract_ids_from_html(html: str) -> list[str]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        nd = json.loads(m.group(1))
    except Exception:
        return []
    queries = ((nd.get("props", {}).get("pageProps", {})
                   .get("initialState", {}).get("ryvussApi", {})).get("queries") or {})
    ids: list[str] = []
    for q_val in queries.values():
        if not isinstance(q_val, dict):
            continue
        results = (q_val.get("data") or {}).get("SearchResults") or []
        for car in results:
            cid = str(car.get("Id") or "")
            if cid:
                ids.append(cid)
    return ids


def extract_ids_from_api(body: str) -> list[str]:
    """API returns JSON with SearchResults list."""
    try:
        obj = json.loads(body)
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []
    results = obj.get("SearchResults") or []
    return [str(c.get("Id")) for c in results if c.get("Id")]


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    print("Goal: get page 2 (offset 200) of encar listing, different IDs from page 1.\n")

    # Baseline: page 1 via current URL to get reference set
    print("====== BASELINE: page 1 (current collect_encar URL) ======")
    base_url = build_listing_url_a(0)
    status, content, err = probe(base_url, render=True)
    print(f"URL: {base_url[:140]}")
    print(f"HTTP: {status}")
    page1_ids = extract_ids_from_html(content) if status == 200 else []
    print(f"IDs found: {len(page1_ids)}")
    if page1_ids:
        print(f"  first 5: {page1_ids[:5]}")
        print(f"  last 5:  {page1_ids[-5:]}")

    # Variant A: from in search dict
    print("\n====== VARIANT A: search dict includes 'from':200 ======")
    url_a = build_listing_url_a(200)
    status, content, err = probe(url_a, render=True)
    print(f"URL: {url_a[:140]}")
    print(f"HTTP: {status}")
    ids_a = extract_ids_from_html(content) if status == 200 else []
    print(f"IDs found: {len(ids_a)}")
    if ids_a:
        new_a = set(ids_a) - set(page1_ids)
        print(f"  first 5: {ids_a[:5]}")
        print(f"  NEW vs page1: {len(new_a)}/{len(ids_a)}")
        if len(new_a) > len(ids_a) * 0.5:
            print("  ✅ VARIANT A WORKS — different cars from page 1")
        else:
            print("  ❌ Same cars as page 1 — no pagination")

    # Variant B: explicit ?from=200
    print("\n====== VARIANT B: explicit ?from=200 query param ======")
    url_b = build_listing_url_b(200)
    status, content, err = probe(url_b, render=True)
    print(f"URL: {url_b[:140]}")
    print(f"HTTP: {status}")
    ids_b = extract_ids_from_html(content) if status == 200 else []
    print(f"IDs found: {len(ids_b)}")
    if ids_b:
        new_b = set(ids_b) - set(page1_ids)
        print(f"  first 5: {ids_b[:5]}")
        print(f"  NEW vs page1: {len(new_b)}/{len(ids_b)}")
        if len(new_b) > len(ids_b) * 0.5:
            print("  ✅ VARIANT B WORKS")
        else:
            print("  ❌ Same cars as page 1")

    # Variant C: direct API
    print("\n====== VARIANT C: direct api.encar.com/search/car/list/general ======")
    url_c0 = build_api_url(0, 20)
    url_c200 = build_api_url(200, 20)

    print(f"\n  C.1 offset=0, limit=20:")
    print(f"  URL: {url_c0[:160]}")
    status, content, err = probe(url_c0, render=False)
    print(f"  HTTP: {status}, size: {len(content)}")
    ids_c0 = extract_ids_from_api(content) if status == 200 else []
    print(f"  IDs found: {len(ids_c0)}")
    if ids_c0:
        print(f"    first 5: {ids_c0[:5]}")

    print(f"\n  C.2 offset=200, limit=20:")
    print(f"  URL: {url_c200[:160]}")
    status, content, err = probe(url_c200, render=False)
    print(f"  HTTP: {status}, size: {len(content)}")
    ids_c200 = extract_ids_from_api(content) if status == 200 else []
    print(f"  IDs found: {len(ids_c200)}")
    if ids_c200:
        new_c = set(ids_c200) - set(ids_c0)
        print(f"    first 5: {ids_c200[:5]}")
        print(f"    NEW vs C.1: {len(new_c)}/{len(ids_c200)}")
        if status == 200 and len(new_c) > len(ids_c200) * 0.5:
            print("  ✅ VARIANT C WORKS — direct API paginates correctly")
            print("    AND it works WITHOUT render → \\$0.002 per page!")
            # Save sample
            sample_path = os.path.join(OUT_DIR, "api_general_sample.json")
            with open(sample_path, "w", encoding="utf-8") as f:
                f.write(content[:50000])
            print(f"    Sample saved → {sample_path}")

    print("\n========== DONE ==========")
    print("Compare the three variants above. Whichever shows >50% NEW IDs wins.")


if __name__ == "__main__":
    main()
