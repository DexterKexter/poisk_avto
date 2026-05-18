"""enrich_brand_logos_clearbit.py — fill `brands.logo_url` from Clearbit
Logo API for brands not covered by the autocango featured grid.

Strategy:
  1. Read brands where logo_url IS NULL.
  2. For each, try a list of candidate domains derived from the name.
     Verify with HEAD requests (Clearbit returns 200 only when its CDN
     has a real logo file).
  3. PATCH brands.logo_url with the first hit.

Override map covers Chinese / Korean brands whose canonical domain is
not obvious (e.g. NIO → nio.com, Geely → geely.com, BYD → byd.com,
Voyah → voyah.com.cn, Hongqi → hongqi.com, etc).

Usage: python enrich_brand_logos_clearbit.py
Env:   SUPABASE_URL, SUPABASE_KEY
"""

import sys
import time

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

CLEARBIT = "https://logo.clearbit.com/{domain}"

# Hand-curated domain overrides for brands whose Clearbit slug isn't obvious
DOMAIN_OVERRIDES = {
    # Chinese mainstream
    "BYD": "byd.com", "Geely": "geely.com", "Chery": "chery.com.cn",
    "Great Wall": "gwm-global.com", "Haval": "haval-global.com",
    "Wuling": "wuling.com", "Hongqi": "hongqi-auto.com",
    "ChangAn": "globalchangan.com", "Changan": "globalchangan.com",
    "GAC Trumpchi": "gac-motor.com", "GAC": "gac-motor.com",
    "JAC": "jac-motors.com", "Brilliance Auto": "brilliance-auto.com",
    "Dongfeng": "dongfeng-global.com",
    "Dongfeng Fengguang": "dongfeng-global.com",
    "Dongfeng Aeolus": "dongfeng-global.com",
    "BAIC": "baicgroup.com.cn", "BAIC BJEV": "baicgroup.com.cn",
    "BAIC ChangHe": "baicgroup.com.cn", "BAIC WeiWang": "baicgroup.com.cn",
    "Roewe": "roewe.com.cn", "MG": "mgmotor.eu",
    "Bestune": "bestune.com.cn", "Jetour": "jetour-auto.com",
    "Aion": "aionchina.com", "Avatr": "avatr.com",
    "Voyah": "voyah.com.cn", "Tank": "tank.com.cn",
    "Lynk & Co": "lynkco.com", "Lynkco": "lynkco.com",
    "Lixiang": "lixiang.com", "Li Auto": "lixiang.com",
    "NIO": "nio.com", "Onvo": "onvo.com", "XPeng": "xiaopeng.com",
    "XPENG": "xiaopeng.com",
    "Xiaomi": "xiaomi.com", "Zeekr": "zeekrglobal.com",
    "AITO": "aitoauto.com", "Luxeed": "luxeed.com", "Stelato": "stelato.com",
    "Maextro": "maextro.com", "HIMA": "huawei.com",
    "ARCFOX": "arcfox.com.cn", "IM": "immotors.com", "Polestar": "polestar.com",
    "Leapmotor": "leapmotor.com", "Neta": "nautocn.com",
    "Hozon": "nautocn.com", "Seres": "seres.cn", "AITO": "aito.com",
    "Yangwang": "yangwang.byd.com", "Denza": "denza.com",
    "Rising Auto": "risingauto.com", "JMC": "jmc.com.cn",
    "ROX": "rox-motors.com", "Lingbao": "lingbao-auto.com",
    "Sehol": "jac-motors.com", "DFSK": "dfskglobal.com",
    "Ineos": "ineosgrenadier.com",
    "Watson-Will": None,  # too niche, will fail gracefully

    # Korean
    "Hyundai": "hyundai.com", "Kia": "kia.com", "Genesis": "genesis.com",
    "KG Mobility": "kg-mobility.com", "Renault Korea": "renaultkorea.com",

    # International
    "Toyota": "toyota.com", "Honda": "honda.com", "Nissan": "nissan.com",
    "Mazda": "mazda.com", "Subaru": "subaru.com", "Mitsubishi": "mitsubishi-motors.com",
    "BMW": "bmw.com", "Mercedes-Benz": "mercedes-benz.com",
    "Mercedes-AMG": "mercedes-amg.com", "Mercedes-Maybach": "mercedes-benz.com",
    "Audi": "audi.com", "Porsche": "porsche.com",
    "Volkswagen": "vw.com", "VW": "vw.com",
    "Volvo": "volvocars.com", "Skoda": "skoda-auto.com",
    "SEAT": "seat.com", "Mini": "mini.com", "MINI": "mini.com",
    "ALPINA": "alpina.de", "Smart": "smart.com",
    "Bentley": "bentleymotors.com", "Rolls-Royce": "rolls-roycemotorcars.com",
    "Bugatti": "bugatti.com", "Ferrari": "ferrari.com",
    "Lamborghini": "lamborghini.com", "Maserati": "maserati.com",
    "Aston Martin": "astonmartin.com", "Lotus": "lotuscars.com",
    "Pagani": "pagani.com", "Koenigsegg": "koenigsegg.com",
    "Alfa Romeo": "alfaromeo.com", "Fiat": "fiat.com",
    "Jeep": "jeep.com", "Dodge": "dodge.com", "Chrysler": "chrysler.com",
    "Ram": "ramtrucks.com", "Chevrolet": "chevrolet.com",
    "Cadillac": "cadillac.com", "GMC": "gmc.com", "Lincoln": "lincoln.com",
    "Ford": "ford.com", "Buick": "buick.com",
    "Tesla": "tesla.com", "Lucid": "lucidmotors.com", "Rivian": "rivian.com",
    "Hummer": "gmc.com",
    "Land Rover": "landrover.com", "Jaguar": "jaguar.com",
    "Citroen": "citroen.com", "Citroën": "citroen.com", "DS": "dsautomobiles.com",
    "Peugeot": "peugeot.com", "Renault": "renault.com",
    "Acura": "acura.com", "Infiniti": "infinitiusa.com", "Lexus": "lexus.com",
    "GWM Ora": "gwm-ora.com", "Ora": "gwm-ora.com",
    "Pony": "ponycar.com",
}


def candidate_domains(name: str) -> list[str]:
    """Return ordered candidate domains for a given brand name."""
    candidates: list[str] = []
    override = DOMAIN_OVERRIDES.get(name)
    if override is None and name in DOMAIN_OVERRIDES:
        return []  # explicit skip
    if override:
        candidates.append(override)
    # Generic fallbacks
    slug = name.lower().replace(" ", "").replace("&", "and").replace("-", "")
    candidates += [f"{slug}.com", f"{slug}.com.cn"]
    return candidates


def clearbit_url(domain: str) -> str | None:
    """Return Clearbit URL if logo exists at this domain, else None."""
    url = CLEARBIT.format(domain=domain)
    try:
        r = requests.head(url, timeout=10, allow_redirects=True)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return url
    except Exception:
        pass
    return None


def main() -> None:
    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    r = DB._pg_request(
        "GET", "brands?logo_url=is.null&select=id,name,slug&limit=1000")
    if r.status_code != 200:
        sys.exit(f"DB read fail: {r.status_code}")
    brands = r.json()
    print(f"Brands without logo: {len(brands)}", flush=True)

    updated = no_match = skipped = 0
    for i, b in enumerate(brands, 1):
        name = b["name"]
        cands = candidate_domains(name)
        if not cands:
            skipped += 1
            continue
        hit = None
        for dom in cands:
            hit = clearbit_url(dom)
            if hit:
                break
        if hit:
            upd = DB._pg_request(
                "PATCH", f"brands?id=eq.{b['id']}",
                json={"logo_url": hit, "updated_at": DB.now_iso()})
            if upd.status_code in (200, 204):
                updated += 1
                if i % 10 == 0 or i <= 5:
                    print(f"  [{i}/{len(brands)}] {name:25} ✅ {hit}", flush=True)
        else:
            no_match += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(brands)}] {name:25} ❌ tried: {cands}",
                      flush=True)

    print(f"\nDone.\n  Updated: {updated}  No-match: {no_match}  Skipped: {skipped}",
          flush=True)


if __name__ == "__main__":
    main()
