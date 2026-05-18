"""guazi.com listing collector — direct HTTP, $0.

Strategy:
  - Visit /{city_slug}/buy/ pages (redirects to /{city_slug}/)
  - HTML has 400 `.car-item` blocks; each has detail URL, title, price, year, mileage, badges
  - Filter in Python: year ≥ MIN_YEAR, mileage ≤ MAX_MILEAGE_KM, price ≥ MIN_PRICE_CNY
  - Save to pending_ids with metadata

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi"
BASE_URL = "https://www.guazi.com"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.guazi.com/",
}

CITIES = {
    "Beijing":    "bj",
    "Shanghai":   "sh",
    "Guangzhou":  "gz",
    "Shenzhen":   "sz",
    "Chengdu":    "cd",
    "Hangzhou":   "hz",
}


def build_listing_url(city_slug: str, page: int, min_year: int) -> str:
    """guazi /{slug}/buy/o{page}c-1n0p0g0s0v0t0z0r0e2y{min_year}-ax/.

    `e2` = exclude sold. `y{year}` = min year. `o{page}` = page number.
    But the simpler /{slug}/ also works and shows current inventory.
    """
    if page == 1:
        return f"{BASE_URL}/{city_slug}/?excludeSold=1"
    return f"{BASE_URL}/{city_slug}/o{page}/"


HREF_RE  = re.compile(r'href="(/car-detail/c(\d+)\.html)"')
ALT_RE   = re.compile(r'alt="([^"]+)"')
PHOTO_RE = re.compile(r'src="(https?://[^"?]+)')
DESC_RE  = re.compile(r'<div class="car-item-info-desc">(.+?)</div>', re.DOTALL)
TAGS_RE  = re.compile(r'<div class="car-item-info-tag">(.+?)</div>\s*<div', re.DOTALL)
PRICE_RE = re.compile(r'<span class="car-item-info-price-value">([\d.]+)</span>')


def extract_cards(html: str) -> list[dict]:
    """Split HTML on `<div class="car-item">` and parse each block individually."""
    chunks = html.split('<div class="car-item ">')[1:]
    out: list[dict] = []
    for chunk in chunks:
        # Cards are ~2KB; cap defensively so regex stays fast
        block = chunk[:3000]

        href = HREF_RE.search(block);    alt = ALT_RE.search(block)
        photo = PHOTO_RE.search(block);  desc = DESC_RE.search(block)
        tags_m = TAGS_RE.search(block);  price = PRICE_RE.search(block)
        if not (href and alt and desc and price):
            continue

        # Desc contains HTML comments `<!-- -->` between segments — strip them
        desc_text = re.sub(r"<[^>]+>", "", desc.group(1))
        d_parts = [p.strip() for p in desc_text.split("|") if p.strip()]
        year = mileage_km = city = None
        for p in d_parts:
            ym = re.search(r"(\d{4})\s*年", p)
            if ym:
                year = int(ym.group(1)); continue
            km = re.search(r"([\d.]+)\s*万\s*公里", p)
            if km:
                mileage_km = int(float(km.group(1)) * 10_000); continue
            if re.search(r"[一-龥]", p):
                city = p
        tags = re.findall(r"<span[^>]*>([^<]+)</span>",
                          tags_m.group(1) if tags_m else "")
        out.append({
            "url": BASE_URL + href.group(1),
            "clue_id": href.group(2),
            "title": alt.group(1),
            "thumb_url": photo.group(1) if photo else None,
            "year": year,
            "mileage_km": mileage_km,
            "city": city,
            "tags": tags,
            "price_cny": int(float(price.group(1)) * 10_000),
        })
    return out


def card_passes_filters(card: dict, min_year: int, max_mileage_km: int,
                        min_price_cny: int) -> tuple[bool, str]:
    if not card.get("year") or card["year"] < min_year:
        return False, f"year {card.get('year')} < {min_year}"
    if not card.get("mileage_km") or card["mileage_km"] > max_mileage_km:
        return False, f"mileage {card.get('mileage_km')} > {max_mileage_km}"
    if not card.get("price_cny") or card["price_cny"] < min_price_cny:
        return False, f"price {card.get('price_cny')} < {min_price_cny}"
    return True, ""


def upsert_pending(card: dict) -> bool:
    rec = {
        "source": SOURCE,
        "source_id": str(card["clue_id"]),
        "metadata": {
            "url":       card["url"],
            "title":     card["title"],
            "thumb_url": card.get("thumb_url"),
            "year":      card.get("year"),
            "mileage_km": card.get("mileage_km"),
            "price_cny": card.get("price_cny"),
            "city":      card.get("city"),
            "tags":      card.get("tags"),
        },
        "found_at": DB.now_iso(),
    }
    return DB.upsert_pending(rec)


def fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        r.encoding = "utf-8"
        if r.status_code != 200 or len(r.text) < 5000:
            return None
        return r.text
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", type=str, default=",".join(CITIES.keys()))
    ap.add_argument("--pages-per-city", type=int, default=20)
    ap.add_argument("--min-year", type=int, default=2020)
    ap.add_argument("--max-mileage-km", type=int, default=100_000)
    ap.add_argument("--min-price-cny", type=int, default=5_000)
    ap.add_argument("--limit", type=int, default=10_000)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    invalid = [c for c in cities if c not in CITIES]
    if invalid:
        sys.exit(f"Unknown: {invalid}. Available: {list(CITIES.keys())}")

    print(f"Collecting guazi: {len(cities)} cities × ≤{args.pages_per_city} pages")
    print(f"  filters: year≥{args.min_year}, mileage≤{args.max_mileage_km:,}km, "
          f"price≥¥{args.min_price_cny:,}")

    saved = 0
    skipped = 0
    started = time.time()

    for city in cities:
        slug = CITIES[city]
        print(f"\n[{city}] /{slug}/")
        seen = set()
        for page_num in range(1, args.pages_per_city + 1):
            if saved >= args.limit:
                print(f"  reached cap {args.limit}")
                break
            url = build_listing_url(slug, page_num, args.min_year)
            html = fetch_html(url)
            if not html:
                print(f"  [p{page_num}] empty/blocked — stop")
                break
            cards = extract_cards(html)
            if not cards:
                print(f"  [p{page_num}] 0 cards (regex no match) — stop")
                break
            page_saved = 0
            for c in cards:
                cid = c["clue_id"]
                if cid in seen:
                    continue
                seen.add(cid)
                ok, _ = card_passes_filters(
                    c, args.min_year, args.max_mileage_km, args.min_price_cny)
                if not ok:
                    skipped += 1
                    continue
                if upsert_pending(c):
                    saved += 1
                    page_saved += 1
            elapsed = int(time.time() - started)
            print(f"  [p{page_num}] {len(cards)} cards → {page_saved} kept "
                  f"(city {len(seen)}, all {saved}, {elapsed}s)")
            time.sleep(0.5)
            if len(cards) < 5:
                break

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. Upserted: {saved}, filtered: {skipped}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
