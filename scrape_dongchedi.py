"""
Dongchedi.com used car scraper via Oxylabs Realtime API.

Parses individual cards (full data) by sku_id, writes to unified schema
in Postgres (Supabase) or SQLite (local fallback).

Schema notes (multi-source compatible):
  - *_original  : value in source language (used to be *_cn)
  - price_original + price_currency : NO conversion, frontend does it via live FX
  - km_age_original + km_age_unit + km_age (normalized km for cross-market filters)
  - source_language : 'zh' / 'ko' / 'ja' / ...
  - source_data JSONB : source-specific fields (inspection report etc.)

Usage:
    python scrape_dongchedi.py --skip-listing --limit 1000 --workers 5

Env vars:
    OXY_USER, OXY_PASS — Oxylabs credentials (required)
    SUPABASE_URL, SUPABASE_KEY — if set, writes to Postgres; otherwise to cars.db
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

SOURCE = "dongchedi"
SOURCE_LANGUAGE = "zh"
PRICE_CURRENCY = "CNY"
KM_AGE_UNIT = "km"

CARD_URL = "https://www.dongchedi.com/usedcar/{id}"
MAX_RETRIES = 3


# ---------- Oxylabs ----------

def oxylabs_fetch(url: str, render: bool = True) -> str | None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS environment variables")
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
    }
    if render:
        payload["render"] = "html"

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(
                OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=180,
            )
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} on {url} (attempt {attempt+1})")
                time.sleep(2 ** attempt)
                continue
            data = r.json()
            results = data.get("results", [])
            if not results:
                return None
            content = results[0].get("content")
            if not content or len(content) < 1000:
                time.sleep(2 ** attempt)
                continue
            return content
        except Exception as e:
            print(f"  exception on {url}: {e}")
            time.sleep(2 ** attempt)
    return None


# ---------- HTML parsing ----------

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def extract_next_data(html: str) -> dict | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ---------- Translation maps (shared across future parsers) ----------

BRAND_MAP = {
    "奔驰": "Mercedes-Benz", "宝马": "BMW", "奥迪": "Audi", "大众": "Volkswagen",
    "丰田": "Toyota", "本田": "Honda", "日产": "Nissan", "马自达": "Mazda",
    "雷克萨斯": "Lexus", "英菲尼迪": "Infiniti", "讴歌": "Acura",
    "福特": "Ford", "雪佛兰": "Chevrolet", "凯迪拉克": "Cadillac", "别克": "Buick",
    "特斯拉": "Tesla", "比亚迪": "BYD", "吉利": "Geely", "吉利汽车": "Geely",
    "长城": "Great Wall", "长安": "Changan", "奇瑞": "Chery", "哈弗": "Haval",
    "红旗": "Hongqi", "蔚来": "NIO", "小鹏": "XPeng", "小鹏汽车": "XPeng",
    "理想": "Li Auto", "理想汽车": "Li Auto", "零跑": "Leapmotor",
    "零跑汽车": "Leapmotor", "小米": "Xiaomi", "小米汽车": "Xiaomi",
    "AITO": "AITO", "问界": "AITO", "极氪": "Zeekr", "捷豹": "Jaguar",
    "路虎": "Land Rover", "保时捷": "Porsche", "玛莎拉蒂": "Maserati",
    "法拉利": "Ferrari", "兰博基尼": "Lamborghini", "宾利": "Bentley",
    "劳斯莱斯": "Rolls-Royce", "沃尔沃": "Volvo", "现代": "Hyundai", "起亚": "Kia",
    "标致": "Peugeot", "雪铁龙": "Citroen", "雷诺": "Renault", "斯柯达": "Skoda",
    "斯巴鲁": "Subaru", "三菱": "Mitsubishi", "铃木": "Suzuki",
    "smart": "smart", "MINI": "MINI", "MG": "MG", "名爵": "MG",
    "上汽大众": "SAIC Volkswagen", "上汽通用五菱": "Wuling", "五菱": "Wuling",
    "五菱汽车": "Wuling", "广汽传祺": "GAC Trumpchi", "传祺": "GAC Trumpchi",
    "坦克": "Tank", "腾势": "Denza", "仰望": "YangWang",
    "领克": "Lynk & Co", "WEY": "WEY", "魏牌": "WEY",
    "荣威": "Roewe", "宝骏": "Baojun", "东风": "Dongfeng",
    "东风风行": "Dongfeng Forthing", "东风风神": "Dongfeng Aeolus",
    "东风风光": "Dongfeng Fengguang", "东风小康": "Dongfeng Sokon",
    "猎豹": "Liebao", "猎豹汽车": "Liebao",
    "中华": "Brilliance", "华晨": "Brilliance",
    "北京汽车": "BAIC", "北汽新能源": "BAIC BJEV",
    "极狐": "Arcfox", "智己": "IM Motors", "飞凡": "Rising Auto",
    "阿维塔": "AVATR", "智界": "Luxeed", "享界": "Stelato",
    "深蓝": "Deepal", "深蓝汽车": "Deepal", "启源": "Qiyuan",
    "长安启源": "Changan Qiyuan", "捷途": "Jetour", "星途": "Exeed",
    "凯翼": "Cowin", "江淮": "JAC", "江铃": "JMC", "海马": "Haima",
    "东南": "Soueast", "众泰": "Zotye", "力帆": "Lifan",
    "克莱斯勒": "Chrysler", "道奇": "Dodge", "Jeep": "Jeep",
    "林肯": "Lincoln", "捷尼赛思": "Genesis",
    "DS": "DS", "阿尔法罗密欧": "Alfa Romeo", "阿斯顿马丁": "Aston Martin",
    "迈凯伦": "McLaren", "布加迪": "Bugatti", "柯尼塞格": "Koenigsegg",
    "哪吒": "Neta", "哪吒汽车": "Neta", "高合": "HiPhi",
    "几何": "Geometry", "几何汽车": "Geometry", "睿蓝": "Radar",
    "欧拉": "ORA", "欧拉汽车": "ORA",
}

COLOR_MAP = {
    "白色": "White", "黑色": "Black", "银色": "Silver", "灰色": "Gray",
    "深灰色": "Dark Gray", "蓝色": "Blue", "红色": "Red", "棕色": "Brown",
    "咖啡色": "Brown", "橙色": "Orange", "黄色": "Yellow", "绿色": "Green",
    "紫色": "Purple", "香槟色": "Champagne", "金色": "Gold", "粉色": "Pink",
    "其他": "Other",
}

FUEL_MAP = {
    "汽油": "Petrol", "柴油": "Diesel", "电动": "Electric", "纯电": "Electric",
    "混合动力": "Hybrid", "油电混合": "Hybrid", "插电混动": "PHEV",
    "插电式混合动力": "PHEV", "增程式": "EREV", "增程": "EREV",
    "氢燃料": "Hydrogen", "天然气": "CNG",
}

TRANSMISSION_MAP = {
    "手动": "Manual", "自动": "Automatic", "无级变速": "CVT",
    "双离合": "DCT", "湿式双离合": "Wet DCT", "干式双离合": "Dry DCT",
    "AMT": "AMT", "电动单速变速箱": "Single-Speed", "电动": "Single-Speed",
}

DRIVE_MAP = {
    "前置前驱": "FWD", "前驱": "FWD",
    "前置后驱": "RWD", "后置后驱": "RWD", "中置后驱": "RWD", "后驱": "RWD",
    "全时四驱": "AWD", "适时四驱": "AWD", "分时四驱": "AWD", "四驱": "AWD",
}

CITY_MAP = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "杭州": "Hangzhou", "成都": "Chengdu", "重庆": "Chongqing", "南京": "Nanjing",
    "武汉": "Wuhan", "西安": "Xi'an", "天津": "Tianjin", "苏州": "Suzhou",
    "青岛": "Qingdao", "沈阳": "Shenyang", "济南": "Jinan", "哈尔滨": "Harbin",
    "长春": "Changchun", "合肥": "Hefei", "贵阳": "Guiyang", "烟台": "Yantai",
    "宁波": "Ningbo", "郑州": "Zhengzhou", "南宁": "Nanning", "昆明": "Kunming",
    "潍坊": "Weifang", "东莞": "Dongguan", "温州": "Wenzhou", "淄博": "Zibo",
    "威海": "Weihai", "乌鲁木齐": "Urumqi", "南昌": "Nanchang", "厦门": "Xiamen",
    "福州": "Fuzhou", "石家庄": "Shijiazhuang", "太原": "Taiyuan", "兰州": "Lanzhou",
    "大连": "Dalian", "佛山": "Foshan", "无锡": "Wuxi", "长沙": "Changsha",
}


def tr(value: str, mapping: dict) -> str:
    if not value:
        return ""
    return mapping.get(value.strip(), value.strip())


def parse_wan(value: str) -> float | None:
    if not value:
        return None
    m = re.search(r'([\d.]+)\s*万', value)
    if m:
        try:
            return round(float(m.group(1)) * 10000, 1)
        except ValueError:
            return None
    m = re.search(r'([\d.]+)', value)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def parse_reg_date(value: str) -> str | None:
    if not value:
        return None
    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月', value)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-01"
    m = re.search(r'(\d{4})', value)
    if m:
        return f"{m.group(1)}-01-01"
    return None


def parse_horse_power(value: str) -> int | None:
    if not value:
        return None
    m = re.search(r'(\d+)\s*马力', value)
    return int(m.group(1)) if m else None


def parse_displacement(value: str) -> float | None:
    if not value:
        return None
    m = re.search(r'([\d.]+)\s*[TL]', value)
    return float(m.group(1)) if m else None


def parse_owners(value: str) -> int | None:
    if not value:
        return None
    m = re.search(r'(\d+)', value)
    return int(m.group(1)) if m else None


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ---------- Card parsing ----------

def parse_card(next_data: dict, card_id: str) -> dict | None:
    try:
        sku = next_data["props"]["pageProps"]["skuDetail"]
    except (KeyError, TypeError):
        return None
    if not sku:
        return None

    car_info = sku.get("car_info", {}) or {}
    config = sku.get("car_config_overview", {}) or {}
    power = config.get("power") or {}
    manip = config.get("manipulation") or {}
    space = config.get("space") or {}
    shop = sku.get("shop_info") or {}

    op = {}
    for item in (sku.get("other_params") or []):
        op[item.get("name", "")] = item.get("value", "")

    brand_original = car_info.get("brand_name", "")
    series_original = car_info.get("series_name", "")
    car_name = car_info.get("car_name", "")
    model = (series_original + " " + car_name).strip() if series_original else car_name

    color_original = car_info.get("body_color", "") or op.get("车身颜色", "")
    fuel_original = power.get("fuel_form", "")
    gearbox_original = op.get("变速箱", "") or power.get("gearbox_description", "")
    drive_original = manip.get("driver_form", "")

    series_type_code = car_info.get("series_type")
    body_type_codes = {0: "Sedan", 1: "SUV", 2: "Minivan", 3: "Pickup", 4: "Sports Car",
                       6: "Light Commercial", 7: "Microvan", 8: "Mini Truck"}
    body_type = body_type_codes.get(series_type_code) if series_type_code is not None else ""
    if not body_type and series_original:
        sl = series_original.lower()
        if "suv" in sl or "越野" in series_original:
            body_type = "SUV"
        elif "mpv" in sl:
            body_type = "Minivan"

    energy_code = car_info.get("series_new_energy_type")
    energy_codes = {0: "Petrol", 1: "Electric", 2: "PHEV", 3: "PHEV", 4: "EREV"}
    engine_type = energy_codes.get(energy_code) or tr(fuel_original, FUEL_MAP)

    # Price: dongchedi gives fen (1/100 CNY). Store original CNY only; frontend converts.
    sh_price = sku.get("source_sh_price")
    price_original = sh_price / 100 if sh_price else None

    off_price = sku.get("source_offical_price")
    new_price_original = off_price / 100 if off_price else None

    km_age = (parse_wan(car_info.get("mileage", ""))
              or parse_wan(op.get("行驶里程", ""))
              or parse_wan(sku.get("important_text", "")))

    city_original = shop.get("city_name", "") or op.get("车源地", "")
    reg_city_original = op.get("上牌地", "")

    images = sku.get("head_images") or []

    ts = DB.now_iso()

    return {
        "source": SOURCE,
        "source_id": str(card_id),
        "source_language": SOURCE_LANGUAGE,
        "url": CARD_URL.format(id=card_id),
        "title": sku.get("title", "") or f"{series_original} {car_name}".strip(),

        # Brand / model
        "mark_original": brand_original,
        "mark": tr(brand_original, BRAND_MAP) or brand_original,
        "series_original": series_original,
        "model": model,
        "complectation": car_name,
        "year": car_info.get("year"),

        # Prices: original currency only — frontend converts via live FX
        "price_original": price_original,
        "price_currency": PRICE_CURRENCY,
        "new_price_original": new_price_original,
        "new_price_currency": PRICE_CURRENCY if new_price_original else None,

        # Mileage (km_age stays normalized for cross-market filters)
        "km_age_original": km_age,
        "km_age_unit": KM_AGE_UNIT,
        "km_age": km_age,

        # Color
        "color_original": color_original,
        "color": tr(color_original, COLOR_MAP),

        # Body / engine / transmission / drive
        "body_type": body_type,
        "engine_type": engine_type,
        "fuel_original": fuel_original,
        "transmission_original": gearbox_original,
        "transmission_type": tr(gearbox_original, TRANSMISSION_MAP)
                              or ("Automatic" if "自动" in gearbox_original else ""),
        "drive_original": drive_original,
        "drive_type": tr(drive_original, DRIVE_MAP),

        "displacement": parse_displacement(op.get("排量", "") or power.get("capacity", "")),
        "horse_power": parse_horse_power(power.get("horsepower", "")),
        "acceleration_time": power.get("acceleration_time", ""),

        # Dimensions
        "length_mm": safe_int(space.get("length")),
        "width_mm": safe_int(space.get("width")),
        "height_mm": safe_int(space.get("height")),
        "wheelbase_mm": safe_int(space.get("wheelbase")),

        # Location
        "city_original": city_original,
        "city": tr(city_original, CITY_MAP),
        "reg_city_original": reg_city_original,
        "reg_city": tr(reg_city_original, CITY_MAP),
        "reg_date": parse_reg_date(op.get("上牌时间", "")),

        # Misc
        "owners_count": parse_owners(op.get("过户次数", "")),
        "maintenance": op.get("保养方式", ""),
        "interior_color_original": op.get("内饰颜色", ""),
        "description": sku.get("sh_car_desc", ""),

        # Images
        "images": images,
        "image_count": len(images),

        # Shop
        "seller_type": "Dealer" if shop.get("shop_type") else "Private",
        "shop_name": shop.get("shop_name", ""),
        "shop_short_name": shop.get("shop_short_name", ""),
        "shop_address": shop.get("shop_address", ""),
        "shop_id": str(shop.get("shop_id", "")),
        "shop_cars_count": shop.get("sales_car_num"),
        "sales_range": shop.get("sales_range", ""),

        # Reserve for inspection report, options, etc.
        "source_data": None,
        "spu_id": str(sku.get("spu_id", "")),

        "first_seen": ts,
        "last_seen": ts,
    }


def scrape_card(card_id: str) -> dict | None:
    url = CARD_URL.format(id=card_id)
    html = oxylabs_fetch(url, render=True)
    if not html:
        return None
    nd = extract_next_data(html)
    if not nd:
        return None
    return parse_card(nd, card_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--skip-listing", action="store_true",
                    help="Use IDs from pending_ids (populated by collect_ids.py)")
    args = ap.parse_args()

    print(f"Backend: {DB.backend_name()}")
    print(f"Limit: {args.limit}, workers: {args.workers}")
    existing = DB.count_cars(SOURCE)
    print(f"cars[{SOURCE}] already: {existing}")

    if not args.skip_listing:
        sys.exit("Use --skip-listing — listing collection is in collect_ids.py")

    ids = DB.get_pending_ids(SOURCE, args.limit)
    print(f"Loaded {len(ids)} pending IDs for [{SOURCE}]")

    if not ids:
        print("Nothing to scrape. Run collect_ids.py first.")
        return

    print(f"\nScraping {len(ids)} cards with {args.workers} workers...")
    ok, fail = 0, 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape_card, cid): cid for cid in ids}
        for i, fut in enumerate(as_completed(futures), 1):
            cid = futures[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = None
                print(f"  [{i}/{len(ids)}] id={cid} EXCEPTION: {e}")

            if rec:
                if DB.upsert_car(rec):
                    ok += 1
                    print(f"  [{i}/{len(ids)}] id={cid} OK {rec['mark']} {rec['model']} "
                          f"{rec['year']} {rec['price_original']} {rec['price_currency']} "
                          f"{rec['km_age']}km {rec['city'] or rec['city_original']}")
                else:
                    fail += 1
                    print(f"  [{i}/{len(ids)}] id={cid} DB FAIL")
            else:
                fail += 1
                print(f"  [{i}/{len(ids)}] id={cid} SCRAPE FAIL")

    print(f"\nDone. OK: {ok}, FAIL: {fail}")
    print(f"Total in cars[{SOURCE}]: {DB.count_cars(SOURCE)}")


if __name__ == "__main__":
    main()
