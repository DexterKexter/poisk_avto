"""
import_model_specs.py — scrape factory specs from autocango /carspecs.

Strategy ("по брендам в cars"):
  1. SELECT DISTINCT mark FROM cars                       — what brands we care about
  2. JOIN with brands.slug WHERE source='autocango'       — get autocango canonical slugs
  3. For each matched brand:
       open /carspecs/brandName={slug}, extract model links
  4. For each model link (/cs/carspecs-Brand-Model-CODE):
       open the page, parse variants from text
       upsert each variant to model_variants table

Usage:
    python import_model_specs.py [--brands BMW,Audi]  # specific brands
    python import_model_specs.py                       # all brands in cars

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from typing import Any

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "autocango"
BASE_URL = "https://www.autocango.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def get_relevant_brands(filter_csv: str | None) -> list[dict]:
    """Brands in autocango `brands` table that also appear in cars (any source)."""
    # Distinct marks from cars
    r = DB._pg_request("GET", "cars?select=mark&mark=not.is.null")
    if r.status_code != 200:
        sys.exit(f"Failed to fetch cars marks: {r.status_code}")
    car_marks = {row["mark"] for row in r.json() if row.get("mark")}
    print(f"  Distinct marks in cars: {len(car_marks)}")

    # All autocango brands
    r = DB._pg_request(
        "GET",
        f"brands?source=eq.{SOURCE}&select=slug,name,source_url",
    )
    if r.status_code != 200:
        sys.exit(f"Failed to fetch brands: {r.status_code}")
    all_brands = r.json()

    # Match by name OR slug (autocango uses both). Case-insensitive.
    car_marks_lc = {m.lower() for m in car_marks}
    matched = []
    for b in all_brands:
        if b["name"].lower() in car_marks_lc or b["slug"].lower() in car_marks_lc:
            matched.append(b)

    # Optional CLI filter
    if filter_csv:
        wanted = {x.strip().lower() for x in filter_csv.split(",")}
        matched = [b for b in matched
                   if b["slug"].lower() in wanted or b["name"].lower() in wanted]

    print(f"  Brands matched to autocango: {len(matched)}")
    return matched


def fetch_model_links(page, brand_slug: str) -> list[dict]:
    """Open /carspecs/brandName=X, extract model spec URLs."""
    url = f"{BASE_URL}/carspecs/brandName={brand_slug}"
    try:
        page.goto(url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(2500)
    except Exception as e:
        print(f"    goto failed: {str(e)[:120]}")
        return []
    try:
        models = page.evaluate(
            r"""() => {
                const out = [];
                const seen = new Set();
                for (const a of document.querySelectorAll('a[href*="/cs/carspecs-"]')) {
                    const href = a.getAttribute('href');
                    if (!href || seen.has(href)) continue;
                    seen.add(href);
                    // /cs/carspecs-{Brand}-{Model-Name}-{5char_code}
                    const m = href.match(/\/cs\/carspecs-(.+?)-([A-Z0-9]{4,8})$/);
                    if (!m) continue;
                    // split by '-' to extract brand vs model (brand is first token, rest is model)
                    const parts = m[1].split('-');
                    const text = a.innerText.trim().slice(0, 100);
                    out.push({
                        href,
                        url: new URL(href, location.origin).href,
                        code: m[2],
                        slug_path: m[1],
                        text,
                    });
                }
                return out;
            }""")
    except Exception as e:
        print(f"    evaluate failed: {str(e)[:120]}")
        return []
    return models or []


# Regex patterns for variant fields (one variant block = one regex pass)
VARIANT_PATTERNS = {
    "model_year":          r'Model Year\s+(\d{4})',
    "fuel":                r'Fuel\s+([A-Za-z+]+)',
    "engine":              r'Engine\s+([^M]+?)(?=\s+Drivetrain|\s+Transm|\s+Electric)',
    "drivetrain":          r'Drivetrain\s+([A-Za-z0-9/]+)',
    "transmission":        r'Transm\.\s+([A-Za-z\-]+)',
    "electric_motors":     r'Electric Motor\s+(\d+)',
    "motor_layout":        r'Motor Layout\s+([A-Za-z+]+)',
    "motor_power_kw":      r'Motor Power\(kW\)\s+(\d+)',
    "battery_capacity":    r'Battery Capacity\(kWh\)\s+([\d.]+)',
    "energy_density":      r'Energy Density\(Wh/kg\)\s+([\d.]+)',
    "fast_charging":       r'Fast Charging\s+(\S+)',
    "range_km":            r'Range\(km\)\s+(\d+)',
    "cylinders":           r'Cylinders\s+(\d+)',
    "displacement":        r'Disp\.\(cc\)\s+(\d+)',
    "seats":               r'Seats\s+(\d+)',
    "doors":               r'Doors\s+(\d+)',
    "wheelbase":           r'Wheelbase\(mm\)\s+(\d+)',
    "weight":              r'Weight\(kg\)\s+(\d+)',
    "dimensions":          r'Dimension\(mm\)\s+(\d+\*\d+\*\d+)',
    "msrp_usd":            r'\＄([\d,]+)MSRP',
    "msrp_cny":            r'\￥([\d,]+)MSRP',
}


def parse_variants(text: str, model_links_on_page: list[dict]) -> list[dict]:
    """Split text by 'More Details' markers and parse each variant block."""
    # Each variant ends with "More Details"
    blocks = text.split("More Details")
    out = []
    for block in blocks:
        block = block.strip()
        if len(block) < 100:
            continue
        # Title is "2025 BrandName Model … " before "Model Year"
        m = re.search(r'(\d{4})\s+([^\d].+?)\s+Model Year', block)
        full_name = m.group(0).rstrip(" Model Year").strip() if m else ""

        rec: dict[str, Any] = {"full_name": full_name}
        for key, pattern in VARIANT_PATTERNS.items():
            m = re.search(pattern, block)
            if m:
                rec[key] = m.group(1).strip()
        if rec.get("model_year"):
            out.append(rec)
    return out


def to_int(v) -> int | None:
    if not v or v == "-":
        return None
    try:
        return int(str(v).replace(",", "").replace("*", "").split(".")[0])
    except Exception:
        return None


def to_num(v) -> float | None:
    if not v or v == "-":
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def to_bool_fc(v: str | None) -> bool | None:
    if v is None:
        return None
    return v.strip().lower() == "supported"


def variant_to_db(rec: dict, brand: dict, model_meta: dict) -> dict:
    """Map parsed variant fields to DB row."""
    dims = rec.get("dimensions", "")
    length = width = height = None
    if dims:
        m = re.match(r'(\d+)\*(\d+)\*(\d+)', dims)
        if m:
            length, width, height = map(int, m.groups())

    return {
        "brand_slug": brand["slug"],
        "brand_name": brand["name"],
        "model_slug": model_meta["slug_path"],
        "model_name": model_meta.get("text", "").split("\n")[0].strip() or model_meta["slug_path"],
        "variant_code": model_meta["code"] + "_" + str(rec.get("model_year", "")) + "_" +
                        re.sub(r'\W+', '_', rec.get("full_name", ""))[:30],
        "full_name":          rec.get("full_name") or None,
        "model_year":         to_int(rec.get("model_year")),
        "fuel":               rec.get("fuel") or None,
        "engine":             rec.get("engine", "").strip() or None,
        "drivetrain":         rec.get("drivetrain") or None,
        "transmission":       rec.get("transmission") or None,
        "electric_motors":    to_int(rec.get("electric_motors")),
        "motor_layout":       rec.get("motor_layout") or None,
        "motor_power_kw":     to_int(rec.get("motor_power_kw")),
        "battery_capacity_kwh": to_num(rec.get("battery_capacity")),
        "energy_density_wh_kg": to_num(rec.get("energy_density")),
        "fast_charging":      to_bool_fc(rec.get("fast_charging")),
        "range_km":           to_int(rec.get("range_km")),
        "cylinders":          to_int(rec.get("cylinders")),
        "displacement_cc":    to_int(rec.get("displacement")),
        "seats":              to_int(rec.get("seats")),
        "doors":              to_int(rec.get("doors")),
        "wheelbase_mm":       to_int(rec.get("wheelbase")),
        "weight_kg":          to_int(rec.get("weight")),
        "length_mm":          length,
        "width_mm":           width,
        "height_mm":          height,
        "msrp_cny":           to_int(rec.get("msrp_cny")),
        "msrp_usd":           to_int(rec.get("msrp_usd")),
        "source":             SOURCE,
        "source_url":         model_meta["url"],
        "updated_at":         DB.now_iso(),
    }


def upsert_variant(rec: dict) -> bool:
    r = DB._pg_request(
        "POST", "model_variants?on_conflict=source,variant_code",
        headers={"Prefer": "return=minimal,resolution=merge-duplicates"},
        json=rec,
    )
    return r.status_code in (200, 201, 204)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", type=str, default="",
                    help="Comma-separated brand slugs (optional filter)")
    ap.add_argument("--max-models-per-brand", type=int, default=200)
    ap.add_argument("--limit-brands", type=int, default=0,
                    help="Process only first N brands (0 = all)")
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    print("Finding relevant brands…")
    brands = get_relevant_brands(args.brands or None)
    if args.limit_brands:
        brands = brands[:args.limit_brands]
    if not brands:
        print("No brands matched"); return
    print(f"Will scrape specs for {len(brands)} brands\n")

    from playwright.sync_api import sync_playwright

    started = time.time()
    total_variants = 0
    total_models = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 4000},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        for bi, brand in enumerate(brands, 1):
            print(f"\n[{bi}/{len(brands)}] {brand['name']} (slug={brand['slug']})")
            model_links = fetch_model_links(page, brand["slug"])
            print(f"  models on brand page: {len(model_links)}")
            if not model_links:
                continue
            for mi, ml in enumerate(model_links[:args.max_models_per_brand], 1):
                total_models += 1
                try:
                    page.goto(ml["url"], wait_until="load", timeout=60_000)
                    page.wait_for_timeout(1500)
                    text = page.evaluate(
                        """() => document.body.innerText.replace(/[\\s]+/g, ' ')"""
                    )
                except Exception as e:
                    print(f"    model fetch failed: {str(e)[:80]}")
                    continue
                variants = parse_variants(text, [])
                saved_in_model = 0
                for v in variants:
                    rec = variant_to_db(v, brand, ml)
                    if upsert_variant(rec):
                        saved_in_model += 1
                total_variants += saved_in_model
                if mi <= 3 or mi % 10 == 0:
                    elapsed = int(time.time() - started)
                    print(f"  [{mi}/{len(model_links)}] {ml['slug_path']:40} "
                          f"→ {saved_in_model} variants (total {total_variants}, "
                          f"{elapsed}s)")

        browser.close()

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s.")
    print(f"  Models scraped:   {total_models}")
    print(f"  Variants saved:   {total_variants}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
