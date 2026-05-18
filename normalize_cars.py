"""normalize_cars.py — apply chinese_maps to existing `cars` rows.

When we update `chinese_maps.py` with new brand/color/fuel/etc entries,
existing rows in the DB stay outdated. This script re-applies the maps to
every row that has the original-language field but is missing the
normalized English equivalent.

Safe to run repeatedly — only writes if target field is currently NULL or
doesn't match the new map result. Idempotent.

Usage:
    python normalize_cars.py [--source che168] [--dry-run]
Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import re
import sys
from typing import Any

import db as DB
from chinese_maps import (
    BRAND_MAP, COLOR_MAP, FUEL_MAP, TRANSMISSION_MAP, DRIVE_MAP, CITY_MAP,
)

sys.stdout.reconfigure(line_buffering=True)

BATCH_SIZE = 500
SOURCES = ("che168", "guazi", "autocango")

# Sort prefixes by length DESC so the longest CN brand stem wins
SORTED_BRANDS = sorted(BRAND_MAP, key=len, reverse=True)
HAS_CN = re.compile(r"[一-鿿]")


def strip_brand_prefix(s: str) -> tuple[str, str]:
    """Return (matched_prefix, remainder). If nothing matches, ('', s)."""
    if not s:
        return "", s
    for p in SORTED_BRANDS:
        if s.startswith(p):
            return p, s[len(p):].strip()
    return "", s


def normalize_series(series_zh: str, brand_zh: str) -> str:
    """Strip brand prefix from series, translate 系→Series 级→Class.

    If the brand prefix consumed the entire series (e.g. "Cayenne 2024款" where
    the brand-stem and the series are the same word), keep the original as the
    model name instead of returning empty.
    """
    if not series_zh:
        return ""
    original = series_zh
    # Strip brand prefix if it's there
    if brand_zh and series_zh.startswith(brand_zh):
        series_zh = series_zh[len(brand_zh):]
    else:
        prefix, rest = strip_brand_prefix(series_zh)
        if prefix:
            series_zh = rest
    series_zh = series_zh.replace("系", " Series").replace("级", " Class").strip()
    return series_zh or original


def normalize_row(row: dict) -> dict:
    """Return a delta dict with only fields that should be updated."""
    delta: dict[str, Any] = {}

    # 1. Mark (brand) — from mark_original OR series_original via BRAND_MAP.
    # che168 listings sometimes drop the brand prefix entirely, so first word
    # of series_original may itself be a model-as-brand stem (e.g. "Cayenne",
    # "Elantra", "Model 3", "傲虎").
    mark_orig = row.get("mark_original") or ""
    series_orig_raw = row.get("series_original") or ""
    candidate = mark_orig or series_orig_raw
    if candidate:
        prefix, _ = strip_brand_prefix(candidate)
        new_mark = BRAND_MAP.get(prefix) or BRAND_MAP.get(candidate)
        if new_mark and new_mark != row.get("mark"):
            delta["mark"] = new_mark

    # 2. Color
    co = row.get("color_original")
    if co:
        new_color = COLOR_MAP.get(co.strip())
        if new_color and new_color != row.get("color"):
            delta["color"] = new_color

    # 3. Fuel → engine_type
    fo = row.get("fuel_original")
    if fo:
        new_fuel = FUEL_MAP.get(fo.strip())
        if new_fuel and new_fuel != row.get("engine_type"):
            delta["engine_type"] = new_fuel

    # 4. Transmission
    to = row.get("transmission_original")
    if to:
        new_tr = TRANSMISSION_MAP.get(to.strip())
        if new_tr and new_tr != row.get("transmission_type"):
            delta["transmission_type"] = new_tr

    # 5. Drive type
    do = row.get("drive_original")
    if do:
        new_dr = DRIVE_MAP.get(do.strip())
        if new_dr and new_dr != row.get("drive_type"):
            delta["drive_type"] = new_dr

    # 6. City
    cio = row.get("city_original")
    if cio:
        new_city = CITY_MAP.get(cio.strip())
        if new_city and new_city != row.get("city"):
            delta["city"] = new_city

    # 7. Model — rebuild if (a) has Chinese chars OR (b) is missing the brand prefix
    cur_model = row.get("model") or ""
    target_mark = delta.get("mark") or row.get("mark")
    if target_mark and series_orig_raw:
        cleaned = normalize_series(series_orig_raw, mark_orig)
        if cleaned and not HAS_CN.search(cleaned):
            new_model = f"{target_mark} {cleaned}".strip()
            need_rebuild = (
                HAS_CN.search(cur_model)
                or not cur_model.startswith(target_mark)
            )
            if need_rebuild and new_model != cur_model:
                delta["model"] = new_model

    return delta


def fetch_rows(source: str, offset: int, limit: int) -> list[dict]:
    """Fetch a page of cars rows with the columns we need."""
    select = ("id,source_id,mark,mark_original,model,series_original,"
              "color,color_original,fuel_original,engine_type,"
              "transmission_original,transmission_type,"
              "drive_original,drive_type,city,city_original")
    r = DB._pg_request(
        "GET",
        f"cars?source=eq.{source}&select={select}"
        f"&order=id&offset={offset}&limit={limit}",
    )
    if r.status_code != 200:
        print(f"fetch FAIL {r.status_code}: {r.text[:200]}")
        return []
    return r.json()


def patch_row(row_id: int, delta: dict) -> bool:
    r = DB._pg_request(
        "PATCH", f"cars?id=eq.{row_id}",
        headers={"Prefer": "return=minimal"},
        json=delta,
    )
    return r.status_code in (200, 204)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES) + ["all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    targets = SOURCES if args.source == "all" else [args.source]
    grand_total = grand_changed = 0

    for source in targets:
        print(f"\n=== {source} ===")
        scanned = 0
        changed = 0
        offset = 0
        while True:
            rows = fetch_rows(source, offset, BATCH_SIZE)
            if not rows:
                break
            for row in rows:
                scanned += 1
                delta = normalize_row(row)
                if not delta:
                    continue
                if args.dry_run:
                    print(f"  [{row['source_id']}] would update: {delta}")
                    changed += 1
                else:
                    if patch_row(row["id"], delta):
                        changed += 1
                        if changed <= 5:
                            print(f"  [{row['source_id']}] {delta}")
            offset += BATCH_SIZE
            print(f"  scanned: {scanned}, changed: {changed}")
        grand_total += scanned
        grand_changed += changed

    print(f"\nDone. Scanned {grand_total}, updated {grand_changed}.")


if __name__ == "__main__":
    main()
