"""normalize_cars_llm.py — second-pass normalizer for CN-source cars.

The first pass (`normalize_cars.py`) applies the hardcoded `chinese_maps`
dictionaries to translate brands/series/colors/fuels. Whatever falls
through (new EV brands, leaked CJK in model, missing engine_type) gets
picked up here: we ship the raw row to Kimi K2.6 via OpenRouter and write
back a canonical English `mark`/`model`, an `engine_type`, an optional
trim string, and an outlier flag.

Idempotent: only processes rows where `llm_normalized_at IS NULL` AND
source is one of (che168, guazi, autocango). After a successful update
we stamp `llm_normalized_at = now()`. Pass `--force` to re-process.

Run:
  python normalize_cars_llm.py                       # process all pending
  python normalize_cars_llm.py --limit 100           # smoke test
  python normalize_cars_llm.py --batch-size 50       # tune batch
  python normalize_cars_llm.py --source che168       # restrict
  python normalize_cars_llm.py --force --limit 20    # re-run on already-tagged

Env:
  SUPABASE_URL, SUPABASE_KEY (service role)
  OPENROUTER_API_KEY  — required, get at openrouter.ai/settings/keys
  OPENROUTER_MODEL    — optional override (default: moonshotai/kimi-k2.6)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v3.2-exp"  # was kimi-k2.6 — too slow/thinking
CN_SOURCES = ("che168", "guazi", "autocango")

# Allowed values for engine_type — anything else means LLM made one up
# and we drop it. Matches the existing taxonomy in `chinese_maps.FUEL_MAP`.
ALLOWED_ENGINE_TYPES = {
    "Petrol", "Diesel", "Electric", "EREV", "PHEV", "Hybrid",
    "Hydrogen", "CNG", "LPG",
}


SYSTEM_PROMPT = """You normalize Chinese used-car listings (from che168 /
guazi / autocango) into a canonical English schema for a Kazakhstan
import-marketplace.

For every row I send you, output ONE JSON object with these fields:

- "id": echo the integer id from input.
- "mark": canonical English brand name. Examples:
    宝马→"BMW", 奔驰→"Mercedes-Benz", 比亚迪→"BYD", 理想/Li Auto→"Li Auto",
    问界→"AITO", 蔚来→"NIO", 极氪→"Zeekr", 岚图→"Voyah",
    哈弗→"Haval", 长城→"Great Wall", 红旗→"Hongqi",
    五菱→"Wuling", 长安→"Changan", 吉利→"Geely",
    奇瑞→"Chery", 领克→"Lynk & Co", 小米→"Xiaomi".
  For obscure niche brands use the manufacturer's official English name
  (not pinyin). If you genuinely cannot identify the brand, set "drop":true.

- "model": canonical English model name WITHOUT trim or engine code.
    "5系"→"5 Series", "X5"→"X5", "汉EV"→"Han EV", "唐DM"→"Tang DM",
    "途观L"→"Tiguan L", "凯美瑞"→"Camry", "卡宴新能源"→"Cayenne EV",
    "理想L9"→"L9", "问界M9"→"M9", "Model 3"→"Model 3", "i5"→"i5".
  STRIP year-trim suffix like "2024款" entirely. STRIP trim words like
  "尊享型", "豪华版", "MAX", "Ultra", "M Sport", "AWD", "Long Wheelbase"
  from the model — those go into "complectation" instead.

- "complectation": the trim/spec descriptor in English, e.g.
    "530Li xDrive M Sport Executive", "AWD Long Range", "Ultra 6-seat".
  Empty string if there is no clear trim.

- "engine_type": EXACTLY one of:
    "Petrol" | "Diesel" | "Electric" | "EREV" | "PHEV" | "Hybrid"
    | "Hydrogen" | "CNG" | "LPG"
  Rules:
    EREV = engine ONLY generates electricity, wheels driven by motor
           (Li Auto L-series, Voyah Free EREV, AITO M5/M7/M9 EREV, AITO,
            Stelato S9 EREV, Maextro S800 EREV, 增程式).
    PHEV = plug-in hybrid where ICE can drive wheels (Tang DM, RAV4 PHEV,
           Cayenne E-Hybrid, BMW xDrive45e).
    Hybrid = classical HEV / MHEV without plug (Toyota Prius non-plug,
             Camry Hybrid, Lexus RX 450h).
    Electric = pure BEV.
    Petrol/Diesel = ICE-only.
  If the row has fuel_original like "汽油" → Petrol, "纯电动" → Electric,
  "插电混动" → PHEV, "增程式" → EREV — use that directly. Only override
  when title/model implies otherwise (e.g. Li Auto L9 is always EREV
  regardless of what fuel field says).

- "drop": true ONLY if this row is hopelessly broken — empty title,
  obvious test entry, or you cannot reasonably identify brand+model.
  Otherwise false. Be conservative: prefer to keep & guess than to drop.

- "confidence": float 0.0–1.0 — how sure you are about mark+model. <0.5
  means we should flag for manual review.

Output a JSON ARRAY of these objects, one per input row, in the SAME
ORDER. No markdown fences, no commentary, no trailing comma. Just the
raw JSON array."""


def fetch_pending(limit: int | None, source_filter: str | None,
                  force: bool) -> list[dict]:
    """Pull rows that still need normalization."""
    select = ("id,source,source_id,title,mark,mark_original,model,"
              "series_original,complectation,fuel_original,engine_type,year,"
              "displacement,llm_normalized_at")
    params = [f"select={select}", "order=id.desc"]
    if source_filter:
        params.append(f"source=eq.{source_filter}")
    else:
        params.append(f"source=in.({','.join(CN_SOURCES)})")
    if not force:
        params.append("llm_normalized_at=is.null")
    if limit:
        params.append(f"limit={limit}")
    r = DB._pg_request("GET", "cars?" + "&".join(params))
    if r.status_code != 200:
        sys.exit(f"DB read fail: {r.status_code} {r.text[:200]}")
    return r.json()


def build_user_message(rows: list[dict]) -> str:
    """Compact JSON-lines representation. One row per line keeps tokens
    low and makes per-row debugging straightforward."""
    compact = []
    for r in rows:
        compact.append(json.dumps({
            "id": r["id"],
            "title": r.get("title") or "",
            "mark_zh": r.get("mark_original") or "",
            "series_zh": r.get("series_original") or "",
            "mark_now": r.get("mark") or "",
            "model_now": r.get("model") or "",
            "trim_now": r.get("complectation") or "",
            "fuel_zh": r.get("fuel_original") or "",
            "engine_now": r.get("engine_type") or "",
            "year": r.get("year"),
            "disp": r.get("displacement"),
        }, ensure_ascii=False))
    return "Rows:\n" + "\n".join(compact)


def call_llm(rows: list[dict], api_key: str, model: str
             ) -> list[dict]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(rows)},
        ],
        # Don't force response_format=json_object here — Kimi sometimes
        # returns empty content when it can't fit the wrapper. The system
        # prompt already mandates a raw JSON array, which is what we parse.
        "temperature": 0.0,
        "max_tokens": 8192,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/dexterkexter/poisk_avto",
        "X-Title": "poisk_avto normalize",
    }
    r = requests.post(OPENROUTER_URL, json=body, headers=headers, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:400]}")
    payload = r.json()
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"unexpected payload shape: "
                           f"{json.dumps(payload)[:800]}")
    if text is None:
        # Some providers return content=null and put text in `reasoning`
        # or `tool_calls`. Log the full payload so we can diagnose.
        raise RuntimeError(f"content=None, payload: "
                           f"{json.dumps(payload)[:800]}")
    text = text.strip()
    # Strip ```json fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3].strip()
    # Find first '[' and last ']' to slice out the array — Kimi sometimes
    # leaks one short sentence before/after even with a strict prompt.
    lb = text.find("[")
    rb = text.rfind("]")
    if lb >= 0 and rb > lb:
        text = text[lb: rb + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        # Dump first 1500 chars so we can see whether model truncated,
        # forgot to close a string, etc.
        raise RuntimeError(
            f"JSON parse failed ({e}); first 1500 chars of raw text: "
            f"{text[:1500]!r}"
        ) from None
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list):
                parsed = v
                break
        else:
            parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"LLM returned non-array: {type(parsed)}")
    return parsed


def apply_update(row_id: int, verdict: dict) -> bool:
    """PATCH cars with LLM's verdict. Validates engine_type."""
    update: dict = {"llm_normalized_at": DB.now_iso()}
    if verdict.get("drop"):
        # Stamp the row but don't change anything; future scrapes may
        # bring more data and we'll re-evaluate then.
        pass
    else:
        m = verdict.get("mark") or None
        mo = verdict.get("model") or None
        eng = verdict.get("engine_type") or None
        trim = verdict.get("complectation")
        if m: update["mark"] = m
        if mo: update["model"] = mo
        if eng in ALLOWED_ENGINE_TYPES:
            update["engine_type"] = eng
        if trim is not None and trim != "":
            update["complectation"] = trim
    r = DB._pg_request("PATCH", f"cars?id=eq.{row_id}", json=update)
    return r.status_code in (200, 204)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--source", default=None,
                    choices=list(CN_SOURCES) + [None])
    ap.add_argument("--force", action="store_true",
                    help="re-normalize rows even if already stamped")
    ap.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL",
                                                      DEFAULT_MODEL))
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        sys.exit("OPENROUTER_API_KEY env var is required")
    if not DB.USE_POSTGRES:
        sys.exit("Need Supabase (USE_POSTGRES)")

    rows = fetch_pending(args.limit, args.source, args.force)
    print(f"Pending rows: {len(rows)}; model={args.model}; "
          f"batch={args.batch_size}", flush=True)
    if not rows:
        return

    start = time.time()
    ok_total = drop_total = fail_total = 0
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i: i + args.batch_size]
        try:
            verdicts = call_llm(batch, api_key, args.model)
        except Exception as e:
            print(f"  ! batch {i // args.batch_size} LLM call failed: {e}",
                  flush=True)
            fail_total += len(batch)
            continue

        # LLM should return one verdict per input row. Map by id.
        by_id = {int(v.get("id", -1)): v for v in verdicts if isinstance(v, dict)}
        for row in batch:
            v = by_id.get(row["id"])
            if v is None:
                fail_total += 1
                continue
            if v.get("drop"):
                drop_total += 1
            if apply_update(row["id"], v):
                ok_total += 1
            else:
                fail_total += 1

        done = min(i + args.batch_size, len(rows))
        rate = done / max(time.time() - start, 1e-3)
        eta = (len(rows) - done) / max(rate, 1e-3)
        print(f"  [{done}/{len(rows)}]  ok={ok_total} drop={drop_total} "
              f"fail={fail_total}  {rate:.1f} rows/s  ETA {eta / 60:.1f} min",
              flush=True)

    print(f"\nDone in {(time.time() - start) / 60:.1f} min. "
          f"Updated: {ok_total}; dropped (kept as-is): {drop_total}; "
          f"failed: {fail_total}",
          flush=True)


if __name__ == "__main__":
    main()
