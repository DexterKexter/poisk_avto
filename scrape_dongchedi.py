"""
Dongchedi.com used car scraper via Oxylabs Realtime API.

Usage:
    set OXY_USER=your_user
    set OXY_PASS=your_pass
    python scrape_dongchedi.py [--cities bj,sh,gz,sz] [--limit 1000] [--workers 3]

Stores results in cars.db (SQLite). Resume-friendly: dedupes by URL.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests

# ---------- Config ----------
OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

CITY_CODES = {
    "bj": ("北京", "Beijing"),
    "sh": ("上海", "Shanghai"),
    "gz": ("广州", "Guangzhou"),
    "sz": ("深圳", "Shenzhen"),
}

LISTING_URL = "https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x"
LISTING_URL_PAGED = "https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x?page={page}"
CARD_URL = "https://www.dongchedi.com/usedcar/{id}"

DB_PATH = "cars.db"
DELAY = 1.0
MAX_RETRIES = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Oxylabs request helper ----------
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
                OXY_URL,
                auth=(OXY_USER, OXY_PASS),
                json=payload,
                timeout=180,
            )
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} on {url} (attempt {attempt+1})")
                time.sleep(2 ** attempt)
                continue
            data = r.json()
            results = data.get("results", [])
            if not results:
                print(f"  empty results on {url}")
                return None
            content = results[0].get("content")
            if not content or len(content) < 1000:
                print(f"  short content on {url} ({len(content) if content else 0} bytes)")
                time.sleep(2 ** attempt)
                continue
            return content
        except Exception as e:
            print(f"  exception on {url}: {e} (attempt {attempt+1})")
            time.sleep(2 ** attempt)

    return None


# ---------- HTML parsing ----------
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Real card IDs are 7+ digits. Shorter matches are nav links like /usedcar/5/.
CARD_LINK_RE = re.compile(r'/usedcar/(\d{7,})')


def extract_next_data(html: str) -> dict | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def extract_card_ids(html: str) -> list[str]:
    return list(dict.fromkeys(CARD_LINK_RE.findall(html)))


# ---------- Translation maps ----------
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

BODY_MAP = {
    "轿车": "Sedan", "SUV": "SUV", "MPV": "Minivan", "跑车": "Sports Car",
    "皮卡": "Pickup", "微卡": "Mini Truck", "微面": "Microvan",
    "轻客": "Light Commercial", "两厢车": "Hatchback", "三厢车": "Sedan",
    "旅行车": "Wagon", "敞篷车": "Convertible", "硬顶敞篷车": "Convertible",
    "客车": "Bus", "房车": "Motorhome",
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
            return float(m.group(1)) * 10000
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

    brand_cn = car_info.get("brand_name", "")
    series_cn = car_info.get("series_name", "")
    car_name = car_info.get("car_name", "")
    # Full model name: series + trim ("奔驰GLA" + "GLA 200 动感型")
    model_cn = (series_cn + " " + car_name).strip() if series_cn else car_name

    color_cn = car_info.get("body_color", "") or op.get("车身颜色", "")
    fuel_cn = power.get("fuel_form", "")
    gearbox_cn = op.get("变速箱", "") or power.get("gearbox_description", "")
    drive_cn = manip.get("driver_form", "")

    # Body type
    series_type_code = car_info.get("series_type")
    body_type_codes = {0: "Sedan", 1: "SUV", 2: "Minivan", 3: "Pickup", 4: "Sports Car",
                       6: "Light Commercial", 7: "Microvan", 8: "Mini Truck"}
    body_type = body_type_codes.get(series_type_code) if series_type_code is not None else ""
    if not body_type and series_cn:
        series_lower = series_cn.lower()
        if "suv" in series_lower or "越野" in series_cn:
            body_type = "SUV"
        elif "mpv" in series_lower:
            body_type = "Minivan"

    # New-energy type
    energy_code = car_info.get("series_new_energy_type")
    energy_codes = {0: "Petrol", 1: "Electric", 2: "PHEV", 3: "PHEV", 4: "EREV"}
    engine_type = energy_codes.get(energy_code) or tr(fuel_cn, FUEL_MAP)

    price_cny = sku.get("source_sh_price")
    if price_cny:
        price_cny = price_cny / 100  # fen -> CNY
    new_price_cny = sku.get("source_offical_price")
    if new_price_cny:
        new_price_cny = new_price_cny / 100

    # Mileage with multiple fallbacks
    km_age = (parse_wan(car_info.get("mileage", ""))
              or parse_wan(op.get("行驶里程", ""))
              or parse_wan(sku.get("important_text", "")))

    ts = now_iso()
    record = {
        "inner_id": card_id,
        "url": CARD_URL.format(id=card_id),
        "title": sku.get("title", "") or f"{series_cn} {car_name}".strip(),
        "mark_cn": brand_cn,
        "mark": tr(brand_cn, BRAND_MAP) or brand_cn,
        "series_cn": series_cn,
        "model": model_cn,
        "complectation": car_name,
        "year": car_info.get("year"),
        "price_cny": price_cny,
        "new_price_cny": new_price_cny,
        "km_age": km_age,
        "color_cn": color_cn,
        "color": tr(color_cn, COLOR_MAP),
        "body_type": body_type,
        "engine_type": engine_type,
        "fuel_cn": fuel_cn,
        "transmission_cn": gearbox_cn,
        "transmission_type": tr(gearbox_cn, TRANSMISSION_MAP)
                             or ("Automatic" if "自动" in gearbox_cn else ""),
        "drive_cn": drive_cn,
        "drive_type": tr(drive_cn, DRIVE_MAP),
        "displacement": parse_displacement(op.get("排量", "") or power.get("capacity", "")),
        "horse_power": parse_horse_power(power.get("horsepower", "")),
        "acceleration_time": power.get("acceleration_time", ""),
        "length_mm": safe_int(space.get("length")),
        "width_mm": safe_int(space.get("width")),
        "height_mm": safe_int(space.get("height")),
        "wheelbase_mm": safe_int(space.get("wheelbase")),
        "city_cn": shop.get("city_name", "") or op.get("车源地", ""),
        "reg_city_cn": op.get("上牌地", ""),
        "reg_date": parse_reg_date(op.get("上牌时间", "")),
        "owners_count": parse_owners(op.get("过户次数", "")),
        "maintenance": op.get("保养方式", ""),
        "interior_color_cn": op.get("内饰颜色", ""),
        "description": sku.get("sh_car_desc", ""),
        "images": json.dumps(sku.get("head_images") or [], ensure_ascii=False),
        "image_count": len(sku.get("head_images") or []),
        "seller_type": "Dealer" if shop.get("shop_type") else "Private",
        "shop_name": shop.get("shop_name", ""),
        "shop_short_name": shop.get("shop_short_name", ""),
        "shop_address": shop.get("shop_address", ""),
        "shop_id": shop.get("shop_id", ""),
        "shop_cars_count": shop.get("sales_car_num"),
        "sales_range": shop.get("sales_range", ""),
        "spu_id": sku.get("spu_id", ""),
        "first_seen": ts,
        "last_seen": ts,
    }
    return record


# ---------- Database ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS cars (
    inner_id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    mark_cn TEXT, mark TEXT,
    series_cn TEXT, model TEXT, complectation TEXT,
    year INTEGER,
    price_cny REAL, new_price_cny REAL,
    km_age REAL,
    color_cn TEXT, color TEXT,
    body_type TEXT,
    engine_type TEXT, fuel_cn TEXT,
    transmission_cn TEXT, transmission_type TEXT,
    drive_cn TEXT, drive_type TEXT,
    displacement REAL, horse_power INTEGER,
    acceleration_time TEXT,
    length_mm INTEGER, width_mm INTEGER, height_mm INTEGER, wheelbase_mm INTEGER,
    city_cn TEXT, reg_city_cn TEXT,
    reg_date TEXT,
    owners_count INTEGER,
    maintenance TEXT, interior_color_cn TEXT,
    description TEXT,
    images TEXT, image_count INTEGER,
    seller_type TEXT,
    shop_name TEXT, shop_short_name TEXT, shop_address TEXT,
    shop_id TEXT, shop_cars_count INTEGER, sales_range TEXT,
    spu_id TEXT,
    first_seen TEXT, last_seen TEXT
);

CREATE INDEX IF NOT EXISTS idx_mark ON cars(mark);
CREATE INDEX IF NOT EXISTS idx_year ON cars(year);
CREATE INDEX IF NOT EXISTS idx_price ON cars(price_cny);
CREATE INDEX IF NOT EXISTS idx_city ON cars(city_cn);

CREATE TABLE IF NOT EXISTS seen_ids (
    inner_id TEXT PRIMARY KEY,
    first_seen TEXT
);
"""


def db_init() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def db_save(conn: sqlite3.Connection, rec: dict) -> None:
    cols = list(rec.keys())
    placeholders = ",".join(":" + c for c in cols)
    col_list = ",".join(cols)
    update_list = ",".join(f"{c}=excluded.{c}" for c in cols if c != "inner_id" and c != "first_seen")
    sql = (f"INSERT INTO cars ({col_list}) VALUES ({placeholders}) "
           f"ON CONFLICT(inner_id) DO UPDATE SET {update_list}")
    conn.execute(sql, rec)
    conn.execute(
        "INSERT OR IGNORE INTO seen_ids (inner_id, first_seen) VALUES (?, ?)",
        (rec["inner_id"], rec["first_seen"]),
    )
    conn.commit()


def db_known_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT inner_id FROM seen_ids").fetchall()
    return {r[0] for r in rows}


# ---------- Workflow ----------
def collect_listing_ids(cities: list[str], limit: int) -> list[str]:
    all_ids: list[str] = []
    seen: set[str] = set()

    for city in cities:
        if len(all_ids) >= limit:
            break
        page = 1
        per_city_collected = 0
        while len(all_ids) < limit and page <= 100:
            url = (LISTING_URL if page == 1
                   else LISTING_URL_PAGED.format(page=page))
            print(f"[listing] {city} page {page} -> {url}")
            html = oxylabs_fetch(url, render=True)
            if not html:
                print(f"  failed to fetch listing")
                break

            ids = extract_card_ids(html)
            new_ids = [i for i in ids if i not in seen]
            if not new_ids:
                print(f"  no new ids on page {page}, moving on")
                break

            for i in new_ids:
                seen.add(i)
                all_ids.append(i)
                per_city_collected += 1
                if len(all_ids) >= limit:
                    break

            print(f"  collected {len(new_ids)} new ids "
                  f"(city {city} total: {per_city_collected}, grand total: {len(all_ids)})")
            page += 1
            time.sleep(DELAY)

    return all_ids


def scrape_card(card_id: str) -> dict | None:
    url = CARD_URL.format(id=card_id)
    html = oxylabs_fetch(url, render=True)
    if not html:
        return None
    nd = extract_next_data(html)
    if not nd:
        print(f"  no __NEXT_DATA__ for id={card_id}")
        return None
    return parse_card(nd, card_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default="bj,sh,gz,sz",
                    help="Comma-separated city codes (bj, sh, gz, sz)")
    ap.add_argument("--limit", type=int, default=1000,
                    help="Max number of cards to scrape this run")
    ap.add_argument("--workers", type=int, default=3,
                    help="Parallel card-page workers")
    ap.add_argument("--skip-listing", action="store_true",
                    help="Skip listing collection, only re-parse known ids")
    args = ap.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip() in CITY_CODES]
    print(f"Cities: {cities}, limit: {args.limit}, workers: {args.workers}")

    conn = db_init()
    known = db_known_ids(conn)
    print(f"Already in DB: {len(known)} cards")

    if args.skip_listing:
        # Pull IDs from pending_ids table (populated by collect_ids.py),
        # excluding those already fully scraped.
        try:
            rows = conn.execute("""
                SELECT sku_id FROM pending_ids
                WHERE sku_id NOT IN (SELECT inner_id FROM seen_ids)
                ORDER BY found_at DESC
                LIMIT ?
            """, (args.limit,)).fetchall()
            ids_to_scrape = [r[0] for r in rows]
            print(f"Loaded {len(ids_to_scrape)} pending IDs from pending_ids table")
        except sqlite3.OperationalError:
            print("ERROR: pending_ids table not found. Run collect_ids.py first.")
            ids_to_scrape = []
    else:
        all_ids = collect_listing_ids(cities, args.limit)
        ids_to_scrape = all_ids
        print(f"\nCollected {len(all_ids)} listing ids "
              f"({len([i for i in all_ids if i not in known])} new)")

    print(f"\nScraping {len(ids_to_scrape)} cards with {args.workers} workers...")
    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape_card, cid): cid for cid in ids_to_scrape}
        for i, fut in enumerate(as_completed(futures), 1):
            cid = futures[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = None
                print(f"  [{i}/{len(ids_to_scrape)}] id={cid} exception: {e}")

            if rec:
                db_save(conn, rec)
                ok += 1
                print(f"  [{i}/{len(ids_to_scrape)}] id={cid} OK "
                      f"{rec['mark']} {rec['model']} {rec['year']} "
                      f"{rec['price_cny']} CNY {rec['km_age']}km {rec['city_cn']}")
            else:
                fail += 1
                print(f"  [{i}/{len(ids_to_scrape)}] id={cid} FAIL")

    print(f"\nDone. OK: {ok}, FAIL: {fail}")
    print(f"Database: {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()