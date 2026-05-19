"""Recon che168 — dump ALL data for a single listing.

Usage:
    python recon_che168_car.py <detail_url_or_infoid>
    # e.g.  python recon_che168_car.py 57958783
    # or    python recon_che168_car.py https://www.che168.com/dealer/395220/57958783.html

Goal: see every field, every photo source, every verification badge, every
trust signal. Output is structured so we can decide what to map into our
`cars` schema later.
"""
import json, re, sys
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(line_buffering=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


_BROWSER = None
_CTX = None
_PAGE = None


def _start():
    global _BROWSER, _CTX, _PAGE
    p = sync_playwright().start()
    _BROWSER = p.chromium.launch(headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    _CTX = _BROWSER.new_context(user_agent=UA, locale="zh-CN",
        viewport={"width": 1366, "height": 800},
        ignore_https_errors=True)
    _CTX.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    _PAGE = _CTX.new_page()


def fetch(url: str) -> str:
    if _PAGE is None:
        _start()
    _PAGE.goto(url, wait_until="networkidle", timeout=45000)
    _PAGE.wait_for_timeout(1500)
    return _PAGE.content()


def collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def find_first_url(arg: str) -> str:
    """Accept a full URL or just an infoid. If infoid, find a dealer URL via listing search."""
    if arg.startswith("http"):
        return arg
    if not arg.isdigit():
        sys.exit("pass a URL or numeric infoid")
    # Fetch nationwide listing & find a card with this infoid
    html = fetch("https://www.che168.com/china/list/")
    m = re.search(rf'<a href="(/dealer/\d+/{arg}\.html[^"]*)"', html)
    if m:
        return "https://www.che168.com" + m.group(1)
    sys.exit(f"infoid {arg} not on china listing first page; pass full URL")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "57958783"
    url = find_first_url(arg)
    print(f"=== URL: {url}\n")

    html = fetch(url)
    print(f"html len: {len(html)}")
    soup = BeautifulSoup(html, "lxml")

    # ─── 1. Page title / breadcrumbs ───
    title = soup.title.string if soup.title else ""
    print(f"\n=== TITLE ===\n{collapse(title)}")

    # ─── 2. Main car card / price block (.car-table, .price-area, etc.) ───
    print("\n=== PRICE BLOCK ===")
    for sel in [".price", ".car-price", ".carbox-price", ".banner-price",
                ".goods-price", ".price-info", "[class*=price]"]:
        for el in soup.select(sel)[:3]:
            text = collapse(el.get_text(" "))
            if text and len(text) < 200:
                print(f"  [{sel}] {text}")

    # ─── 3. Spec table — all <li> / <p> inside a "car-attribute" container ───
    print("\n=== ALL SPEC ROWS (li/p with label-value pattern) ===")
    seen = set()
    for el in soup.find_all(["li", "p", "div", "td"]):
        text = collapse(el.get_text(" "))
        if not text or len(text) > 80 or text in seen:
            continue
        # Heuristic: label-value pairs usually contain ":" or 2-3 字 + a value
        if re.match(r"^[一-龥A-Za-z]{2,8}[：:]\s?\S+", text) or re.match(
            r"^(上牌时间|表显里程|过户|排量|变速箱|车身颜色|燃料类型|环保标准|VIN|车架号|发动机|驱动方式)",
            text,
        ):
            print(f"  · {text}")
            seen.add(text)

    # ─── 4. VIN ───
    print("\n=== VIN ===")
    vins = set(re.findall(r"\b([A-HJ-NPR-Z0-9*]{17})\b", html))
    # Filter out hex hashes
    real_vins = [v for v in vins if not re.fullmatch(r"[A-F0-9]+", v)]
    print("  candidates:", real_vins[:5] or "(none — VIN likely masked)")

    # ─── 5. Photos (autoimg.cn with all size variants) ───
    print("\n=== PHOTOS ===")
    raw = re.findall(r"(?:https?:)?//[\w.-]*autoimg\.cn/[^\"'\s<>)]+?\.(?:jpg|webp)", html)
    all_imgs = list(dict.fromkeys(
        u if u.startswith("http") else "https:" + u for u in raw))
    print(f"  total unique autoimg URLs: {len(all_imgs)}")
    sizes: dict[str, list] = {}
    for u in all_imgs:
        m = re.search(r"/([0-9]+x[0-9]+)_0_", u)
        sizes.setdefault(m.group(1) if m else "other", []).append(u)
    for sz, urls in sizes.items():
        print(f"    [{sz}]  {len(urls)} photos. sample: {urls[0][:130]}")

    # ─── 6. Verification / certification / badges ───
    print("\n=== TRUST / VERIFICATION SIGNALS ===")
    badge_keywords = [
        "认证二手车", "精选好车", "无重大事故", "事故车", "泡水车", "原版漆",
        "一手车", "原厂质保", "30天整车保修", "7天无理由", "15天包退",
        "30天包退", "180天质保", "1年质保", "检测", "111项", "保养记录",
        "维修记录", "出险记录", "里程核实", "VIN核实",
    ]
    found = []
    for kw in badge_keywords:
        c = html.count(kw)
        if c > 0:
            found.append(f"{kw}({c})")
    print("  found:", ", ".join(found) or "(none)")

    # ─── 7. Inline JS objects ───
    print("\n=== INLINE JS OBJECTS ===")
    for var in ["CONFIG", "carBaseInfo", "carInfo", "showdata", "pageData",
                "spuInfo", "infoData", "shareData"]:
        m = re.search(rf"\b{var}\s*=\s*(\{{.{{50,1500}}?\}});", html, re.DOTALL)
        if m:
            snippet = collapse(m.group(1))[:280]
            print(f"  [{var}] {snippet}")

    # ─── 8. Dealer / seller info ───
    print("\n=== DEALER ===")
    for sel in [".dealer", "[class*=dealer]", ".seller", ".shop"]:
        for el in soup.select(sel)[:2]:
            text = collapse(el.get_text(" "))
            if text and len(text) < 300:
                print(f"  [{sel}] {text[:250]}")
                break

    # ─── 9. Report links (maintenance, insurance) ───
    print("\n=== REPORT LINKS ===")
    for a in soup.find_all("a", href=True):
        h = a["href"]
        text = collapse(a.get_text())
        if any(kw in h for kw in ("maintenance", "vincode", "baoyang", "ccwz",
                                   "chebao", "weibao", "chuxian")):
            print(f"  · {text[:50]:50}  {h[:100]}")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
