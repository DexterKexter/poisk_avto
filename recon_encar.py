"""
recon_encar.py — one-shot probe of encar.com to map parser strategy.

For each target URL fires an Oxylabs request, then dumps:
  - HTTP / Oxylabs status, final URL after redirects, content length
  - First 16 KB of response (HTML or JSON) → recon_artifacts/<name>_head.*
  - __NEXT_DATA__ JSON keys if present
  - JSON-LD blocks count
  - Captured XHR list (URL, method, status, response size) when xhr=true
  - All API-looking XHR bodies → recon_artifacts/<name>_xhr_api.json
  - Per-target summary JSON → recon_artifacts/<name>_summary.json

Total per run: ~6 targets × $0.04 ≈ $0.25.

Run from GitHub Actions (workflow: recon-encar.yml) — artifacts get uploaded
and can be downloaded from the run page.

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


# Set of URL patterns we want to probe.
# - Legacy "dc_" / "fc_" URLs: encar's old-style listings.
# - "car.encar.com": newer SPA-style listing UI.
# - "api.encar.com": semi-public search/readside API (no token, was open).
# - Mobile/v1 endpoints: another known surface.
#
# If a target returns useful JSON via API directly — we save ~10x cost
# vs render=html and skip browser entirely.
TARGETS = [
    {
        "name": "01_homepage",
        "url": "http://www.encar.com/",
        "render": "html",
        "xhr": False,
    },
    {
        "name": "02_list_legacy_kor",
        "url": "http://www.encar.com/dc/dc_carsearchlist.do?carType=kor",
        "render": "html",
        "xhr": True,
        "scrolls": 3,
    },
    {
        "name": "03_list_legacy_imp",
        "url": "http://www.encar.com/fc/fc_carsearchlist.do?carType=for",
        "render": "html",
        "xhr": True,
        "scrolls": 3,
    },
    {
        "name": "04_list_new_ui",
        "url": "https://car.encar.com/list/car?count=20&q=%28And.Hidden.N._.CarType.Y.%29",
        "render": "html",
        "xhr": True,
        "scrolls": 3,
    },
    {
        "name": "05_api_premium",
        "url": (
            "http://api.encar.com/search/car/list/premium"
            "?count=true&q=%28And.Hidden.N._.CarType.Y.%29"
            "&sr=%7CMobileModified%7C0%7C20"
        ),
        "render": None,
        "xhr": False,
    },
    {
        "name": "06_api_general",
        "url": (
            "http://api.encar.com/search/car/list/general"
            "?count=true&q=%28And.Hidden.N._.CarType.A.%29"
            "&sr=%7CMobileModified%7C0%7C20"
        ),
        "render": None,
        "xhr": False,
    },
    {
        "name": "07_api_readside",
        "url": "https://api.encar.com/v1/readside/vehicle/list?count=20",
        "render": None,
        "xhr": False,
    },
]

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
JSON_LD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
INITIAL_STATE_RE = re.compile(
    r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', re.DOTALL
)


def probe(t: dict) -> dict:
    payload: dict = {
        "source": "universal",
        "url": t["url"],
        "geo_location": "South Korea",
    }
    if t.get("render"):
        payload["render"] = t["render"]
    if t.get("xhr"):
        payload["xhr"] = True
        payload["browser_instructions"] = [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(t.get("scrolls", 3))
        ]

    print(f"\n=== {t['name']} ===")
    print(f"URL: {t['url']}")
    print(f"  render={payload.get('render')}, xhr={payload.get('xhr', False)}")

    try:
        r = requests.post(
            OXY_URL, auth=(OXY_USER, OXY_PASS),
            json=payload, timeout=300,
        )
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return {"target": t["name"], "error": str(e)}

    summary: dict = {
        "target": t["name"],
        "url_requested": t["url"],
        "payload_render": payload.get("render"),
        "payload_xhr": payload.get("xhr", False),
        "oxylabs_http": r.status_code,
    }

    if r.status_code != 200:
        summary["error"] = r.text[:500]
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        _dump_summary(t["name"], summary)
        return summary

    try:
        data = r.json()
    except Exception as e:
        summary["error"] = f"oxy json: {e}"
        return summary

    results = data.get("results", []) or []
    summary["num_results"] = len(results)
    if not results:
        summary["error"] = "no results"
        _dump_summary(t["name"], summary)
        return summary

    # Primary content result (skip XHR ones for now).
    main = next((res for res in results if res.get("type") != "xhr"), results[0])
    summary["target_status"] = main.get("status_code")
    summary["url_final"] = main.get("url")

    content = main.get("content")
    if isinstance(content, dict):
        # JSON content (direct API)
        summary["content_type"] = "json_dict"
        summary["json_top_keys"] = list(content.keys())[:30]
        head_path = os.path.join(OUT_DIR, f"{t['name']}_head.json")
        with open(head_path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        summary["head_saved"] = head_path
    elif isinstance(content, str):
        summary["content_type"] = "string"
        summary["content_length"] = len(content)
        stripped = content.lstrip()[:1]
        is_html = stripped in ("<",)
        is_json = stripped in ("{", "[")
        summary["looks_like"] = "html" if is_html else ("json" if is_json else "other")

        head_ext = ".html" if is_html else (".json" if is_json else ".txt")
        head_path = os.path.join(OUT_DIR, f"{t['name']}_head{head_ext}")
        with open(head_path, "w", encoding="utf-8") as f:
            f.write(content[:16000])
        summary["head_saved"] = head_path

        if is_html:
            m = NEXT_DATA_RE.search(content)
            if m:
                try:
                    nd = json.loads(m.group(1))
                    summary["next_data_keys"] = list(nd.keys())
                    summary["next_data_size"] = len(m.group(1))
                    nd_path = os.path.join(OUT_DIR, f"{t['name']}_next_data.json")
                    with open(nd_path, "w", encoding="utf-8") as f:
                        json.dump(nd, f, ensure_ascii=False, indent=2)
                    summary["next_data_saved"] = nd_path
                except Exception:
                    summary["next_data_invalid"] = True

            init = INITIAL_STATE_RE.search(content)
            if init:
                summary["initial_state_found"] = True
                summary["initial_state_size"] = len(init.group(1))

            jsonld = JSON_LD_RE.findall(content)
            summary["jsonld_blocks"] = len(jsonld)

            if is_json or "{" in content[:200]:
                # Sometimes HTML wraps a small JSON; not relevant.
                pass
        elif is_json:
            try:
                obj = json.loads(content)
                if isinstance(obj, dict):
                    summary["json_top_keys"] = list(obj.keys())[:30]
                elif isinstance(obj, list):
                    summary["json_top_type"] = "list"
                    summary["json_list_len"] = len(obj)
                    if obj and isinstance(obj[0], dict):
                        summary["json_list_item_keys"] = list(obj[0].keys())[:30]
            except Exception:
                summary["json_parse_error"] = True
    else:
        summary["content_type"] = f"other:{type(content).__name__}"

    # XHR captures from a render+xhr request.
    xhr_blocks = [res for res in results if res.get("type") == "xhr"]
    if xhr_blocks:
        captured = xhr_blocks[0].get("content", []) or []
        summary["xhr_count"] = len(captured)
        xhr_summary = []
        api_calls = []
        for req in captured:
            url = req.get("url", "") or ""
            xhr_summary.append({
                "method": req.get("method"),
                "url": url[:200],
                "status": req.get("status_code"),
                "resp_size": len(req.get("response_body") or ""),
            })
            if ("/api" in url or "search" in url.lower()
                    or "vehicle" in url.lower() or "list" in url.lower()):
                api_calls.append(req)
        summary["xhr_sample"] = xhr_summary[:30]
        if api_calls:
            api_path = os.path.join(OUT_DIR, f"{t['name']}_xhr_api.json")
            with open(api_path, "w", encoding="utf-8") as f:
                json.dump(api_calls, f, ensure_ascii=False, indent=2)
            summary["xhr_api_saved"] = api_path
            summary["xhr_api_count"] = len(api_calls)

    _dump_summary(t["name"], summary)
    print(f"  → target_status={summary.get('target_status')} "
          f"content_type={summary.get('content_type')} "
          f"looks_like={summary.get('looks_like')} "
          f"xhr={summary.get('xhr_count', 0)} "
          f"next_data={'yes' if summary.get('next_data_keys') else 'no'}")
    return summary


def _dump_summary(name: str, summary: dict) -> None:
    path = os.path.join(OUT_DIR, f"{name}_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    print(f"Probing {len(TARGETS)} targets on encar.com via Oxylabs (geo=South Korea)")
    all_summaries: dict = {}
    for t in TARGETS:
        all_summaries[t["name"]] = probe(t)

    index_path = os.path.join(OUT_DIR, "_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(all_summaries, f, ensure_ascii=False, indent=2)

    print("\n\n=== RECON DONE ===")
    print(f"Artifacts saved to ./{OUT_DIR}/")
    print("Upload them via 'actions/upload-artifact' (the workflow does this).")
    print("\nQuick verdict per target (see *_summary.json for details):")
    for name, s in all_summaries.items():
        verdict = []
        if s.get("error"):
            verdict.append(f"ERROR: {s['error'][:60]}")
        else:
            verdict.append(f"http={s.get('target_status')}")
            verdict.append(f"type={s.get('content_type')}")
            if s.get("looks_like"):
                verdict.append(f"is={s['looks_like']}")
            if s.get("next_data_keys"):
                verdict.append("__NEXT_DATA__:yes")
            if s.get("xhr_api_count"):
                verdict.append(f"xhr_api={s['xhr_api_count']}")
        print(f"  {name}: {' | '.join(verdict)}")


if __name__ == "__main__":
    main()
