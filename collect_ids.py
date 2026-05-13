"""
Dongchedi listing ID collector using Oxylabs render=html + browser_instructions.

Loads listing page in headless browser, scrolls to bottom N times so lazy-load
fires their API with auto-generated msToken/a_bogus, extracts all sku_ids
from final rendered HTML.

Usage:
    python collect_ids.py [--limit 1000] [--scrolls 30]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

LISTING_URL = "https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x"

DB_PATH = "cars.db"

CARD_LINK_RE = re.compile(r'/usedcar/(\d{7,})')


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_listing_with_scroll(scrolls: int = 20) -> str | None:
    """
    Render listing page and scroll to bottom multiple times.
    Each scroll triggers dongchedi's lazy-load → more cars appear in DOM.
    Returns final HTML or None.
    """
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS environment variables")

    # Build scroll instructions: scroll_to_bottom waits N seconds at the bottom
    # so the API call (POST sh_sku_list) has time to fire and DOM to update.
    instructions = []
    for i in range(scrolls):
        instructions.append({
            "type": "scroll_to_bottom",
            "wait_time_s": 2,
        })

    payload = {
        "source": "universal",
        "url": LISTING_URL,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
        "browser_instructions": instructions,
    }

    print(f"Requesting listing with {scrolls} scrolls (estimated {scrolls * 2}s wait time)...")
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
        status_code = result0.get("status_code")
        if status_code and status_code != 200:
            print(f"target HTTP {status_code}")
        content = result0.get("content", "")
        warnings = result0.get("browser_instructions_warnings")
        if warnings:
            print(f"  browser warnings: {warnings}")
        return content if isinstance(content, str) else None
    except Exception as e:
        print(f"exception: {e}")
        return None


def extract_card_ids(html: str) -> list[str]:
    return list(dict.fromkeys(CARD_LINK_RE.findall(html)))


def db_init() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pending_ids (
            sku_id TEXT PRIMARY KEY,
            brand_name TEXT,
            series_name TEXT,
            car_name TEXT,
            car_year INTEGER,
            car_source_city_name TEXT,
            sh_city_name TEXT,
            shop_id TEXT,
            transfer_cnt INTEGER,
            found_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pending_city ON pending_ids(sh_city_name);
    """)
    conn.commit()
    return conn


def save_id(conn: sqlite3.Connection, sku_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM pending_ids WHERE sku_id = ?", (sku_id,))
    is_new = cur.fetchone() is None
    if is_new:
        conn.execute("""
            INSERT INTO pending_ids (sku_id, found_at)
            VALUES (?, ?)
        """, (sku_id, now_iso()))
        conn.commit()
    return is_new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000,
                    help="Stop after collecting this many new IDs total")
    ap.add_argument("--scrolls", type=int, default=10,
                    help="Number of scroll-to-bottom actions per request (each loads ~20 cars)")
    args = ap.parse_args()

    print(f"Target: {args.limit} IDs")
    print(f"Scrolls per request: {args.scrolls}")
    print(f"Expected cars per request: ~{args.scrolls * 20} (in theory)")

    conn = db_init()
    existing = conn.execute("SELECT COUNT(*) FROM pending_ids").fetchone()[0]
    print(f"pending_ids already in DB: {existing}")

    html = fetch_listing_with_scroll(scrolls=args.scrolls)
    if not html:
        print("Failed to fetch listing")
        return

    print(f"Got HTML: {len(html)} bytes")
    ids = extract_card_ids(html)
    print(f"Extracted {len(ids)} unique IDs from HTML")

    new_count = 0
    for sku_id in ids:
        if save_id(conn, sku_id):
            new_count += 1
        if new_count >= args.limit:
            break

    final = conn.execute("SELECT COUNT(*) FROM pending_ids").fetchone()[0]
    print(f"\nDone. New: {new_count}, total in pending_ids: {final}")
    print(f"\nNow run:  python scrape_dongchedi.py --skip-listing --limit {final}")
    conn.close()


if __name__ == "__main__":
    main()