"""
Encar.com card scraper — DIRECT HTTP (no Oxylabs).

Tests confirmed api.encar.com is reachable from any IP without proxy.
For each pending ID, calls:
    GET https://api.encar.com/v1/readside/vehicles
        ?vehicleIds=ID1,ID2,ID3,ID4,ID5
        &include=SPEC,ADVERTISEMENT,PHOTOS,CATEGORY,MANAGE,CONTACT,VIEW,
                 OPTIONS,CONDITION,PARTNERSHIP,CONTENTS,VEHICLETYPE

Returns JSON list of 5 cars with full detail (VIN, options, photos, etc).
Cost: $0 per request (direct HTTP, no proxy).

Usage:
    python scrape_encar.py --limit 500 --workers 5

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

SOURCE = "encar"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    "Referer": "https://fem.encar.com/",
}

SOURCE_LANGUAGE = "ko"
PRICE_CURRENCY = "KRW"
KM_AGE_UNIT = "km"
IMAGE_BASE = "https://ci.encar.com"
# Encar serves Full HD when we append this impolicy. Without it photos are 640×360.
IMAGE_HD_QS = "?impolicy=heightRate&rh=1080&cw=1920&ch=1080&cg=Center"
CARD_URL_TPL = "https://fem.encar.com/cars/detail/{id}"

API_URL = "https://api.encar.com/v1/readside/vehicles"
INCLUDES = (
    "SPEC,ADVERTISEMENT,PHOTOS,CATEGORY,MANAGE,CONTACT,VIEW,"
    "OPTIONS,CONDITION,PARTNERSHIP,CONTENTS,VEHICLETYPE"
)
BATCH_SIZE = 5  # API supports up to 5 IDs per request


# ---------- Korean → Latin maps ----------

COLOR_MAP = {
    "흰색": "White", "검정색": "Black", "검은색": "Black", "회색": "Gray",
    "은색": "Silver", "쥐색": "Gray", "진주색": "Pearl", "진주": "Pearl",
    "파랑색": "Blue", "파랑": "Blue", "남색": "Navy", "하늘색": "Light Blue",
    "빨강색": "Red", "빨강": "Red", "주황색": "Orange", "주황": "Orange",
    "노랑색": "Yellow", "노랑": "Yellow", "녹색": "Green", "초록색": "Green",
    "갈색": "Brown", "고동색": "Dark Brown", "베이지": "Beige",
    "와인색": "Wine", "보라색": "Purple", "분홍색": "Pink",
    "금색": "Gold", "기타": "Other",
    # Variants seen in live encar data
    "청색": "Blue", "은회색": "Silver", "빨간색": "Red",
    "담녹색": "Green", "노란색": "Yellow", "연금색": "Gold",
    "명은색": "Silver", "진주투톤": "Pearl Two-Tone", "은하색": "Silver",
    "청옥색": "Blue", "연두색": "Green", "갈대색": "Beige",
}

FUEL_MAP = {
    "가솔린": "Petrol", "디젤": "Diesel", "LPG": "LPG", "가스": "LPG",
    "전기": "Electric", "수소": "Hydrogen",
    "하이브리드": "Hybrid", "가솔린+하이브리드": "Hybrid",
    "디젤+하이브리드": "Hybrid", "LPG+하이브리드": "Hybrid",
    "가솔린+전기": "PHEV", "디젤+전기": "PHEV",
    # Variants
    "LPG(일반인 구입)": "LPG", "가솔린+LPG": "Petrol + LPG",
}

TRANSMISSION_MAP = {
    "오토": "Automatic", "자동": "Automatic", "수동": "Manual",
    "세미오토": "Semi-Auto", "무단변속기": "CVT", "CVT": "CVT",
    "듀얼클러치": "DCT", "DCT": "DCT",
}

BODY_MAP = {
    "경차": "Sedan", "소형차": "Sedan", "준중형차": "Sedan",
    "중형차": "Sedan", "준대형차": "Sedan", "대형차": "Sedan",
    "스포츠카": "Sports Car", "쿠페": "Coupe", "컨버터블": "Convertible",
    "왜건": "Wagon", "해치백": "Hatchback",
    "SUV": "SUV", "RV": "SUV",
    "미니밴": "Minivan", "승합차": "Minivan", "밴": "Minivan",
    "픽업트럭": "Pickup", "트럭": "Truck", "버스": "Bus",
    # Variants
    "화물차": "Truck", "경승합차": "Mini Van",
}

# Korean province codes (first word of contact.address)
REGION_MAP = {
    "서울": "Seoul", "부산": "Busan", "대구": "Daegu", "인천": "Incheon",
    "광주": "Gwangju", "대전": "Daejeon", "울산": "Ulsan", "세종": "Sejong",
    "경기": "Gyeonggi", "강원": "Gangwon",
    "충북": "Chungbuk", "충남": "Chungnam",
    "전북": "Jeonbuk", "전남": "Jeonnam",
    "경북": "Gyeongbuk", "경남": "Gyeongnam", "제주": "Jeju",
}


def tr(value: str, mapping: dict) -> str:
    if not value:
        return ""
    return mapping.get(value.strip(), value.strip())


# ---------- API fetch ----------

def fetch_batch(ids: list[str]) -> list[dict] | None:
    """Fetch up to 5 cars via direct HTTP. Returns list of car dicts or None."""
    url = f"{API_URL}?vehicleIds={','.join(ids)}&include={INCLUDES}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        content = r.json()
        if isinstance(content, list):
            return content
        return None
    except Exception:
        return None


# ---------- Parse one car ----------

def _format_reg_date(year_month: str) -> str | None:
    if not year_month or len(year_month) < 6:
        return None
    try:
        return f"{year_month[:4]}-{year_month[4:6]}-01"
    except Exception:
        return None


def parse_car(api_car: dict) -> dict | None:
    """Map encar API response to our cars schema."""
    try:
        manage = api_car.get("manage") or {}
        category = api_car.get("category") or {}
        advertisement = api_car.get("advertisement") or {}
        contact = api_car.get("contact") or {}
        spec = api_car.get("spec") or {}
        photos = api_car.get("photos") or []
        options = api_car.get("options") or {}
        condition = api_car.get("condition") or {}
        partnership = api_car.get("partnership") or {}
        contents = api_car.get("contents") or {}

        source_id = str(manage.get("dummyVehicleId")
                        or api_car.get("vehicleId") or "")
        if not source_id:
            return None

        year_month = category.get("yearMonth", "")
        year = int(year_month[:4]) if year_month[:4].isdigit() else None

        price_wan = advertisement.get("price")
        new_price_wan = category.get("originPrice")
        new_price = (new_price_wan * 10000
                     if isinstance(new_price_wan, (int, float)) else None)
        # encar uses 99999 (만원) as "협의/문의" placeholder. Below 150만원
        # ($108) AND/OR used < 5% of new = auction down-payments / wholesale
        # leftovers, not real consumer prices.
        price = None
        if isinstance(price_wan, (int, float)) and 150 <= price_wan < 99999:
            if (new_price_wan and isinstance(new_price_wan, (int, float))
                    and new_price_wan > 0
                    and price_wan < new_price_wan * 0.05):
                price = None
            else:
                price = price_wan * 10000

        mileage = spec.get("mileage")

        color_kr = spec.get("colorName", "") or ""
        fuel_kr = spec.get("fuelName", "") or ""
        trans_kr = spec.get("transmissionName", "") or ""
        body_kr = spec.get("bodyName", "") or ""

        address = contact.get("address", "") or ""
        region_kr = address.split(" ")[0] if address else ""

        image_urls = [f"{IMAGE_BASE}{p['path']}{IMAGE_HD_QS}" for p in photos
                      if isinstance(p, dict) and p.get("path")]

        dealer = partnership.get("dealer") or {}
        firm = dealer.get("firm") or {}

        mark_orig = category.get("manufacturerName", "")
        mark_en = category.get("manufacturerEnglishName") or mark_orig
        # encar concatenates historical legal-entity names ("ChevroletGMDaewoo",
        # "Renault-KoreaSamsung", "KG_Mobility_Ssangyong", "Citroen-DS").
        # Normalize to the current consumer-facing brand.
        ENCAR_BRAND_ALIASES = {
            "ChevroletGMDaewoo": "Chevrolet",
            "Renault-KoreaSamsung": "Renault Korea",
            "KG_Mobility_Ssangyong": "KG Mobility",
            "Citroen-DS": "Citroen",
        }
        mark_en = ENCAR_BRAND_ALIASES.get(mark_en, mark_en)
        model_group_en = category.get("modelGroupEnglishName", "")
        grade_en = category.get("gradeEnglishName", "")

        # Korean→global model aliases
        ENCAR_MODEL_ALIASES = {
            "avante": "Elantra", "canival": "Carnival", "morning": "Picanto",
            "santafe": "Santa Fe", "grandeur": "Azera", "starex": "H-1",
            "mohave": "Borrego", "qm6": "Koleos",
        }
        model_clean = ENCAR_MODEL_ALIASES.get(model_group_en.lower(), model_group_en)
        complectation_str = grade_en or category.get("gradeName", "")

        ts = DB.now_iso()

        return {
            "source": SOURCE,
            "source_id": source_id,
            "source_language": SOURCE_LANGUAGE,
            "url": CARD_URL_TPL.format(id=source_id),
            "title": " ".join(x for x in (mark_en, model_clean, complectation_str) if x).strip(),

            "mark_original": mark_orig,
            "mark": mark_en,
            "series_original": model_group_en or category.get("modelName", ""),
            "model": model_clean or model_group_en or category.get("modelName", ""),
            "complectation": complectation_str,
            "year": year,

            "price_original": price,
            "price_currency": PRICE_CURRENCY,
            "new_price_original": new_price,
            "new_price_currency": PRICE_CURRENCY if new_price else None,

            "km_age_original": mileage,
            "km_age_unit": KM_AGE_UNIT,
            "km_age": mileage,

            "color_original": color_kr,
            "color": tr(color_kr, COLOR_MAP),

            "body_type": tr(body_kr, BODY_MAP),
            "engine_type": tr(fuel_kr, FUEL_MAP),
            "fuel_original": fuel_kr,
            "transmission_original": trans_kr,
            "transmission_type": tr(trans_kr, TRANSMISSION_MAP),
            "drive_original": "",
            "drive_type": "",

            "displacement": (spec["displacement"] / 1000
                             if spec.get("displacement") else None),
            "horse_power": None,
            "acceleration_time": "",

            "length_mm": None, "width_mm": None,
            "height_mm": None, "wheelbase_mm": None,

            "city_original": region_kr,
            "city": tr(region_kr, REGION_MAP),
            "reg_city_original": "",
            "reg_city": "",
            "reg_date": _format_reg_date(year_month),

            "owners_count": None,
            "has_accident_record": (condition.get("accident") or {}).get("recordView"),
            "maintenance": "",
            "interior_color_original": "",
            "description": contents.get("text", "") or "",

            "images": image_urls,
            "image_count": len(image_urls),

            "seller_type": ("Dealer" if contact.get("userType") == "DEALER"
                            else "Private"),
            "shop_name": firm.get("name", "") or "",
            "shop_short_name": dealer.get("name", "") or "",
            "shop_address": address,
            "shop_id": contact.get("userId", "") or "",
            "shop_cars_count": None,
            "sales_range": "",

            "vin": api_car.get("vin"),
            "spu_id": "",

            "published_at": manage.get("firstAdvertisedDateTime"),
            "listing_updated_at": manage.get("modifyDateTime"),

            "source_data": {
                "vehicle_no": api_car.get("vehicleNo"),
                "vehicle_id": api_car.get("vehicleId"),
                "year_month": year_month,
                "import_type": category.get("importType"),
                "domestic": category.get("domestic"),
                "warranty": category.get("warranty"),
                "trust": advertisement.get("trust"),
                "diagnosis_car": advertisement.get("diagnosisCar"),
                "accident": condition.get("accident"),
                "inspection_formats": (condition.get("inspection") or {}).get("formats"),
                "seizing": condition.get("seizing"),
                "option_codes_standard": options.get("standard", []),
                "option_codes_etc": options.get("etc", []),
                "option_codes_choice": options.get("choice", []),
                "option_codes_tuning": options.get("tuning", []),
                "dealer_phone": contact.get("no"),
                "dealer_firm_code": firm.get("code"),
                "dealer_diagnosis_centers": firm.get("diagnosisCenters"),
                "view_count": manage.get("viewCount"),
                "subscribe_count": manage.get("subscribeCount"),
                "regist_datetime": manage.get("registDateTime"),
                "first_advertised_datetime": manage.get("firstAdvertisedDateTime"),
                "modify_datetime": manage.get("modifyDateTime"),
            },

            "first_seen": ts,
            "last_seen": ts,
        }
    except Exception as e:
        print(f"  parse error: {e}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE}, batch_size={BATCH_SIZE}, workers={args.workers}")
    existing = DB.count_cars(SOURCE)
    print(f"cars[{SOURCE}] already: {existing}")

    ids = DB.get_pending_ids(SOURCE, args.limit)
    print(f"Loaded {len(ids)} pending IDs for [{SOURCE}]")
    if not ids:
        print("Nothing to scrape. Run collect_encar.py first.")
        return

    batches = [ids[i:i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]
    print(f"\nProcessing {len(batches)} batches of up to {BATCH_SIZE}…\n")

    ok = fail = 0
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_batch, b): b for b in batches}
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                cars = fut.result()
            except Exception as e:
                cars = None
                print(f"  batch {batch} EXCEPTION: {e}")

            if not cars:
                for cid in batch:
                    DB.mark_failed(SOURCE, cid)
                    fail += 1
                print(f"  batch {batch} FAIL (+{len(batch)} attempts)")
                continue

            returned_ids: set[str] = set()
            for car in cars:
                rec = parse_car(car)
                if not rec:
                    continue
                returned_ids.add(rec["source_id"])
                if DB.upsert_car(rec):
                    ok += 1
                    vin = rec.get("vin") or "—"
                    print(f"  OK {rec['source_id']} {rec['mark']} {rec['model'][:30]} "
                          f"{rec['year']} {rec['price_original']} KRW  VIN:{vin}")
                else:
                    DB.mark_failed(SOURCE, rec["source_id"])
                    fail += 1

            for cid in batch:
                if cid not in returned_ids:
                    DB.mark_failed(SOURCE, cid)
                    fail += 1

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. OK: {ok}, FAIL: {fail}")
    print(f"Total in cars[{SOURCE}]: {DB.count_cars(SOURCE)}")


if __name__ == "__main__":
    main()
