"""Recon: find higher-res image fields in dongchedi SKU payload."""
import json, os, re, sys, time
import requests
sys.stdout.reconfigure(line_buffering=True)

OXY_USER = os.environ.get("OXY_USER")
OXY_PASS = os.environ.get("OXY_PASS")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
SKU_ID = sys.argv[1] if len(sys.argv) > 1 else "23406092"
CARD_URL = f"https://www.dongchedi.com/usedcar/{SKU_ID}"


def oxy_fetch(url):
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
        json={"source": "universal", "url": url,
              "geo_location": "China", "locale": "zh-CN", "render": "html"},
        timeout=180)
    r.raise_for_status()
    return r.json()["results"][0]["content"]


def walk(obj, path=""):
    """Yield (path, value) for every leaf and intermediate node."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            yield p, v
            yield from walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            yield p, v
            yield from walk(v, p)


print(f"Fetching {CARD_URL} ...")
html = oxy_fetch(CARD_URL)

# Also try the mobile URL — often serves higher-res images for retina
print(f"\nFetching mobile https://m.dongchedi.com/usedcar/{SKU_ID} ...")
try:
    m_html = oxy_fetch(f"https://m.dongchedi.com/usedcar/{SKU_ID}")
    m_imgs = re.findall(r'https?://[^"\s]*byteimg\.com[^"\s]*', m_html)
    m_imgs = list(dict.fromkeys(m_imgs))
    print(f"  mobile len={len(m_html)}, unique byteimg URLs: {len(m_imgs)}")
    for u in m_imgs[:10]:
        sz = re.search(r":(\d+):(\d+)", u)
        sz_str = f"{sz.group(1)}x{sz.group(2)}" if sz else "no-tpl"
        print(f"    [{sz_str}] {u[:140]}")
except Exception as e:
    print(f"  mobile ERR: {e}")

print(f"  html len={len(html)}")
m = NEXT_RE.search(html)
if not m:
    sys.exit("no __NEXT_DATA__")
data = json.loads(m.group(1))

# Find every field containing a byteimg URL or image-like string
img_paths = []
for p, v in walk(data):
    if isinstance(v, str) and ("byteimg.com" in v or "byteimg-cn-i" in v
                                or v.endswith((".jpg", ".jpeg", ".png", ".webp"))):
        img_paths.append((p, v))

print(f"\nFound {len(img_paths)} image-like leaf strings. Unique paths:")
unique_paths = sorted({p.split("[")[0] for p, _ in img_paths})
for up in unique_paths:
    sample = next((v for p, v in img_paths if p.split("[")[0] == up), "")
    # Extract template size from URL
    sz = re.search(r":(\d+):(\d+)", sample)
    sz_str = f"{sz.group(1)}x{sz.group(2)}" if sz else "no-template"
    print(f"  {up:60} ({sz_str})")
    print(f"    → {sample[:140]}")

# Also dump top-level keys of skuDetail to see what we miss
sku = data.get("props", {}).get("pageProps", {}).get("skuDetail", {})
print(f"\nskuDetail top-level keys ({len(sku)}):")
for k in sorted(sku.keys()):
    v = sku[k]
    kind = type(v).__name__
    size = len(v) if hasattr(v, "__len__") else "-"
    print(f"  {k:35} ({kind}, size={size})")

# Dump any key containing 'pic', 'image', 'photo' in path tree
print("\nPaths containing 'pic'/'image'/'photo'/'gallery':")
for p, v in walk(data):
    if any(kw in p.lower() for kw in ("pic", "image", "photo", "gallery", "head_img")):
        if isinstance(v, (list, dict)) and len(v) > 0:
            print(f"  {p:80} {type(v).__name__}(len={len(v)})")
        elif isinstance(v, str) and len(v) > 20:
            print(f"  {p:80} = {v[:100]}")

# Dump skuDetail.report — might contain check_id or photo URLs
print("\n=== skuDetail.report ===")
report = sku.get("report") or {}
print(json.dumps(report, ensure_ascii=False, indent=2)[:3000])

# Look for any URL-like field anywhere
print("\n=== All URL-like fields (containing /motor/, dongchedi.com/api, /sh_) ===")
for p, v in walk(data):
    if isinstance(v, str) and any(kw in v for kw in ("/motor/", "/api/", "/sh_", "check_id", "dcdx-default", "/inspection")):
        print(f"  {p}\n    {v[:160]}")

# Try fetching a known dongchedi inspection-report endpoint with sku_id
print("\n=== Try /motor/sh_check_report endpoint ===")
for endpoint in [
    f"https://www.dongchedi.com/motor/sh_check_report?sku_id={SKU_ID}",
    f"https://www.dongchedi.com/motor/v1/used_car/check_report?sku_id={SKU_ID}",
    f"https://www.dongchedi.com/motor/v1/used_car/sku_pic_list?sku_id={SKU_ID}",
    f"https://www.dongchedi.com/motor/v3/use_car_check_report?sku_id={SKU_ID}",
]:
    try:
        h = oxy_fetch(endpoint)
        print(f"  {endpoint}\n    len={len(h)}  head={h[:200]!r}")
    except Exception as e:
        print(f"  {endpoint}\n    ERR {e}")
