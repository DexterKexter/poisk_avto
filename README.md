# Poisk Avto — мульти-источник парсер автомобилей для импорта в КЗ

Парсер объявлений с **4 источников** (3 китайских + 1 корейский), плюс справочник брендов/моделей. Цель: показать клиенту из Казахстана **готовые к ввозу** машины с реальными ценами, фото, VIN и историей.

База — Supabase Postgres. Парсеры — Python + GitHub Actions. **Стоимость инфры — $0/мес** (всё на direct HTTP + playwright, без платных проксей).

## Что сейчас в репо

```
poisk_avto/
├── README.md                   # этот файл
├── README_che168.md            # 🇨🇳 dealer-площадка, VIN + reports
├── README_guazi.md             # 🇨🇳 C2C с детальным inspection scorecard
├── README_encar.md             # 🇰🇷 корейский б/у — VIN, ДТП-отчёты
├── README_autocango.md         # 🇨🇳 экспорт, FOB USD
│
├── db.py                       # Supabase REST API + SQLite fallback
├── chinese_maps.py             # CN→EN brand/color/fuel/transmission/drive maps
├── requirements.txt            # requests
├── requirements-scrapling.txt  # + playwright (che168, autocango)
│
├── collect_che168.py           # playwright, 6 cities + filters
├── scrape_che168.py            # playwright, VIN + photos + trust badges
│
├── collect_guazi.py            # direct HTTP, fast
├── scrape_guazi.py             # direct HTTP, parallel workers
│
├── collect_encar.py            # direct HTTP
├── scrape_encar.py             # direct HTTP, Full HD photos
│
├── collect_autocango.py        # playwright + filters
├── scrape_autocango.py         # playwright + full-res
├── import_brands_autocango.py  # справочник брендов
├── import_model_specs.py       # справочник моделей (model_variants)
├── enrich_brand_logos.py       # лого брендов
│
└── .github/workflows/
    ├── scrape-che168.yml       # daily 19:30 UTC
    ├── scrape-guazi.yml        # daily 20:30 UTC
    ├── scrape-encar.yml        # daily 20:00 UTC
    ├── scrape-autocango.yml    # daily 21:00 UTC
    ├── import-brands.yml       # weekly Mon 22:00 UTC
    └── import-model-specs.yml  # monthly + dispatch
```

## Архитектура одной фразой

**Multi-source schema** (`cars` + `pending_ids` + `changes` + `brands` + `model_variants`) наполняется параллельно 4 парсерами на разных технологиях (playwright / direct HTTP), Postgres-views поверх считают готовность к экспорту по 180-day rule и фильтр для КЗ.

```
┌─────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ che168.com      │ │ guazi.com    │ │ encar.com    │ │ autocango.com│
│ dealer pool     │ │ C2C marketpl │ │ Korea (VIN+) │ │ China export │
│ VIN + reports   │ │ inspection   │ │ ДТП reports  │ │ FOB USD      │
│ playwright      │ │ direct HTTP  │ │ direct HTTP  │ │ playwright   │
└────────┬────────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
         │                 │                │                │
         └─────────────────┼────────────────┼────────────────┘
                           ▼                ▼
              ┌────────────────────────────────────────────┐
              │           Supabase Postgres                 │
              │                                             │
              │  pending_ids  → cars  → changes            │
              │  brands       → model_variants             │
              │                                             │
              │  Views:                                     │
              │    cars_kz_view              (год≥2022, ICE)│
              │    cars_export_eligibility   (180-day rule) │
              └────────────────────────────────────────────┘
```

## Источники в цифрах

| Источник | Метод | Стоимость | Главная фишка |
|---|---|---|---|
| **che168** | playwright | **$0** | VIN + maintenance/insurance reports |
| **guazi** | direct HTTP | **$0** | детальный inspection scorecard (5 секций × «N проблем») |
| **encar** | direct HTTP | $0 | VIN, ДТП Korea, Full HD photos |
| **autocango** | playwright | $0 | FOB USD, original-paint флаг |
| **ИТОГО** | — | **$0/мес** | — |

## Что вытаскиваем — полная карта полей

### Все источники в `cars`

| Поле | Тип | che168 | guazi | encar | autocango |
|---|---|---|---|---|---|
| `source_id` | text | infoid | clue_id | vehicleId | sku |
| `title` | text | ✓ | ✓ | ✓ | ✓ |
| `mark` / `mark_original` | text | ✓ | ✓ | ✓ | ✓ |
| `model` | text | ✓ | ✓ | ✓ | ✓ |
| `complectation` | text | ✓ (CN) | ✓ (CN) | ✓ EN | ✓ |
| `year` + `reg_date` | int + date | ✓ нативно | ✓ нативно | ✓ нативно | ✓ |
| `price_original` + currency | num + text | CNY | CNY | KRW | USD/CNY |
| `km_age` + unit | num + text | ✓ | ✓ | ✓ | ✓ |
| `color` + `color_original` | text | ✓ | ✓ | ✓ | ✓ |
| `transmission` + original | text | ✓ | ✓ | ✓ | ✓ |
| `drive_type` + original | text | ✓ | ✓ | — | ✓ |
| `engine_type` + `fuel_original` | text | ✓ | ✓ | ✓ | ✓ |
| `body_type` | text | — | — | ✓ | ✓ |
| `city` + `city_original` | text | ✓ | ✓ | ✓ | ✓ |
| **`vin`** | text | ✓ | ✗ скрыт | ✓ | ✓ |
| `images` (HD) | jsonb | ≤1024×768 | 1920×1280 | 1920×1080 | 1440×1080 |
| `image_count` | int | ✓ | ✓ | ✓ | ✓ |
| `source_data` | jsonb | см. ниже | см. ниже | см. ниже | см. ниже |
| `published_at` | timestamptz | ✓ | — | ✓ | — |
| `first_seen` / `last_seen` | timestamptz | ✓ | ✓ | ✓ | ✓ |

### `source_data` JSONB — per-source extras

**che168:**
- `trust_badges` — счётчики вхождений «认证二手车», «无重大事故», «30天整车保修» и др.
- `transfers` — переоформлений
- `emission` — эко-стандарт (国V/国VI/新能源)
- `dealer_address`, `dealer_id`
- `battery_score`, `battery_health` (% capacity), `battery_capacity`, `ev_range_km`
- `displacement`
- `brand_id_che168`, `series_id_che168`, `spec_id_che168` — внутренние ID

**guazi:**
- `trust_badges`
- `transfers`
- **`inspection.grade`** — общая оценка («一般»/«良好»/«优秀»)
- **`inspection.body_exterior`** — «2项注意» (2 проблемы)
- **`inspection.interior`** — «4项注意»
- **`inspection.frame`** — «5项注意» (рама!)
- **`inspection.engine_bay`** — «0项注意»
- **`inspection.ev_components`** — для EV
- **`inspection.insurance_claims`** — «1次理赔» (количество страховых)
- `battery.*` — kWh, type, range, fast-charge details
- `source_city` — РЕАЛЬНЫЙ город владельца (C2C — может отличаться от `city`)
- `displacement`, `emission`

**encar:** options list, accident report fields, dealer firm name, ...

**autocango:** FOB USD, original paint flag, export-eligibility...

## Расписание GitHub Actions

| Workflow | Cron | Что |
|---|---|---|
| `Scrape che168` | `30 19 * * *` | 03:30 Beijing |
| `Scrape encar` | `0 20 * * *` | 05:00 Seoul |
| `Scrape guazi` | `30 20 * * *` | 04:30 Beijing |
| `Scrape autocango` | `0 21 * * *` | 05:00 Beijing |
| `Import brands` | `0 22 * * 1` | пн 22:00 UTC |
| `Import model specs` | `0 23 1 * *` | 1-е число месяца |

Все можно запустить вручную через **workflow_dispatch**.

## Дефолтные фильтры (общие для китайских источников)

| | |
|---|---|
| Города | Beijing, Shanghai, Guangzhou, Shenzhen, Chengdu, Hangzhou |
| Год регистрации | ≥ 2020 |
| Пробег | ≤ 100,000 km |
| Цена | ≥ ¥5,000 |
| Sold | исключены |

## Secrets

| Secret | Используется в |
|---|---|
| `SUPABASE_URL` | везде |
| `SUPABASE_KEY` (service_role JWT) | везде |

## Стоимость

**Все 4 парсера = $0/мес** (после ухода от dongchedi).
GitHub Actions free tier + Supabase free tier хватает.

## Что дальше

- [ ] Frontend dashboard (Next.js + Vercel) — KPI, browse cars, кнопки запуска
- [ ] Image mirroring (Supabase Storage) — иначе китайские CDN могут перестать отдавать через границу
- [ ] **Inspection service** (Linear: «Inspection Service — pre-purchase»)
- [ ] LLM-перевод комплектаций (китайские trim-suffixes типа 商务型/豪华型)
- [ ] CN→EN model name backfill через сопоставление с `model_variants`

## Документация по источникам

- [`README_che168.md`](./README_che168.md) — VIN + reports
- [`README_guazi.md`](./README_guazi.md) — inspection scorecard
- [`README_encar.md`](./README_encar.md) — Корея
- [`README_autocango.md`](./README_autocango.md) — экспорт-каталог
