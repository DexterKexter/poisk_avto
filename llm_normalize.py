"""
Brand/model normaliser: deterministic resolver + LLM fallback.

Pipeline for matching scraped cars to OUR brands/models catalog:

  1. Pull cars that still lack model_id (and not yet LLM-processed).
  2. Collapse to unique (mark, model) spellings.
  3. For each unique spelling:
       a. catalog_aliases cache hit?            -> use it (free)
       b. deterministic match (normalized name/slug, brand aliases)? -> use it,
          record a 'rule' alias
       c. otherwise ask the LLM, giving ONLY that brand's catalog models as
          candidates; it must pick a model_id from the list or return null.
          Record an 'llm' alias.
  4. Write brand_id / model_id back to every car with that spelling, plus
     llm_suggestion + llm_normalized_at; low-confidence / no-match -> quarantine.

The LLM (default qwen/qwen3.6-flash via OpenRouter) never invents ids — it only
chooses from the candidate list we pass, so output is always a valid catalog id
or an explicit "no match".

Usage:
  python llm_normalize.py [--limit 500] [--model qwen/qwen3.6-flash]
                          [--min-confidence 0.6] [--dry-run] [--no-llm]

Env: SUPABASE_URL, SUPABASE_KEY, OPENROUTER_API_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.6-flash"

_brands: list[dict] = []          # [{id,name,slug}]
_models_by_brand: dict[int, list[dict]] = defaultdict(list)
_brand_idx: dict[str, int] = {}   # norm(name|slug) -> brand_id
_model_idx: dict[tuple[int, str], int] = {}  # (brand_id, norm) -> model_id
_alias_cache: dict[tuple[str, str], dict] = {}


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch_all(path: str, page: int = 1000) -> list[dict]:
    """Page through PostgREST (Supabase caps responses at ~1000 rows)."""
    out: list[dict] = []
    offset = 0
    sep = "&" if "?" in path else "?"
    while True:
        r = DB._pg_request("GET", f"{path}{sep}limit={page}&offset={offset}")
        if r.status_code != 200:
            break
        batch = r.json()
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


# ---------- load catalog ----------

def load_catalog() -> None:
    for b in fetch_all("brands?select=id,name,slug"):
        _brands.append(b)
        _brand_idx[norm(b["name"])] = b["id"]
        _brand_idx[norm(b["slug"])] = b["id"]
    for m in fetch_all("models?select=id,brand_id,name,slug"):
        if m.get("brand_id"):
            _models_by_brand[m["brand_id"]].append(m)
            _model_idx[(m["brand_id"], norm(m["name"]))] = m["id"]
            _model_idx[(m["brand_id"], norm(m["slug"]))] = m["id"]
    for a in fetch_all("catalog_aliases?select=mark_norm,model_norm,brand_id,model_id"):
        _alias_cache[(a["mark_norm"], a["model_norm"])] = a
    print(f"  catalog: {len(_brands)} brands, "
          f"{sum(len(v) for v in _models_by_brand.values())} models, "
          f"{len(_alias_cache)} aliases")


# ---------- deterministic resolver ----------

def resolve_brand(mark: str) -> int | None:
    return _brand_idx.get(norm(mark))


def resolve_model(brand_id: int | None, *names: str) -> int | None:
    if not brand_id:
        return None
    for n in names:
        mid = _model_idx.get((brand_id, norm(n)))
        if mid:
            return mid
    return None


# ---------- LLM fallback ----------

def llm_match(raw: dict, brand: dict, candidates: list[dict], model: str) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"model_id": None, "confidence": 0, "reason": "no OPENROUTER_API_KEY"}

    cand_lines = "\n".join(f'  {{"id": {c["id"]}, "name": "{c["name"]}"}}'
                           for c in candidates)
    prompt = (
        "You match a used-car listing to OUR model catalog.\n"
        f"Brand: {brand['name']} (id {brand['id']}).\n"
        "Listing raw fields:\n"
        f"  mark: {raw.get('mark')!r}\n"
        f"  model: {raw.get('model')!r}\n"
        f"  complectation: {raw.get('complectation')!r}\n"
        f"  title: {raw.get('title')!r}\n\n"
        "Candidate models (choose the model_id from THIS list only):\n"
        f"[\n{cand_lines}\n]\n\n"
        "Return STRICT JSON, no prose:\n"
        '{"model_id": <id from list or null>, "trim_badge": "<engine/trim like '
        '530Li, C200, or null>", "confidence": <0..1>, "reason": "<short>", '
        '"new_model_name": "<canonical name if none matches, else null>"}'
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(OPENROUTER_URL, timeout=60,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json=body)
        if r.status_code != 200:
            return {"model_id": None, "confidence": 0,
                    "reason": f"http {r.status_code}: {r.text[:120]}"}
        content = r.json()["choices"][0]["message"]["content"]
        out = json.loads(content)
        # guard: model_id must be one of the candidates
        valid = {c["id"] for c in candidates}
        if out.get("model_id") not in valid:
            out["model_id"] = None
        return out
    except Exception as e:
        return {"model_id": None, "confidence": 0, "reason": f"error: {e}"}


# ---------- write-back ----------

def save_alias(mark_n, model_n, brand_id, model_id, decided_by, conf, raw, llm_raw=None):
    DB._pg_request("POST", "catalog_aliases?on_conflict=mark_norm,model_norm", json={
        "mark_norm": mark_n, "model_norm": model_n,
        "brand_id": brand_id, "model_id": model_id,
        "decided_by": decided_by, "confidence": conf,
        "raw_mark": raw.get("mark"), "raw_model": raw.get("model"),
        "llm_raw": llm_raw, "updated_at": DB.now_iso(),
    })


def apply_to_cars(mark, model, brand_id, model_id, llm_raw, dry):
    patch = {"llm_normalized_at": DB.now_iso()}
    if brand_id:
        patch["brand_id"] = brand_id
    if model_id:
        patch["model_id"] = model_id
    if llm_raw is not None:
        patch["llm_suggestion"] = llm_raw
    if dry:
        return
    # match every car with this exact raw spelling
    q = (f"cars?mark=eq.{requests.utils.quote(mark)}"
         f"&model=eq.{requests.utils.quote(model)}")
    DB._pg_request("PATCH", q, json=patch)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500,
                    help="Max unique (mark,model) spellings to process")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-confidence", type=float, default=0.6)
    ap.add_argument("--no-llm", action="store_true",
                    help="Deterministic only; skip the LLM fallback")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    print("Loading catalog…")
    load_catalog()

    # unresolved cars -> unique (mark, model) spellings
    rows = fetch_all(
        "cars?select=mark,model,complectation,title"
        "&model_id=is.null&llm_normalized_at=is.null"
        "&mark=not.is.null&model=not.is.null")
    uniq: dict[tuple[str, str], dict] = {}
    for row in rows:
        uniq.setdefault((row["mark"], row["model"]), row)
    spellings = list(uniq.items())[:args.limit]
    print(f"  {len(rows)} unresolved cars -> {len(uniq)} unique spellings "
          f"(processing {len(spellings)})")

    n_rule = n_llm = n_none = 0
    for (mark, model), raw in spellings:
        mk, mdl = norm(mark), norm(model)

        cached = _alias_cache.get((mk, mdl))
        if cached and cached.get("model_id"):
            apply_to_cars(mark, model, cached["brand_id"], cached["model_id"], None, args.dry_run)
            continue

        brand_id = resolve_brand(mark)
        model_id = resolve_model(brand_id, model, raw.get("complectation") or "")

        if model_id:
            n_rule += 1
            if not args.dry_run:
                save_alias(mk, mdl, brand_id, model_id, "rule", 1.0, raw)
            apply_to_cars(mark, model, brand_id, model_id, None, args.dry_run)
            print(f"  rule  [{mark} / {model}] -> brand={brand_id} model={model_id}")
            continue

        if args.no_llm or not brand_id:
            n_none += 1
            print(f"  skip  [{mark} / {model}] brand={brand_id} (no model match)")
            continue

        # LLM fallback with this brand's candidate models
        brand = next((b for b in _brands if b["id"] == brand_id), None)
        cands = _models_by_brand.get(brand_id, [])
        out = llm_match(raw, brand, cands, args.model)
        mid = out.get("model_id")
        conf = float(out.get("confidence") or 0)
        if mid and conf >= args.min_confidence:
            n_llm += 1
            if not args.dry_run:
                save_alias(mk, mdl, brand_id, mid, "llm", conf, raw, out)
            apply_to_cars(mark, model, brand_id, mid, out, args.dry_run)
            print(f"  llm   [{mark} / {model}] -> model={mid} conf={conf} "
                  f"({out.get('reason','')[:50]})")
        else:
            n_none += 1
            print(f"  none  [{mark} / {model}] llm={out.get('model_id')} "
                  f"conf={conf} ({out.get('reason','')[:60]})")

    print(f"\nDone. rule={n_rule}, llm={n_llm}, unresolved={n_none}"
          f"{' (dry-run)' if args.dry_run else ''}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
