# Poisk Avto — мульти-источник парсер автомобилей для импорта в КЗ

Парсер объявлений с трёх китайских и одного корейского сайтов, плюс справочник брендов. Цель: показать клиенту из Казахстана **готовые к ввозу** машины с реальными ценами, фото, VIN и историей.

База — Supabase Postgres. Парсеры — Python + GitHub Actions. Стоимость инфры — **~$200/мес** (Oxylabs только для dongchedi).

## Что сейчас в репо

```
poisk_avto/
├── README.md                        # этот файл
├── README_dongchedi.md              # 🇨🇳 китайский б/у — Oxylabs render
├── README_encar.md                  # 🇰🇷 корейский б/у — direct HTTP, $0
├── README_autocango.md              # 🇨🇳 китайский экспорт — playwright, $0
│
├── db.py                            # Supabase REST API + SQLite fallback
├── requirements.txt                 # 1 строка: requests
├── requirements-scrapling.txt       # playwright (только для autocango)
│
├── collect_ids.py                   # dongchedi listing collector
├── scrape_dongchedi.py              # dongchedi card scraper
├── refresh_cars.py                  # sold detection + price drops (dongchedi)
│
├── collect_encar.py                 # encar listing (direct HTTP)
├── scrape_encar.py                  # encar cards (direct HTTP)
│
├── collect_autocango.py             # autocango listings (playwright + filters)
├── scrape_autocango.py              # autocango cards (playwright + full-res)
├── import_brands_autocango.py       # /ucbrand → brands table
├── enrich_brand_logos.py            # дотянуть 268 недостающих лого
│
└── .github/workflows/
    ├── scrape.yml                   # dongchedi daily 19:00 UTC
    ├── refresh.yml                  # dongchedi weekly sold/price refresh
    ├── scrape-encar.yml             # encar daily 20:00 UTC
    ├── scrape-autocango.yml         # autocango daily 21:00 UTC
    └── import-brands.yml            # brand catalog weekly Mon 22:00 UTC
```

## Архитектура одной фразой

**Multi-source schema (`cars` + `pending_ids` + `changes` + `brands`)** наполняется параллельно из 3 парсеров с разными технологиями (Oxylabs / direct HTTP / playwright), а Postgres-view `cars_export_eligibility` поверх считает готовность к экспорту по китайскому 180-day rule.

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ dongchedi.com    │   │ encar.com        │   │ autocango.com    │
│ (Oxylabs render) │   │ (direct HTTP)    │   │ (playwright)     │
│ б/у Китай        │   │ б/у Корея + VIN  │   │ б/у Китай export │
└────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
         │                      │                      │
         │ collect → scrape     │ collect → scrape     │ collect → scrape
         │                      │                      │
         ▼                      ▼                      ▼
┌────────────────────────────────────────────────────────────────┐
│                  Supabase Postgres                              │
│                                                                 │
│  pending_ids ───┐                                              │
│                  ↓                                              │
│  cars ─────── ← scrapers populate                              │
│   ├─ source='dongchedi' / 'encar' / 'autocango'                │
│   ├─ source_id, source_language, *_original/* fields           │
│   ├─ price_original + price_currency (no FX conversion)        │
│   ├─ km_age, vin, sold_at, refresh_failed_attempts             │
│   ├─ published_at, listing_updated_at                          │
│   ├─ source_data JSONB (per-source extras: options, MSRP, etc) │
│   └─ images JSONB array                                        │
│                                                                 │
│  changes ─── price_drop, sold (from refresh_cars.py)           │
│                                                                 │
│  brands ─── 303 brands × 296 logos (autocango)                 │
│  models ─── (зарезервировано)                                  │
│                                                                 │
│  Views:                                                         │
│    cars_kz_view              ← year≥2022, не EV                │
│    cars_export_eligibility   ← 180-day rule, days_until_*       │
└────────────────────────────────────────────────────────────────┘
```

## Источники в цифрах

| Источник | База сейчас | Метод | Стоимость/мес | Спец.фишка |
|---|---|---|---|---|
| **dongchedi** | 1,879 машин | Oxylabs `render=html` + XHR | ~$200 | massive inventory, brand×city |
| **encar** | 1,058 машин | **direct HTTP** | **$0** | VIN, ДТП-отчёты, корейские |
| **autocango** | 55+ машин | playwright + DOM | **$0** | FOB USD, original paint, 180-day flag |
| **brands** | 303 (296 с лого) | playwright | $0 | каталог для фронта |
| **ИТОГО** | **~3,000 машин** | — | **~$200/мес** | live live live |

## Таблицы Supabase

### `cars` — главная multi-source таблица

Универсальные поля + JSONB для source-specific:

| Поле | Тип | Что |
|---|---|---|
| `id` | bigserial PK | автоинкремент |
| `source` + `source_id` | text, UNIQUE | составной ключ (`dongchedi`/`encar`/`autocango` + sku_id) |
| `source_language` | text | `zh` / `ko` / `en` |
| `*_original` / `*` | text | значение на языке источника / нормализовано в латиницу |
| `price_original` + `price_currency` | numeric + text | без конвертации — фронт делает |
| `km_age_original` + `km_age_unit` + `km_age` | numeric + text + numeric | пробег нормализован для cross-market фильтров |
| `vin` | text | пока только encar/autocango заполняют |
| `images` | jsonb | массив URL |
| `source_data` | jsonb | per-source extras (опции, MSRP, ДТП, accessories, etc) |
| `first_seen` / `last_seen` | timestamptz | первая/последняя успешная парсинга |
| `sold_at` | timestamptz | NULL если в продаже |
| `refresh_failed_attempts` | int | counter для weekly sold-detection |
| `published_at` / `listing_updated_at` | timestamptz | даты публикации/правки объявления (encar — real, dongchedi — proxy через first_seen) |

### `pending_ids` — очередь на парсинг карточек

```sql
source TEXT, source_id TEXT,
metadata JSONB,            -- snapshot из listing
found_at TIMESTAMPTZ,
failed_attempts INT,        -- после 3 → quarantine
last_failed_at TIMESTAMPTZ,
PRIMARY KEY (source, source_id)
```

### `changes` — лента событий

```sql
id BIGSERIAL PK,
source, source_id,
change_type TEXT,           -- 'price_drop' | 'sold'
old_value JSONB, new_value JSONB,
created_at TIMESTAMPTZ
```

### `brands` — нормализованный каталог брендов

```sql
id BIGSERIAL PK,
slug TEXT,                  -- 'BMW', 'BYD', 'Land Rover'
name TEXT,
logo_url TEXT,              -- https://i1.autocango.com/brand/CODE.webp
country TEXT,
source TEXT,                -- 'autocango' (пока)
source_url TEXT,
created_at, updated_at TIMESTAMPTZ,
UNIQUE (source, slug)
```

### `models` — модели брендов

Создана, пока пуста. Будет наполняться когда подключим model-extraction (drill через brand-pages).

### Views

- **`cars_kz_view`** — `kz_importable` (год≥2022 AND не Electric), `evro_class`, `age_years`, `kz_status`
- **`cars_export_eligibility`** — `days_since_reg`, `days_until_export_eligible`, `export_status`, `is_export_eligible`

## Расписание GitHub Actions

| Workflow | Cron | Что |
|---|---|---|
| `Scrape Dongchedi` | `0 19 * * *` | каждый день 19:00 UTC (03:00 Пекин) — collect + scrape |
| `Scrape Encar` | `0 20 * * *` | каждый день 20:00 UTC (05:00 Сеул) — collect + scrape |
| `Scrape AutoCango` | `0 21 * * *` | каждый день 21:00 UTC (05:00 Пекин) — 6 cities + filters |
| `Refresh Dongchedi (sold + price drops)` | `0 22 * * 0` | воскресенье 22:00 UTC — full re-check |
| `Import brands (autocango)` | `0 22 * * 1` | понедельник 22:00 UTC — refresh brand catalog |

Все можно запустить вручную через **workflow_dispatch** в Actions UI.

## Secrets

| Secret | Используется в |
|---|---|
| `SUPABASE_URL` | везде |
| `SUPABASE_KEY` (service_role JWT) | везде |
| `OXY_USER` | dongchedi only |
| `OXY_PASS` | dongchedi only |

## Стоимость по факту

| Парсер | Что платим | Сумма |
|---|---|---|
| dongchedi daily collect | Oxylabs render×316 URL | ~$12/день |
| dongchedi scrape карточек | Oxylabs render×~800 | ~$32/день |
| dongchedi weekly refresh | Oxylabs render×~1500 | ~$55/неделя |
| encar | direct HTTP | $0 |
| autocango | playwright (GH Actions free tier) | $0 |
| **Итого** | | **~$200/мес** |

## Roadmap

- [ ] Frontend dashboard (Next.js + Vercel) — кнопки запуска парсеров, KPI, browse cars
- [ ] dongchedi через китайский residential proxy (-$170/мес vs Oxylabs)
- [ ] autocango `/newcar` парсер (НОВЫЕ китайские машины)
- [ ] Models per brand (303 страниц brand → models table)
- [ ] Корейский `che168.com` (б/у с VIN, альтернатива encar для китайских машин)

## Документация по источникам

Per-site README в корне репо:
- [`README_dongchedi.md`](./README_dongchedi.md) — китайский б/у через Oxylabs
- [`README_encar.md`](./README_encar.md) — корейский б/у через direct HTTP
- [`README_autocango.md`](./README_autocango.md) — китайский экспорт через playwright
