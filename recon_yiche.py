"""
recon_yiche.py v2 — find real yiche car catalog URLs.

v1 showed:
  - yiche.com/ is editorial (news/videos), no cars
  - car.yiche.com/ returns 16KB skeleton (need to inspect)
  - yiche.com/newcar/ → 404
  - API host is mapi.yiche.com

v2 strategy:
  1. Re-probe car.yiche.com but DUMP FULL HTML to stdout so we can read
     the actual <a href> links and `<script>` references.
  2. Try a few alternative paths in parallel based on common Chinese
     auto-site patterns (jiage = prices, brand pages, series pages).

Env: OXY_USER, OXY_PASS
"""

import json
import os
import re
import sys

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

TARGETS = [
    # Empty skeleton from v1 — dump full content this time.
    ("01_car_hub",        "https://car.yiche.com/"),
    # 价格 = "prices" — common Chinese auto site path
    ("02_jiage",          "https://www.yiche.com/jiage/"),
    # 选车 = "choose a car"
    ("03_xuanche",        "https://www.yiche.com/xuanche/"),
    # Common pattern: car.yiche.com/{brand_pinyin}/
    ("04_byd_brand",      "https://car.yiche.com/byd/"),
    # Direct model — BYD Han is popular
    ("05_han_series",     "https://car.yiche.com/han/"),
    # 报价 = "quote/MSRP"
    ("06_baojia",         "https://www.yiche.com/baojia/"),
]

HREF_RE = re.compile(r'href="([^"]+)"')
SCRIPT_SRC_RE = re.compile(r'<script[^>]+src="([^"]+)"')


def probe(name: str, url: str) -> None:
    print(f"\n========== {name}: {url} ==========")
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
    }
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                          json=payload, timeout=180)
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return
    results = r.json().get("results", []) or []
    if not results:
        print("  no results")
        return
    target_status = results[0].get("status_code")
    final_url = results[0].get("url")
    content = results[0].get("content", "")
    print(f"  Target HTTP: {target_status}")
    print(f"  Final URL:   {final_url}")
    if not isinstance(content, str):
        print(f"  Content is {type(content).__name__}")
        return
    print(f"  HTML length: {len(content)} chars")

    # Save full content
    path = os.path.join(OUT_DIR, f"yiche_v2_{name}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Full HTML → {path}")

    # Extract internal links pointing to yiche.com pages
    hrefs = HREF_RE.findall(content)
    yiche_links = sorted({h for h in hrefs
                          if "yiche.com" in h and not any(
                              s in h for s in (
                                  "javascript:", "#", "mailto:",
                                  "/ad", "/aboutus", "/contact",
                                  "/privacy", "/terms",
                                  "icp.gov", "weibo.com", "qq.com",
                                  "douban.com", "youku.com"
                              ))})
    # Strip query strings for the unique-path overview
    cleaned = sorted({h.split("?")[0].split("#")[0] for h in yiche_links})

    print(f"\n  Internal yiche links ({len(yiche_links)} raw, "
          f"{len(cleaned)} unique paths):")
    for link in cleaned[:60]:
        print(f"    {link}")

    # If HTML is short, dump it fully to logs too
    if len(content) < 20000:
        print(f"\n  ===== FULL HTML (since short) =====")
        print(content)
        print(f"  ===== END HTML =====")


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    for name, url in TARGETS:
        probe(name, url)

    print("\n========== DONE ==========")
    print("Inspect printed links to find the real car catalog URLs,")
    print("then a v3 will drill into those.")


if __name__ == "__main__":
    main()
