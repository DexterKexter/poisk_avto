"""
Dongchedi listing ID collector using Oxylabs render=html + browser_instructions.

Loads listing page in headless browser, scrolls to bottom N times so lazy-load
fires their internal API, extracts all sku_ids from final rendered HTML.

Usage:
    python collect_ids.py [--limit 1000] [--scrolls 10]

Env vars:
    OXY_USER, OXY_PASS  — Oxylabs credentials (required)
    SUPABASE_URL, SUPABASE_KEY — if set, writes to Postgres; otherwise to cars.db
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

LISTING_URL = "https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x"

SOURCE = "dongchedi"
CARD_LINK_RE = re.compile(r'/usedcar/(\d{7,})')


def fetch_listing_with_scroll(scrolls: int = 10) -> str | None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS environment variables")

    instructions = [
        {"type": "scroll_to_bottom", "wait_time_s": 2}
        for _ in range(scrolls)
    ]

    payload = {
        "source": "universal",
        "url": LISTING_URL,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
        "browser_instructions": instructions,
    }

    print(f"Requesting listing with {scrolls} scrolls (estimated {scrolls * 2}s wait)...")
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
        if r.status_code != 200:
            print(f"Oxylabs HTTP {r.status_code}: {r.text[:300]}")
            return None
        outer = r.json()
        results = outer.get("results", [])
        if not results:
            print(f"empty results: {str(outer)[:300]}")
            return None
        result0 = results[0]
        content = result0.get("content", "")
        return content if isinstance(content, str) else None
    except Exception as e:
        print(f"exception: {e}")
        return None


def extract_card_ids(html: str) -> list[str]:
    return list(dict.fromkeys(CARD_LINK_RE.findall(html)))


def save_id(sku_id: str) -> bool:
    return DB.upsert_pending({
        "source": SOURCE,
        "source_id": sku_id,
        "metadata": None,
        "found_at": DB.now_iso(),
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000,
                    help="Stop after collecting this many IDs total")
    ap.add_argument("--scrolls", type=int, default=10,
                    help="Number of scroll-to-bottom actions per request")
    args = ap.parse_args()

    print(f"Backend: {DB.backend_name()}")
    print(f"Target: {args.limit} IDs, scrolls: {args.scrolls}")

    existing = DB.count_pending(SOURCE)
    print(f"pending_ids[{SOURCE}] already: {existing}")

    html = fetch_listing_with_scroll(scrolls=args.scrolls)
    if not html:
        print("Failed to fetch listing")
        return

    print(f"Got HTML: {len(html)} bytes")
    ids = extract_card_ids(html)
    print(f"Extracted {len(ids)} unique IDs")

    saved = 0
    for sku_id in ids:
        if save_id(sku_id):
            saved += 1
        if saved >= args.limit:
            break

    final = DB.count_pending(SOURCE)
    print(f"\nDone. Upserted: {saved}, total in pending_ids[{SOURCE}]: {final}")


if __name__ == "__main__":
    main()
