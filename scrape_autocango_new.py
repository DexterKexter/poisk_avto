"""
Autocango.com NEW-car detail page scraper.

Mirrors scrape_autocango.py but targets /sku/newcar-<...>-<ACN...> pages.
New cars carry no mileage / no registration date / no 180-day-rule flag,
so those fields are intentionally skipped. The km_age is forced to 0.

Usage:
    python scrape_autocango_new.py --limit 500

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import re
import sys
import time
import traceback

import db as DB

SOURCE = "autocango"
TYPE_SLUG = "newcar"
SOURCE_LANGUAGE = "en"
PRICE_CURRENCY = "USD"
KM_AGE_UNIT = "km"
BASE_URL = "https://www.autocango.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


DRIVE_MAP = {
    "2WD": "FWD",
    "4WD": "AWD",
    "FWD": "FWD",
    "RWD": "RWD",
    "AWD": "AWD",
}

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


def is_newcar_id(source_id: str) -> bool:
    """ACN-prefixed IDs belong to the newcar section."""
    return bool(source_id) and source_id.startswith("ACN")


def build_detail_url(meta: dict, source_id: str) -> str:
    """Reconstruct /sku/newcar-...-<ID> detail URL."""
    href = (meta or {}).get("href")
    if href:
        return href
    type_slug = (meta or {}).get("type_slug") or TYPE_SLUG
    brand = (meta or {}).get("brand_slug") or "Unknown"
    model = (meta or {}).get("model_slug") or "Model"
    model = model.replace(" ", "-")
    return f"{BASE_URL}/sku/{type_slug}-{brand}-{model}-{source_id}"


def extract_detail_js() -> str:
    """JS extractor for newcar detail pages.

    The /sku/newcar-... page lays out specs as a `Label\\n\\nValue\\n\\n…`
    table inside "Basic Parameters". Free-text regex against the whole
    page collides with navigation headers (e.g. matching "Transmission"
    in the section nav, capturing "Weight & Capacity" as the value), so
    we parse the parameters block into a label→value dict first and
    only then map fields.
    """
    return r"""() => {
        const rawText = document.body.innerText || '';

        // Only include images from this listing's gallery.
        // /new/<hash>.webp = primary photos; /part/<hash>.webp = part shots.
        // Everything else (/used/, /brand/, /blog/, /news/, logos, icons)
        // is from recommendations or chrome and must be excluded.
        const images = Array.from(document.querySelectorAll('img'))
            .map(i => i.src)
            .filter(s => s && /\.(jpe?g|png|webp)/i.test(s)
                          && !s.startsWith('data:')
                          && (s.includes('/new/') || s.includes('/part/'))
                          && !s.includes('rule-traffic-light')
                          && !s.includes('logo'))
            .map(s => s.split('?')[0]);
        // Dedupe while preserving order
        const seenImg = new Set();
        const uniqueImages = images.filter(s => seenImg.has(s) ? false : seenImg.add(s));

        // Prices
        let export_usd = null, msrp_cny = null;
        const usdMatch = rawText.match(/FOB[^$]*\$\s*([\d,]+)/)
                       || rawText.match(/\$\s*([\d,]+)\b/);
        if (usdMatch) export_usd = parseInt(usdMatch[1].replace(/,/g, ''), 10);
        const cnyMatch = rawText.match(/MSRP[^\d]*¥?\s*([\d,]+(?:\.\d+)?)/);
        if (cnyMatch) msrp_cny = parseInt(cnyMatch[1].replace(/[,.]/g, ''), 10);

        // City — usually "Shanghai Shanghai China" near the FOB block
        const cityMatch = rawText.match(/\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+(?:Anhui|Beijing|Chongqing|Fujian|Gansu|Guangdong|Guangxi|Guizhou|Hainan|Hebei|Heilongjiang|Henan|Hubei|Hunan|Jiangsu|Jiangxi|Jilin|Liaoning|Ningxia|Qinghai|Shaanxi|Shandong|Shanghai|Shanxi|Sichuan|Tianjin|Xinjiang|Tibet|Yunnan|Zhejiang)\s+China\b/);
        const city = cityMatch ? cityMatch[1] : null;

        // ── Spec table extraction ──
        // Strategy: walk every <div>/<span>/<td> that has only text and pair
        // each "label-looking" node with the next text node as its value.
        // The whole spec block lives between "Basic Parameters" and
        // "More Details" markers.
        const startIdx = rawText.indexOf('Basic Parameters');
        const endIdx = rawText.indexOf('More Details');
        let specBlock = (startIdx >= 0 && endIdx > startIdx)
            ? rawText.substring(startIdx, endIdx)
            : rawText;
        // Split into trimmed non-empty tokens
        const tokens = specBlock.split('\n').map(s => s.trim()).filter(Boolean);

        // Known label set — anything else is treated as a value
        const LABELS = new Set([
            'Brand','Series','Manufacturer','Model','MSRP','Launch Date','Launched Time',
            'Manufacturer Guidance Price','Vehicle Level','Energy Type','Maximum Power(kW)',
            'Maximum Power(HP)','Maximum Torque(N·m)','Engine','Engine Type','Engine Position',
            'Drivetrain','Drive Type','Number Of Cylinders','Cylinder Arrangement',
            'Valve Structure','Displacement(mL)','Displacement(L)','Intake Method',
            'Fuel','Fuel Type','Fuel Grade','Body Type','Body','Body Color',
            'Length(mm)','Width(mm)','Height(mm)','Wheelbase(mm)',
            'Front Track(mm)','Rear Track(mm)','Minimum Ground Clearance(mm)',
            'Number Of Doors','Number Of Seats','Doors','Seats',
            'Curb Weight(kg)','Max Loaded Weight(kg)','Rear Trunk Volume(L)',
            'Fuel Tank Capacity(L)','Transmission Type','Transmission Abbreviation',
            'Transmission','Number Of Gears','Steering Type','Steering','Steering Wheel Position',
            'Front Brake Type','Rear Brake Type','Parking Brake Type',
            'Front Suspension Type','Rear Suspension Type',
            'Front Tire Specs','Rear Tire Specs','Spare Tire Specs','Tire Material',
            'Battery capacity (kWh)','Battery Capacity','Range (KM)','Pure Electric Range',
            'Motor Power (kW)','Engine Power (kW)','Model Year','Warranty',
        ]);

        const specs = {};
        for (let i = 0; i < tokens.length - 1; i++) {
            const lbl = tokens[i];
            const val = tokens[i + 1];
            if (!LABELS.has(lbl)) continue;
            if (LABELS.has(val)) continue;  // adjacent labels — value missing
            if (specs[lbl] === undefined) specs[lbl] = val;
        }

        // Description block — Description ... Contact your AutoCango
        let description = '';
        const descStart = rawText.indexOf('Description');
        const descEnd = rawText.indexOf('Contact your AutoCango');
        if (descStart > 0 && descEnd > descStart) {
            description = rawText.substring(descStart + 11, descEnd).trim()
                .replace(/Availability Check：[^\n]+/, '')
                .replace(/Condition：/g, '').trim();
        }

        // Numeric helper
        const num = (v) => {
            if (!v || v === '-' || v === '○') return null;
            const m = String(v).match(/-?\d+(?:\.\d+)?/);
            return m ? m[0] : null;
        };

        // Title — prefer the "Model" field from the spec dict (canonical),
        // fall back to first line in Basic Parameters that looks like a
        // model summary, then to <h1>.
        const summaryRe = /\d{4}\s+[A-Za-z][\w \-]+?\s+\d+\.\d+[TL]?\s+\d+HP\s+L\d+(?:\s+\w+)?/;
        let title = specs['Model'] || null;
        if (!title) {
            const m = specBlock.match(summaryRe);
            title = m ? m[0].trim()
                : (document.querySelector('h1, .car-title')?.innerText || '').trim();
        }

        // Engine summary like "1.5T 160HP L4 7DCT" — extract from title once defined
        let engineSummary = null;
        const engM = (title || '').match(/(\d+\.\d+[TL]?\s+\d+HP\s+L\d+)/);
        if (engM) engineSummary = engM[1];

        return {
            title,
            images: uniqueImages.slice(0, 30),
            export_usd, msrp_cny,
            description: description.slice(0, 4000),
            accessories: [],
            city,

            // From spec dict
            brand:        specs['Brand'] || null,
            series:       specs['Series'] || null,
            model_year:   specs['Model Year'] || (title.match(/^(\d{4})/) || [])[1] || null,
            engine:       engineSummary,
            fuel:         specs['Fuel'] || specs['Fuel Type'] || specs['Energy Type'] || null,
            transmission: specs['Transmission Type'] || specs['Transmission Abbreviation'] || null,
            drivetrain:   specs['Drivetrain'] || null,
            body_type:    specs['Body Type'] || specs['Vehicle Level'] || null,
            color:        specs['Body Color'] || null,
            steering:     specs['Steering Type'] || specs['Steering Wheel Position'] || null,
            engine_cc:    num(specs['Displacement(mL)']),
            seats:        num(specs['Number Of Seats'] || specs['Seats']),
            doors:        num(specs['Number Of Doors'] || specs['Doors']),
            weight_kg:    num(specs['Curb Weight(kg)']),
            max_cap_kg:   num(specs['Max Loaded Weight(kg)']),
            battery_cap:  num(specs['Battery capacity (kWh)'] || specs['Battery Capacity']),
            range_km:     num(specs['Range (KM)'] || specs['Pure Electric Range']),
            motor_power:  num(specs['Motor Power (kW)'] || specs['Engine Power (kW)']),
            length_mm:    num(specs['Length(mm)']),
            width_mm:     num(specs['Width(mm)']),
            height_mm:    num(specs['Height(mm)']),
            wheelbase_mm: num(specs['Wheelbase(mm)']),
            model_code:   null,
            ref_id:       null,
            volume_m3:    null,
            dimensions:   null,
            specs_raw:    specs,
        };
    }"""


def safe_int(value) -> int | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(re.sub(r'[^\d]', '', str(value)))
    except Exception:
        return None


def dedupe_brand(name: str) -> str:
    """Collapse autocango's doubled brand names (e.g. 'ROXROX' -> 'ROX')."""
    if not name:
        return name
    s = name.strip()
    # Exact whole-word doubling, e.g. "ROXROX", "BMWBMW"
    m = re.match(r'^([A-Za-z]{2,})\1$', s)
    if m:
        return m.group(1)
    return s


def parse_detail_to_car(source_id: str, detail: dict, meta: dict) -> dict:
    ts = DB.now_iso()

    length = safe_int(detail.get("length_mm"))
    width = safe_int(detail.get("width_mm"))
    height = safe_int(detail.get("height_mm"))
    wheelbase = safe_int(detail.get("wheelbase_mm"))

    eng = detail.get("engine", "") or ""
    disp_match = re.search(r'(\d+\.\d+)\s*[TL]', eng)
    displacement_l = float(disp_match.group(1)) if disp_match else None
    hp_match = re.search(r'(\d+)\s*HP', eng)
    horsepower = int(hp_match.group(1)) if hp_match else None

    year = safe_int(detail.get("model_year")) or meta.get("model_year")

    brand = dedupe_brand((detail.get("brand") or meta.get("brand_slug") or "").strip())
    series = (detail.get("series") or "").strip()
    if not series and meta.get("model_slug"):
        series = meta["model_slug"]

    title = detail.get("title") or f"{brand} {series}".strip()
    # Strip the doubled brand from the title summary too
    if brand and (brand + brand) in title:
        title = title.replace(brand + brand, brand)

    price_usd = detail.get("export_usd") or meta.get("price_usd")
    msrp_cny = detail.get("msrp_cny") or meta.get("msrp_cny")

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

        # New car — zero mileage, never registered
        "km_age_original": 0,
        "km_age_unit": KM_AGE_UNIT,
        "km_age": 0,

        "color_original": detail.get("color", "") or "",
        "color": detail.get("color", "") or "",

        "body_type": detail.get("body_type", "") or "",
        "engine_type": tr(detail.get("fuel", ""), FUEL_MAP),
        "fuel_original": detail.get("fuel", "") or "",
        "transmission_original": detail.get("transmission", "") or "",
        "transmission_type": tr(detail.get("transmission", ""), TRANSMISSION_MAP),
        # Drop placeholder values like "Drive Mode" that aren't real drivetrains
        "drive_original": detail.get("drivetrain") if detail.get("drivetrain") in DRIVE_MAP else "",
        "drive_type": tr(detail.get("drivetrain", ""), DRIVE_MAP, default="") if detail.get("drivetrain") in DRIVE_MAP else "",

        "displacement": displacement_l,
        "horse_power": horsepower,
        "acceleration_time": "",

        "length_mm": length,
        "width_mm": width,
        "height_mm": height,
        "wheelbase_mm": wheelbase,

        "city_original": detail.get("city", "") or "",
        "city": detail.get("city", "") or "",
        "reg_city_original": "",
        "reg_city": "",
        "reg_date": None,

        "owners_count": 0,
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

        "vin": None,
        "spu_id": "",

        "published_at": None,
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
            "type_slug": meta.get("type_slug") or TYPE_SLUG,
            "msrp_cny": msrp_cny,
            "is_new": True,
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
    print(f"Source: {SOURCE} (type={TYPE_SLUG})")
    existing = DB.count_cars(SOURCE)
    print(f"cars[{SOURCE}] already: {existing}")

    # Fetch pending IDs and keep only ACN (newcar) ones.
    # Over-fetch since the queue may contain ACU IDs too.
    raw_ids = DB.get_pending_ids(SOURCE, args.limit * 5)
    ids = [i for i in raw_ids if is_newcar_id(i)][:args.limit]
    print(f"Loaded {len(ids)} pending newcar IDs "
          f"(filtered from {len(raw_ids)} total)\n")
    if not ids:
        print("Nothing to scrape. Run collect_autocango_new.py first.")
        return

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
    else:
        import json as _json
        import sqlite3 as _sqlite3
        try:
            _conn = _sqlite3.connect(DB.SQLITE_PATH)
            _conn.row_factory = _sqlite3.Row
            for row in _conn.execute(
                "SELECT source_id, metadata FROM pending_ids "
                "WHERE source=? AND source_id IN (" +
                ",".join("?" * len(ids)) + ")",
                [SOURCE] + ids,
            ):
                md = row["metadata"]
                metas[row["source_id"]] = (
                    _json.loads(md) if isinstance(md, str) else (md or {})
                )
            _conn.close()
        except Exception as e:
            print(f"  SQLite meta load FAIL: {e}")

    started = time.time()
    ok = fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage",
                  "--ignore-certificate-errors"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768},
                                  locale="en-US",
                                  ignore_https_errors=True)
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        # Warm the WAF cookies via the newcar listing
        warmup = ctx.new_page()
        try:
            warmup.goto("https://www.autocango.com/newcar/excludeSold=true",
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
                      f"{rec['year']} ${rec['price_original']} (new)")
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
