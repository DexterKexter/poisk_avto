"""
Autocango.com card scraper — playwright + DOM extraction.

For each pending ID, opens https://www.autocango.com/sku/usedcar-<...>-<ID>
via headless Chromium, scrapes detail page fields (specs, options, photos,
both MSRP CNY and Export USD prices).

Usage:
    python scrape_autocango.py --limit 500

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

SOURCE = "autocango"
SOURCE_LANGUAGE = "en"
PRICE_CURRENCY = "USD"
KM_AGE_UNIT = "km"
BASE_URL = "https://www.autocango.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


# Drivetrain mapping
DRIVE_MAP = {
    "2WD": "FWD",
    "4WD": "AWD",
    "FWD": "FWD",
    "RWD": "RWD",
    "AWD": "AWD",
}

# Fuel → engine_type
FUEL_MAP = {
    "Petrol": "Petrol",
    "Gasoline": "Petrol",
    "Diesel": "Diesel",
    "BEV": "Electric",
    "Electric": "Electric",
    "Hybrid": "Hybrid",
    "PHEV": "PHEV",
    "EREV": "EREV",
    "LPG": "LPG",
    "CNG": "CNG",
}

TRANSMISSION_MAP = {
    "AT": "Automatic",
    "MT": "Manual",
    "CVT": "CVT",
    "DCT": "DCT",
    "AMT": "AMT",
    "Auto": "Automatic",
    "Automatic": "Automatic",
    "Manual": "Manual",
}


def tr(value: str, mapping: dict, default: str = "") -> str:
    if not value:
        return default
    return mapping.get(value.strip(), value.strip()) or default


def build_detail_url(meta: dict, source_id: str) -> str:
    """Reconstruct detail URL from saved metadata."""
    href = (meta or {}).get("href")
    if href:
        return href
    type_slug = (meta or {}).get("type_slug") or "usedcar"
    brand = (meta or {}).get("brand_slug") or "Unknown"
    model = (meta or {}).get("model_slug") or "Model"
    model = model.replace(" ", "-")
    return f"{BASE_URL}/sku/{type_slug}-{brand}-{model}-{source_id}"


def extract_detail_js() -> str:
    """JS that pulls everything we need from the detail page."""
    return r"""() => {
        const text = (document.body.innerText || '').replace(/[ \t]+/g, ' ');
        const lines = text.split('\n').map(s => s.trim()).filter(Boolean);

        // Find specific labelled values
        const findAfter = (label) => {
            for (let i = 0; i < lines.length; i++) {
                if (lines[i] === label || lines[i].startsWith(label + ' ')) {
                    if (lines[i].length > label.length + 1) {
                        return lines[i].substring(label.length).trim();
                    }
                    if (i + 1 < lines.length) return lines[i + 1];
                }
            }
            return null;
        };

        // All H1 / title
        const title = (document.querySelector('h1, .car-title')?.innerText || '').trim();

        // Image URLs (real photos, not icons)
        const images = Array.from(document.querySelectorAll('img'))
            .map(i => i.src)
            .filter(s => s && /\.(jpe?g|png|webp)/i.test(s)
                          && !s.startsWith('data:')
                          && !s.includes('rule-traffic-light')
                          && !s.includes('logo'));

        // Prices: $X,XXX (export) and MSRP ¥X,XXX (Chinese factory)
        let export_usd = null, msrp_cny = null;
        const usdMatch = text.match(/\$\s*([\d,]+)/);
        if (usdMatch) export_usd = parseInt(usdMatch[1].replace(/,/g, ''), 10);
        const cnyMatch = text.match(/MSRP[^\d]*¥\s*([\d,]+)/);
        if (cnyMatch) msrp_cny = parseInt(cnyMatch[1].replace(/,/g, ''), 10);

        // Description block (between "Description" and "Contact your AutoCango")
        let description = '';
        const descStart = text.indexOf('Description');
        const descEnd = text.indexOf('Contact your AutoCango');
        if (descStart > 0 && descEnd > descStart) {
            description = text.substring(descStart + 'Description'.length, descEnd).trim();
        }

        // Accessories list (between "Accessories" and "Relevant Car Specs"/"Spec")
        let accessories = [];
        const accStart = text.indexOf('Accessories');
        const accEnd = Math.min(
            ...['Relevant Car Specs', 'Vehicle Specs', 'Brand'].map(s => {
                const idx = text.indexOf(s, accStart + 12);
                return idx > 0 ? idx : 999999;
            })
        );
        if (accStart > 0 && accEnd < text.length) {
            accessories = text.substring(accStart + 'Accessories'.length, accEnd)
                .split('\n').map(s => s.trim()).filter(Boolean);
        }

        // City (often appears on detail page near body or in breadcrumb)
        const cityMatch = text.match(/\b([A-Z][a-z]+)\s+(?:[A-Z][a-z]+\s+)?China\b/);
        const city = cityMatch ? cityMatch[1] : null;

        return {
            title,
            text_full: text.slice(0, 6000),
            images: images.slice(0, 30),
            export_usd, msrp_cny,
            description: description.slice(0, 5000),
            accessories: accessories.slice(0, 60),
            city,
            // Specific labelled fields
            ref_id: findAfter('Ref ID'),
            steering: findAfter('Steering'),
            model_code: findAfter('Model Code'),
            body_type: findAfter('Body Type'),
            model_year: findAfter('Model Year'),
            mileage: findAfter('Mlg(km)'),
            color: findAfter('Exterior Color'),
            fuel: findAfter('Fuel'),
            engine: findAfter('Engine'),
            transmission: findAfter('Transmission'),
            drivetrain: findAfter('Drivetrain'),
            battery_cap: findAfter('Batt.Cap.(kWh)'),
            range_km: findAfter('Range(km)'),
            motor_power: findAfter('Motor Power(kW)'),
            seats: findAfter('Seats'),
            doors: findAfter('Doors'),
            dimensions: findAfter('Dim.(mm)'),
            volume_m3: findAfter('M³'),
            weight_kg: findAfter('Weight(kg)'),
            max_cap_kg: findAfter('Max.Cap(kg)'),
            brand: findAfter('Brand'),
            series: findAfter('Series'),
            engine_cc: findAfter('Engine(cc)'),
            reg_year_month: findAfter('Reg. Year'),
        };
    }"""


def safe_int(value) -> int | None:
    if not value or value == "-":
        return None
    try:
        return int(re.sub(r'[^\d]', '', str(value)))
    except Exception:
        return None


def parse_detail_to_car(source_id: str, detail: dict, meta: dict) -> dict:
    """Map scraped detail page fields to cars schema."""
    ts = DB.now_iso()

    # Parse dimensions
    dim_m = re.match(r'(\d+)\*(\d+)\*(\d+)', detail.get("dimensions", "") or "")
    length = int(dim_m.group(1)) if dim_m else None
    width = int(dim_m.group(2)) if dim_m else None
    height = int(dim_m.group(3)) if dim_m else None

    # Parse reg date: "2019-06"
    reg_date = None
    rym = detail.get("reg_year_month") or ""
    rm = re.match(r'(\d{4})-(\d{1,2})', rym)
    if rm:
        reg_date = f"{rm.group(1)}-{int(rm.group(2)):02d}-01"

    # Engine — parse displacement (L) and horsepower
    eng = detail.get("engine", "") or ""
    disp_match = re.search(r'(\d+\.\d+)\s*[TL]', eng)
    displacement_l = float(disp_match.group(1)) if disp_match else None
    hp_match = re.search(r'(\d+)\s*HP', eng)
    horsepower = int(hp_match.group(1)) if hp_match else None

    # Year — prefer model_year if present
    year = safe_int(detail.get("model_year"))
    if not year and reg_date:
        year = int(reg_date[:4])

    # Brand/model strings
    brand = (detail.get("brand") or meta.get("brand_slug") or "").strip()
    series = (detail.get("series") or "").strip()
    if not series and meta.get("model_slug"):
        series = meta["model_slug"]

    title = detail.get("title") or ""
    if not title:
        title = f"{brand} {series}".strip()

    # Price: detail's export_usd is per-car USD export price
    price_usd = detail.get("export_usd") or meta.get("price_usd")
    msrp_cny = detail.get("msrp_cny")

    return {
        "source": SOURCE,
        "source_id": str(source_id),
        "source_language": SOURCE_LANGUAGE,
        "url": build_detail_url(meta, source_id),
        "title": title,

        "mark_original": brand,
        "mark": brand,
        "series_original": series,
        "model": f"{series}".strip(),
        "complectation": "",
        "year": year,

        "price_original": price_usd,
        "price_currency": PRICE_CURRENCY if price_usd else None,
        "new_price_original": msrp_cny,
        "new_price_currency": "CNY" if msrp_cny else None,

        "km_age_original": safe_int(detail.get("mileage")),
        "km_age_unit": KM_AGE_UNIT,
        "km_age": safe_int(detail.get("mileage")),

        "color_original": detail.get("color", "") or "",
        "color": detail.get("color", "") or "",

        "body_type": detail.get("body_type", "") or "",
        "engine_type": tr(detail.get("fuel", ""), FUEL_MAP),
        "fuel_original": detail.get("fuel", "") or "",
        "transmission_original": detail.get("transmission", "") or "",
        "transmission_type": tr(detail.get("transmission", ""), TRANSMISSION_MAP),
        "drive_original": detail.get("drivetrain", "") or "",
        "drive_type": tr(detail.get("drivetrain", ""), DRIVE_MAP),

        "displacement": displacement_l,
        "horse_power": horsepower,
        "acceleration_time": "",

        "length_mm": length,
        "width_mm": width,
        "height_mm": height,
        "wheelbase_mm": None,

        "city_original": detail.get("city", "") or "",
        "city": detail.get("city", "") or "",
        "reg_city_original": "",
        "reg_city": "",
        "reg_date": reg_date,

        "owners_count": None,
        "maintenance": "",
        "interior_color_original": "",
        "description": detail.get("description", "") or "",

        "images": detail.get("images", []),
        "image_count": len(detail.get("images", []) or []),

        "seller_type": "Exporter",
        "shop_name": "AutoCango",
        "shop_short_name": "",
        "shop_address": "",
        "shop_id": "",
        "shop_cars_count": None,
        "sales_range": "Export",

        "vin": None,  # autocango doesn't expose VIN on listing
        "spu_id": "",

        "published_at": None,  # not exposed
        "listing_updated_at": None,

        "source_data": {
            "ref_id": detail.get("ref_id"),
            "steering": detail.get("steering"),
            "model_code": detail.get("model_code"),
            "engine_cc": safe_int(detail.get("engine_cc")),
            "battery_capacity_kwh": detail.get("battery_cap"),
            "range_km": detail.get("range_km"),
            "motor_power_kw": detail.get("motor_power"),
            "seats": safe_int(detail.get("seats")),
            "doors": safe_int(detail.get("doors")),
            "volume_m3": detail.get("volume_m3"),
            "weight_kg": safe_int(detail.get("weight_kg")),
            "max_cap_kg": safe_int(detail.get("max_cap_kg")),
            "accessories": detail.get("accessories", []),
            "compliant_180day": meta.get("compliant_180day"),
            "type_slug": meta.get("type_slug"),
            "msrp_cny": msrp_cny,
        },

        "first_seen": ts,
        "last_seen": ts,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE}")
    existing = DB.count_cars(SOURCE)
    print(f"cars[{SOURCE}] already: {existing}")

    ids = DB.get_pending_ids(SOURCE, args.limit)
    print(f"Loaded {len(ids)} pending IDs\n")
    if not ids:
        print("Nothing to scrape. Run collect_autocango.py first.")
        return

    # Fetch metadata for each ID so we can reconstruct URLs
    metas: dict[str, dict] = {}
    if DB.USE_POSTGRES:
        for chunk_start in range(0, len(ids), 100):
            chunk = ids[chunk_start:chunk_start + 100]
            ids_in = ",".join(f'"{i}"' for i in chunk)
            r = DB._pg_request(
                "GET",
                f"pending_ids?source=eq.{SOURCE}"
                f"&source_id=in.({ids_in})"
                f"&select=source_id,metadata"
            )
            if r.status_code == 200:
                for row in r.json():
                    metas[row["source_id"]] = row.get("metadata") or {}

    started = time.time()
    ok = fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        # Warm the WAF cookies by visiting listing page once
        warmup = ctx.new_page()
        try:
            warmup.goto("https://www.autocango.com/usedcar/excludeSold=true",
                        wait_until="networkidle", timeout=60_000)
        except Exception:
            pass
        warmup.close()
        page = ctx.new_page()

        for i, cid in enumerate(ids, 1):
            meta = metas.get(cid, {})
            url = build_detail_url(meta, cid)
            try:
                page.goto(url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1000)
                detail = page.evaluate(extract_detail_js())
            except Exception as e:
                fail += 1
                DB.mark_failed(SOURCE, cid)
                print(f"  [{i}/{len(ids)}] {cid} FAIL: {e}")
                continue

            rec = parse_detail_to_car(cid, detail, meta)
            if DB.upsert_car(rec):
                ok += 1
                print(f"  [{i}/{len(ids)}] {cid} OK {rec['mark']} {rec['model']} "
                      f"{rec['year']} ${rec['price_original']} {rec['km_age']}km")
            else:
                fail += 1
                DB.mark_failed(SOURCE, cid)
                print(f"  [{i}/{len(ids)}] {cid} DB FAIL")

        browser.close()

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. OK: {ok}, FAIL: {fail}")
    print(f"Total cars[{SOURCE}]: {DB.count_cars(SOURCE)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
