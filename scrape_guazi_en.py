"""en.guazi.com detail-page scraper — Playwright, parallel workers.

Each en.guazi.com detail page (/products/{slug}.html) contains:
  - Full specs in English (engine, transmission, dimensions, etc.)
  - Inspection grade (A/B/C/D/S) + inspection scores
  - Partial VIN (middle digits masked)
  - FOB price in USD (Shanghai port)
  - HD photos
  - Seller type & location

No Oxylabs proxy needed — en.guazi.com is accessible worldwide.

Usage:
    python scrape_guazi_en.py [--limit 1000] [--workers 4]
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from playwright.sync_api import sync_playwright

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi_en"
SOURCE_LANGUAGE = "en"
PRICE_CURRENCY = "USD"
KM_AGE_UNIT = "km"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

BASE_URL = "https://en.guazi.com"

PHOTO_HD_TARGET = "?x-bce-process=image/quality,q_95/resize,m_fill,w_1920,h_1280"

SLUG_RE = re.compile(
    r'^(.+?)-(\d{4})-(\d+)l-([a-z]+)-(\d+)km-(at|mt)'
    r'(?:-(2wd|4wd))?-(\d+)-seats-([a-z0-9]+)$'
)

TRANSMISSION_MAP = {
    "automatic": "Automatic", "at": "Automatic",
    "manual": "Manual", "mt": "Manual",
    "cvt": "CVT", "dct": "DCT", "amt": "AMT",
    "single-speed": "Single-Speed",
}

DRIVE_MAP = {
    "fwd": "FWD", "rwd": "RWD", "awd": "AWD", "4wd": "AWD", "2wd": "FWD",
    "front-engine fwd": "FWD", "front-engine rwd": "RWD",
    "front-engine awd": "AWD",
}

FUEL_MAP = {
    "gasoline": "Petrol", "petrol": "Petrol",
    "diesel": "Diesel",
    "electric": "Electric", "pure electric": "Electric", "bev": "Electric",
    "hybrid": "Hybrid", "phev": "PHEV",
    "plug-in hybrid": "PHEV", "plug-in": "PHEV",
    "range extender": "EREV", "erev": "EREV", "reev": "EREV",
}

COLOR_NORMALIZE = {
    "white": "White", "black": "Black", "silver": "Silver",
    "gray": "Gray", "grey": "Gray", "blue": "Blue", "red": "Red",
    "brown": "Brown", "orange": "Orange", "yellow": "Yellow",
    "green": "Green", "purple": "Purple", "gold": "Gold",
    "champagne": "Champagne", "beige": "Beige", "pink": "Pink",
}

BRAND_SLUG_TO_NAME = {
    "toyota": "Toyota", "volkswagen": "Volkswagen", "bmw": "BMW",
    "mercedes-benz": "Mercedes-Benz", "audi": "Audi", "honda": "Honda",
    "nissan": "Nissan", "hyundai": "Hyundai", "kia": "Kia",
    "byd": "BYD", "geely-auto": "Geely", "chery": "Chery",
    "haval": "Haval", "great-wall": "Great Wall", "changan": "Changan",
    "buick": "Buick", "chevrolet": "Chevrolet", "ford": "Ford",
    "cadillac": "Cadillac", "lincoln": "Lincoln",
    "mazda": "Mazda", "subaru": "Subaru", "mitsubishi": "Mitsubishi",
    "tesla": "Tesla", "nio": "NIO", "xpeng": "XPeng",
    "li-auto": "Li Auto", "zeekr": "Zeekr", "xiaomi-auto": "Xiaomi",
    "volvo": "Volvo", "lexus": "Lexus", "infiniti": "Infiniti",
    "porsche": "Porsche", "land-rover": "Land Rover", "jaguar": "Jaguar",
    "bentley": "Bentley", "rolls-royce": "Rolls-Royce",
    "maserati": "Maserati", "ferrari": "Ferrari", "lamborghini": "Lamborghini",
    "peugeot": "Peugeot", "citroen": "Citroen", "skoda": "Skoda",
    "smart": "smart", "mini": "MINI", "mg": "MG",
    "jetour": "Jetour", "tank": "Tank", "lynk-co": "Lynk & Co",
    "wey": "WEY", "hongqi": "Hongqi", "denza": "Denza",
    "voyah": "Voyah", "aion": "Aion", "ora": "ORA",
    "leapmotor": "Leapmotor", "neta": "Neta", "arcfox": "ARCFOX",
    "roewe": "Roewe", "wuling": "Wuling",
    "dongfeng": "Dongfeng", "jac": "JAC",
    "gac-trumpchi": "GAC Trumpchi", "aito": "AITO",
    "jeep": "Jeep", "genesis": "Genesis", "acura": "Acura",
    "alfa-romeo": "Alfa Romeo", "aston-martin": "Aston Martin",
    "lotus": "Lotus",
}


EXTRACT_DETAIL_JS = """() => {
    const data = {};
    const text = document.body.innerText || '';

    // Title
    const h1 = document.querySelector('h1');
    data.title = h1 ? h1.innerText.trim() : '';

    // Price
    const priceMatch = text.match(/\\$([\\d,]+)\\s*FOB/i);
    data.price_usd = priceMatch ? parseInt(priceMatch[1].replace(/,/g, ''), 10) : null;

    // Grade
    const gradeEl = document.querySelector('[class*="grade" i], [class*="Grade"]');
    if (gradeEl) {
        data.grade = (gradeEl.innerText || '').trim().replace(/^Grade\\s*/i, '');
    } else {
        const gm = text.match(/Grade\\s*([ABCDS])/i);
        data.grade = gm ? gm[1].toUpperCase() : '';
    }

    // Item number
    const itemMatch = text.match(/Item\\s*(?:No|Number)[.:]*\\s*([a-z0-9]+)/i);
    data.item_no = itemMatch ? itemMatch[1] : '';

    // VIN (partial, like LBV****8860)
    const vinMatch = text.match(/VIN[.:]*\\s*([A-Z0-9*]{10,17})/i);
    data.vin = vinMatch ? vinMatch[1] : '';

    // Specs: find all label-value pairs
    data.specs = {};
    // Try structured spec rows first
    const rows = document.querySelectorAll('tr, [class*="spec-row"], [class*="detail-item"]');
    for (const row of rows) {
        const cells = row.querySelectorAll('td, th, span, div');
        if (cells.length >= 2) {
            const label = (cells[0].innerText || '').trim().replace(/:$/, '');
            const value = (cells[1].innerText || '').trim();
            if (label && value && label.length < 50 && value.length < 200) {
                data.specs[label] = value;
            }
        }
    }

    // Fallback: parse labeled pairs from text
    const pairPatterns = [
        /Mfg\\.?\\s*(?:Year|Date)[.:]*\\s*([\\d.]+)/i,
        /1st\\s*Reg(?:istration)?[.:]*\\s*([\\d.]+)/i,
        /Mileage[.:]*\\s*([\\d,]+\\s*km)/i,
        /Body\\s*Style[.:]*\\s*(\\w[\\w\\s-]*)/i,
        /Exterior\\s*Color[.:]*\\s*([\\w\\s]+?)(?:\\s*$|\\s*\\n)/i,
        /Seats?[.:]*\\s*(\\d+)/i,
        /Doors?[.:]*\\s*(\\d+)/i,
        /Engine(?:\\s*Model)?[.:]*\\s*([\\w\\d.]+[^\\n]{0,50})/i,
        /Displacement[.:]*\\s*([\\d.]+\\s*[LT])/i,
        /Cylinder[^:]*Arrangement[.:]*\\s*(\\w+)/i,
        /Number\\s*of\\s*Cylinders?[.:]*\\s*(\\d+)/i,
        /Valves?\\s*(?:per\\s*)?(?:Cylinder)?[.:]*\\s*(\\d+)/i,
        /Valve\\s*Train[.:]*\\s*(\\w+)/i,
        /(?:Max\\s*)?Horsepower[.:]*\\s*([\\d.]+\\s*ps)/i,
        /(?:Max\\s*)?Power[.:]*\\s*([\\d.]+\\s*kW)/i,
        /(?:Max\\s*)?Power\\s*Speed[.:]*\\s*([\\d-]+\\s*rpm)/i,
        /(?:Max\\s*)?Torque[.:]*\\s*([\\d.]+\\s*N[·.]m)/i,
        /(?:Max\\s*)?Torque\\s*Speed[.:]*\\s*([\\d-]+\\s*rpm)/i,
        /Transmission[.:]*\\s*(\\w[\\w\\s()-]*)/i,
        /Drive\\s*(?:Train|Type)[.:]*\\s*([^\\n]{3,50})/i,
        /Fuel\\s*(?:Type)?[.:]*\\s*(\\w[\\w\\s-]*)/i,
        /Dimensions?[.:]*\\s*([\\d×x\\s]+mm)/i,
        /Curb\\s*Weight[.:]*\\s*([\\d,]+\\s*kg)/i,
        /Steering[.:]*\\s*(Left|Right)[^\\n]*/i,
        /(?:Current\\s*)?Location[.:]*\\s*([^\\n]+)/i,
        /Seller\\s*(?:Type)?[.:]*\\s*(Individual|Certified|Dealer)[^\\n]*/i,
        /Port[.:]*\\s*(\\w[\\w\\s]*)/i,
        // EV / battery fields
        /Battery\\s*Capacity[.:]*\\s*([\\d.]+\\s*kWh)/i,
        /(?:EV\\s*)?Range\\s*\\(?(?:NEDC|CLTC|WLTP)?\\)?[.:]*\\s*([\\d,]+\\s*km)/i,
        /Energy\\s*Consumption[.:]*\\s*([\\d.]+\\s*kWh\\/100km)/i,
        /(?:WLTC|NEDC)?\\s*(?:Combined\\s*)?Fuel\\s*Consumption[.:]*\\s*([\\d.]+\\s*L\\/100km)/i,
        /Total\\s*Motor\\s*Power[.:]*\\s*([\\d.]+\\s*kW)/i,
        /Total\\s*Motor\\s*Torque[.:]*\\s*([\\d.]+\\s*N[·.]m)/i,
        /(?:Front|Rear)\\s*Motor\\s*(?:Max\\s*)?Power[.:]*\\s*([\\d.]+\\s*kW)/i,
        /(?:Front|Rear)\\s*Motor\\s*(?:Max\\s*)?Torque[.:]*\\s*([\\d.]+\\s*N[·.]m)/i,
        /(?:Slow|AC)\\s*Charg(?:ing|e)\\s*Time[.:]*\\s*([\\d.]+\\s*h)/i,
        /(?:Fast|DC)\\s*Charg(?:ing|e)\\s*Time[.:]*\\s*([\\d.]+\\s*(?:h|min))/i,
    ];
    const labels = [
        'mfg_date', 'reg_date', 'mileage', 'body_style', 'color',
        'seats', 'doors', 'engine_model', 'displacement', 'cylinder_arrangement',
        'num_cylinders', 'valves_per_cylinder', 'valve_train',
        'horsepower', 'max_power_kw', 'power_rpm',
        'torque', 'torque_rpm',
        'transmission', 'drive_type', 'fuel_type',
        'dimensions', 'curb_weight', 'steering', 'location',
        'seller_type', 'port',
        'battery_capacity', 'ev_range', 'energy_consumption',
        'fuel_consumption', 'total_motor_power', 'total_motor_torque',
        'rear_motor_power', 'rear_motor_torque',
        'slow_charge_time', 'fast_charge_time',
    ];
    for (let i = 0; i < pairPatterns.length; i++) {
        const m = text.match(pairPatterns[i]);
        if (m && !data.specs[labels[i]]) {
            data.specs[labels[i]] = m[1].trim();
        }
    }

    // Front motor (separate from rear)
    const fmPower = text.match(/Front\\s*Motor\\s*(?:Max\\s*)?Power[.:]*\\s*([\\d.]+\\s*kW)/i);
    const fmTorque = text.match(/Front\\s*Motor\\s*(?:Max\\s*)?Torque[.:]*\\s*([\\d.]+\\s*N[·.]m)/i);
    if (fmPower) data.specs['front_motor_power'] = fmPower[1].trim();
    if (fmTorque) data.specs['front_motor_torque'] = fmTorque[1].trim();

    // Inspection scores (with denominators)
    data.inspection = {};
    const inspPairs = [
        /Exterior\\s*(?:Design)?[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
        /Interior\\s*(?:Trim)?[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
        /Configuration\\s*(?:Features)?[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
        /Structural\\s*(?:Components)?[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
        /Reinforcement\\s*(?:Parts)?[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
        /Cockpit\\s*(?:Conditions)?[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
        /New\\s*Energy[.:]*\\s*(\\d+)(?:[/\\\\](\\d+))?/i,
    ];
    const inspLabels = [
        'exterior', 'interior', 'configuration',
        'structural', 'reinforcement', 'cockpit',
        'new_energy',
    ];
    for (let i = 0; i < inspPairs.length; i++) {
        const m = text.match(inspPairs[i]);
        if (m) {
            data.inspection[inspLabels[i]] = parseInt(m[1], 10);
            if (m[2]) data.inspection[inspLabels[i] + '_total'] = parseInt(m[2], 10);
        }
    }

    // Damage flags
    data.no_accident = text.includes('No Accident');
    data.no_water = text.includes('No Water');
    data.no_fire = text.includes('No Fire');

    // Photos
    data.photos = [];
    const imgs = document.querySelectorAll('img[src*="guazi"], img[src*="image-public"]');
    const seenUrls = new Set();
    for (const img of imgs) {
        const src = img.src || img.getAttribute('data-src') || '';
        if (!src || seenUrls.has(src)) continue;
        // Skip tiny UI icons
        if (src.includes('icon') || src.includes('logo') || src.includes('flag')) continue;
        const w = img.naturalWidth || img.width || 0;
        if (w > 0 && w < 50) continue;
        seenUrls.add(src);
        data.photos.push(src);
    }

    // Features list
    data.features = [];
    const featureEls = document.querySelectorAll(
        '[class*="feature"] li, [class*="config"] li, [class*="equipment"] span'
    );
    for (const el of featureEls) {
        const t = (el.innerText || '').trim();
        if (t && t.length < 100) data.features.push(t);
    }

    return data;
}"""


def upgrade_photo(url: str) -> str:
    if "guazistatic.com" in url:
        base = url.split("?")[0]
        return base + PHOTO_HD_TARGET
    return url


def tr(value: str, mapping: dict) -> str:
    if not value:
        return ""
    v = value.strip().lower()
    return mapping.get(v, value.strip())


def parse_slug(slug: str) -> dict | None:
    m = SLUG_RE.match(slug)
    if not m:
        return None
    brand_series, year, disp, color, km, trans, drive, seats, item_id = m.groups()
    return {
        "brand_series_slug": brand_series,
        "year": int(year),
        "displacement_dl": int(disp),
        "color": color,
        "mileage_km": int(km),
        "transmission_slug": trans,
        "drive_slug": drive,
        "seats": int(seats),
        "item_id": item_id,
    }


def parse_int(s: str | None) -> int | None:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def parse_float(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"[\d.]+", str(s))
    return float(m.group()) if m else None


def parse_dimensions(s: str | None) -> tuple[int | None, int | None, int | None]:
    if not s:
        return None, None, None
    nums = re.findall(r"\d+", s)
    if len(nums) >= 3:
        return int(nums[0]), int(nums[1]), int(nums[2])
    return None, None, None


def extract_brand_series(title: str, slug_brand_series: str) -> tuple[str, str, str]:
    """Extract brand and series/model from the English title."""
    title = re.sub(r"^Used\s+", "", title, flags=re.IGNORECASE).strip()

    # Try matching known brand prefixes (longest first)
    sorted_brands = sorted(BRAND_SLUG_TO_NAME.values(), key=len, reverse=True)
    brand = ""
    rest = title
    for b in sorted_brands:
        if title.upper().startswith(b.upper()):
            brand = b
            rest = title[len(b):].strip()
            break

    if not brand:
        # Fallback: first word of slug
        first_slug = slug_brand_series.split("-")[0]
        brand = BRAND_SLUG_TO_NAME.get(first_slug, first_slug.title())
        rest = title

    # Series is usually the next segment before the year
    year_m = re.search(r"\b(19|20)\d{2}\b", rest)
    if year_m:
        series = rest[:year_m.start()].strip()
        complectation = rest[year_m.end():].strip()
    else:
        parts = rest.split(" ", 1)
        series = parts[0] if parts else ""
        complectation = parts[1] if len(parts) > 1 else ""

    return brand, series, complectation


def build_record(detail: dict, meta: dict, item_id: str) -> dict | None:
    slug = meta.get("slug", "")
    parsed = parse_slug(slug) if slug else None

    title = detail.get("title") or meta.get("title", "")
    if not title:
        return None

    specs = detail.get("specs", {})

    # Brand / series / complectation
    slug_brand_series = parsed["brand_series_slug"] if parsed else ""
    brand, series, complectation = extract_brand_series(title, slug_brand_series)

    # Year + manufacturing date
    mfg_raw = specs.get("mfg_date", "")
    mfg_date = None
    year = None
    if mfg_raw:
        mfg_m = re.match(r"(\d{4})\.(\d{1,2})", mfg_raw)
        if mfg_m:
            mfg_date = f"{mfg_m.group(1)}-{int(mfg_m.group(2)):02d}-01"
            year = int(mfg_m.group(1))
    if not year:
        year = parsed["year"] if parsed else None
    if not year:
        year = meta.get("year")

    # Registration date
    reg_raw = specs.get("reg_date", "")
    reg_date = None
    if reg_raw:
        reg_m = re.match(r"(\d{4})\.(\d{1,2})", reg_raw)
        if reg_m:
            reg_date = f"{reg_m.group(1)}-{int(reg_m.group(2)):02d}-01"

    # Mileage
    mileage_km = parse_int(specs.get("mileage"))
    if not mileage_km and parsed:
        mileage_km = parsed["mileage_km"]
    if not mileage_km:
        mileage_km = meta.get("mileage_km")

    # Price
    price_usd = detail.get("price_usd") or meta.get("price_usd")

    # Color
    color_raw = specs.get("color", "")
    if not color_raw and parsed:
        color_raw = parsed["color"]
    color = tr(color_raw, COLOR_NORMALIZE) or color_raw.capitalize()

    # Displacement
    disp_raw = specs.get("displacement", "")
    displacement_l = parse_float(disp_raw)
    if not displacement_l and parsed:
        dl = parsed["displacement_dl"]
        displacement_l = dl / 10.0 if dl > 0 else None
    if displacement_l == 0:
        displacement_l = None

    # Transmission
    trans_raw = specs.get("transmission", "")
    trans_type = tr(trans_raw, TRANSMISSION_MAP)
    if not trans_type and parsed:
        trans_type = "Automatic" if parsed["transmission_slug"] == "at" else "Manual"

    # Drive type
    drive_raw = specs.get("drive_type", "")
    drive_type = tr(drive_raw, DRIVE_MAP)
    if not drive_type and parsed and parsed["drive_slug"]:
        drive_type = "AWD" if parsed["drive_slug"] == "4wd" else "FWD"

    # Fuel type
    fuel_raw = specs.get("fuel_type", "")
    engine_type = tr(fuel_raw, FUEL_MAP)

    # Horsepower
    hp = parse_int(specs.get("horsepower"))

    # Body type
    body_type = specs.get("body_style", "")

    # Dimensions
    dim_raw = specs.get("dimensions", "")
    length_mm, width_mm, height_mm = parse_dimensions(dim_raw)

    # Weight
    curb_weight = parse_int(specs.get("curb_weight"))

    # VIN (partial)
    vin = detail.get("vin") or None
    if vin and len(vin) < 8:
        vin = None

    # Inspection
    grade = detail.get("grade", "") or meta.get("grade", "")
    inspection = detail.get("inspection", {})
    if grade:
        inspection["grade"] = grade

    # Accident record
    has_accident = 0 if detail.get("no_accident") else None

    # Photos
    raw_photos = detail.get("photos", [])
    photos = [upgrade_photo(p) for p in raw_photos if "guazi" in p or "image" in p]
    # Deduplicate keeping order
    seen_photos: set[str] = set()
    unique_photos: list[str] = []
    for p in photos:
        base = p.split("?")[0]
        if base not in seen_photos:
            seen_photos.add(base)
            unique_photos.append(p)

    # Seller info
    seller_type = specs.get("seller_type", "") or meta.get("seller_type", "")
    location = specs.get("location", "")
    city = ""
    if location:
        # "Shanghai, China" → "Shanghai"
        city = location.split(",")[0].strip()

    # EV / battery — parse numeric values for dedicated columns
    battery_kwh = parse_float(specs.get("battery_capacity"))
    ev_range_km = parse_int(specs.get("ev_range"))
    energy_cons = parse_float(specs.get("energy_consumption"))
    total_motor_kw = parse_float(specs.get("total_motor_power"))
    total_motor_torque = parse_float(specs.get("total_motor_torque"))
    front_motor_kw = parse_float(specs.get("front_motor_power"))
    front_motor_torque = parse_float(specs.get("front_motor_torque"))
    rear_motor_kw = parse_float(specs.get("rear_motor_power"))
    rear_motor_torque = parse_float(specs.get("rear_motor_torque"))

    # Engine power in kW (ICE or single-motor EV)
    engine_kw = parse_float(specs.get("max_power_kw"))
    # motor_power_kw = total motor power for multi-motor EV, else engine kW
    motor_kw = total_motor_kw or (engine_kw if engine_type == "Electric" else None)
    engine_power_kw = engine_kw if engine_type != "Electric" else None

    # Torque
    torque = parse_float(specs.get("torque"))

    # Fuel consumption (ICE)
    fuel_cons = parse_float(specs.get("fuel_consumption"))

    # Inspection score — sum all inspection sub-scores
    insp_vals = [v for k, v in inspection.items()
                 if isinstance(v, (int, float)) and not k.endswith("_total")
                 and k != "grade"]
    inspection_score = sum(insp_vals) if insp_vals else None

    # Source data — only fields that don't have their own column
    source_data: dict[str, Any] = {
        "features": detail.get("features") or None,
        "item_id": item_id,
    }
    source_data = {k: v for k, v in source_data.items() if v is not None}

    detail_url = meta.get("url") or f"{BASE_URL}/products/{slug}.html"

    ts = DB.now_iso()
    return {
        "source": SOURCE,
        "source_id": item_id,
        "source_language": SOURCE_LANGUAGE,
        "url": detail_url,
        "title": title,

        "mark_original": None,
        "mark": brand or None,
        "series_original": None,
        "model": series or None,
        "complectation": complectation or None,
        "year": year,
        "reg_date": reg_date,
        "mfg_date": mfg_date,

        "price_original": price_usd,
        "price_currency": PRICE_CURRENCY,

        "km_age_original": mileage_km,
        "km_age_unit": KM_AGE_UNIT,
        "km_age": mileage_km,

        "color_original": color_raw or None,
        "color": color or None,
        "body_type": body_type or None,
        "engine_type": engine_type or None,
        "fuel_original": fuel_raw or None,
        "transmission_original": trans_raw or None,
        "transmission_type": trans_type or None,
        "drive_type": drive_type or None,
        "drive_original": drive_raw or None,
        "displacement": displacement_l,
        "horse_power": hp,

        # Engine details (new columns)
        "engine_model": specs.get("engine_model") or None,
        "engine_power_kw": engine_power_kw,
        "num_cylinders": parse_int(specs.get("num_cylinders")),
        "cylinder_arrangement": specs.get("cylinder_arrangement") or None,
        "valves_per_cylinder": parse_int(specs.get("valves_per_cylinder")),
        "valve_train": specs.get("valve_train") or None,
        "torque_nm": torque,
        "power_rpm": specs.get("power_rpm") or None,
        "torque_rpm": specs.get("torque_rpm") or None,
        "fuel_consumption": fuel_cons,

        # EV / battery (new + existing columns)
        "battery_kwh": battery_kwh,
        "ev_range_km": ev_range_km,
        "energy_consumption": energy_cons,
        "motor_power_kw": motor_kw,
        "total_motor_torque_nm": total_motor_torque,
        "front_motor_power_kw": front_motor_kw,
        "front_motor_torque_nm": front_motor_torque,
        "rear_motor_power_kw": rear_motor_kw,
        "rear_motor_torque_nm": rear_motor_torque,
        "charge_time_fast": specs.get("fast_charge_time") or None,
        "charge_time_slow": specs.get("slow_charge_time") or None,

        # Body / dimensions
        "length_mm": length_mm,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "curb_weight_kg": curb_weight,
        "doors": parse_int(specs.get("doors")),
        "seats": parsed["seats"] if parsed else None,

        # Location / logistics
        "city_original": None,
        "city": city or None,
        "port": specs.get("port") or None,
        "steering": specs.get("steering") or None,

        # Condition / inspection
        "vin": vin,
        "accident_free": True if detail.get("no_accident") else None,
        "no_water_damage": True if detail.get("no_water") else None,
        "no_fire_damage": True if detail.get("no_fire") else None,
        "inspection_grade": grade or None,
        "inspection_score": inspection_score,
        "inspection_data": inspection if inspection else None,

        "images": unique_photos,
        "image_count": len(unique_photos),

        "seller_type": seller_type or None,

        "source_data": source_data,
        "first_seen": ts,
        "last_seen": ts,
    }


class WorkerCtx:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.ctx = None
        self.page = None

    def __enter__(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self.ctx = self.browser.new_context(
            user_agent=UA, locale="en-US", ignore_https_errors=True,
            viewport={"width": 1366, "height": 900},
        )
        self.ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        self.page = self.ctx.new_page()
        return self.page

    def __exit__(self, *_):
        try:
            self.browser.close()
        finally:
            self.pw.stop()


def fetch_detail(url: str, page=None) -> dict | None:
    if page is None:
        with WorkerCtx() as p:
            return fetch_detail(url, p)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1500)

        # Scroll to load lazy content
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)

        html = page.content()
        if len(html) < 3000:
            return None
        if "captcha" in page.url.lower():
            return None

        detail = page.evaluate(EXTRACT_DETAIL_JS)
        return detail
    except Exception:
        return None


def fetch_pending_rows(limit: int) -> list[dict]:
    r = DB._pg_request(
        "GET",
        f"pending_ids?source=eq.{SOURCE}"
        f"&failed_attempts=lt.{DB.QUARANTINE_THRESHOLD}"
        f"&select=source_id,metadata&limit={limit * 3}",
    )
    if r.status_code != 200:
        return []
    pending = r.json()
    r2 = DB._pg_request("GET", f"cars?source=eq.{SOURCE}&select=source_id")
    scraped = {row["source_id"] for row in r2.json()} if r2.status_code == 200 else set()
    return [p for p in pending if str(p["source_id"]) not in scraped][:limit]


def scrape_batch(rows: list[dict]) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    fail_streak = 0
    ctx = WorkerCtx()
    page = ctx.__enter__()
    try:
        for row in rows:
            item_id = row["source_id"]
            meta = row.get("metadata") or {}
            url = meta.get("url") or f"{BASE_URL}/products/{meta.get('slug', item_id)}.html"

            detail = fetch_detail(url, page)
            if not detail:
                fail_streak += 1
                results.append((item_id, False, "fetch failed"))
                if fail_streak >= 3:
                    ctx.__exit__(None, None, None)
                    ctx = WorkerCtx()
                    page = ctx.__enter__()
                    fail_streak = 0
                continue
            fail_streak = 0

            rec = build_record(detail, meta, item_id)
            if not rec:
                results.append((item_id, False, "parse failed"))
                continue
            ok = DB.upsert_car(rec)
            results.append((item_id, ok, ""))
    finally:
        ctx.__exit__(None, None, None)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    run_id = DB.sync_log_start(SOURCE, os.environ.get("GITHUB_RUN_URL"))
    ok_count = 0
    fail_count = 0
    error_message: str | None = None
    try:
        pending = fetch_pending_rows(args.limit)
        if not pending:
            print("No pending IDs")
            return
        print(f"Scraping {len(pending)} en.guazi.com detail pages "
              f"with {args.workers} workers (batches of ~15)")

        BATCH_SIZE = 15
        batches = [pending[i:i+BATCH_SIZE]
                   for i in range(0, len(pending), BATCH_SIZE)]

        started = time.time()
        processed = 0

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(scrape_batch, b): b for b in batches}
            for fut in as_completed(futs):
                try:
                    results = fut.result()
                except Exception:
                    traceback.print_exc()
                    fail_count += len(futs[fut])
                    continue
                for cid, ok, err in results:
                    processed += 1
                    if ok:
                        ok_count += 1
                    else:
                        DB.mark_failed(SOURCE, cid)
                        fail_count += 1
                elapsed = int(time.time() - started)
                print(f"  batch done: {processed}/{len(pending)} "
                      f"(ok={ok_count}, fail={fail_count}, {elapsed}s)")

        elapsed = int(time.time() - started)
        print(f"\nDone in {elapsed}s. OK: {ok_count}, FAIL: {fail_count}")
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        raise
    finally:
        DB.sync_log_finish(run_id, added=ok_count, failed=fail_count,
                           error_message=error_message)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
