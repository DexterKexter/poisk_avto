# Poisk Avto — мульти-источник парсер автомобилей для импорта в КЗ

Парсер объявлений с **4 источников** (3 китайских + 1 корейский), плюс каталог брендов, моделей и поколений. Цель — показать клиенту из Казахстана **готовые к ввозу** машины с реальными ценами, фото, VIN и историей проверок.

База — Supabase Postgres. Парсеры — Python + GitHub Actions. **Стоимость инфры — $0/мес** (всё на direct HTTP + Playwright, без платных проксей).

## Структура репо

```
poisk_avto/
├── README.md                       # этот файл
├── README_che168.md                # 🇨🇳 dealer-площадка, VIN + reports
├── README_guazi.md                 # 🇨🇳 C2C с детальным inspection scorecard
├── README_encar.md                 # 🇰🇷 корейский б/у — VIN, ДТП-отчёты
├── README_autocango.md             # 🇨🇳 экспорт, FOB USD
│
├── db.py                           # Supabase REST API + SQLite fallback
├── chinese_maps.py                 # CN→EN brand/color/fuel/transmission/drive maps
├── requirements.txt                # requests
├── requirements-scrapling.txt      # + playwright (che168, autocango)
│
├── collect_che168.py               # playwright, 6 городов + фильтры
├── scrape_che168.py                # playwright, VIN + photos + trust badges
│
├── collect_guazi.py                # direct HTTP
├── scrape_guazi.py                 # parallel workers
│
├── collect_encar.py                # direct HTTP
├── scrape_encar.py                 # direct HTTP, Full HD photos
│
├── collect_autocango.py            # playwright + фильтры (used)
├── scrape_autocango.py             # playwright + full-res (used)
├── collect_autocango_new.py        # для /newcar (без фильтров)
├── scrape_autocango_new.py         # для /newcar
├── scrape_autocango_fleet.py       # B2B-прайслисты с xlsx
│
├── import_brands_autocango.py      # справочник брендов
├── import_model_specs.py           # справочник комплектаций → model_variants
├── enrich_brand_logos.py           # лого из i1.autocango.com badges
├── enrich_brand_logos_clearbit.py  # лого через Clearbit fallback
├── normalize_cars.py               # apply chinese_maps post-hoc
├── mirror_images.py                # копирует CDN-фото в Supabase Storage
│
├── data/
│   └── model_generations.json      # 2516 поколений из внешнего каталога
├── migrations/
│   └── 20260519_model_generations.sql
│
└── .github/workflows/
    ├── scrape-che168.yml           # */4h (Beijing)
    ├── scrape-guazi.yml            # */2h (Beijing)
    ├── scrape-encar.yml            # ежечасно (Seoul)
    ├── scrape-autocango.yml        # */12h (used + new смешано)
    ├── scrape-autocango-new.yml    # daily 22:00 UTC (только новые)
    ├── scrape-autocango-fleet.yml  # ручной (B2B прайсы)
    ├── enrich-brand-logos.yml      # ручной (autocango badges)
    ├── import-brands.yml           # пн 22:00 UTC
    ├── import-model-specs.yml      # 1-е число месяца
    ├── mirror-images.yml           # daily
    └── normalize.yml               # после каждого scrape
```

## Архитектура

**Multi-source schema** наполняется параллельно 4 парсерами на разных технологиях (playwright / direct HTTP). Поверх — справочники и Postgres-views под фильтр КЗ.

```
┌─────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ che168.com      │ │ guazi.com    │ │ encar.com    │ │ autocango.com    │
│ dealer pool     │ │ C2C marketpl │ │ Korea (VIN+) │ │ export catalog   │
│ VIN+reports     │ │ inspection   │ │ accident rpt │ │ used + new+fleet │
│ playwright      │ │ direct HTTP  │ │ direct HTTP  │ │ playwright       │
└────────┬────────┘ └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘
         │                 │                │                  │
         └─────────────────┼────────────────┼──────────────────┘
                           ▼                ▼
              ┌────────────────────────────────────────────┐
              │           Supabase Postgres                 │
              │                                             │
              │  cars ─→ brands ─→ models                  │
              │    └──→ model_generations (FK by year)     │
              │    └──→ model_variants (trim catalog)      │
              │                                             │
              │  pending_ids   (ID-queue per source)       │
              │  changes       (audit log)                 │
              │  fleet_offers  + fleet_pricelist (B2B)     │
              │                                             │
              │  Views:                                     │
              │    cars_kz_view             (год≥2022,ICE)  │
              │    cars_export_eligibility  (180-day rule)  │
              │    cars_with_specs          (joined)        │
              │    brand_picker, model_picker (UI helpers)  │
              └────────────────────────────────────────────┘
```

## Источники в цифрах

| Источник | Метод | Cost | Главная фишка |
|---|---|---|---|
| **che168** | playwright | $0 | VIN + maintenance/insurance reports |
| **guazi** | direct HTTP | $0 | детальный inspection scorecard |
| **encar** | direct HTTP | $0 | VIN, ДТП Korea, Full HD photos |
| **autocango (used)** | playwright | $0 | FOB USD, original-paint флаг |
| **autocango (new)** | playwright | $0 | новые машины с дилеров |
| **autocango (fleet)** | playwright | $0 | B2B xlsx-прайсы оптовиков |
| **ИТОГО** | — | **$0/мес** | — |

### Префиксы source_id у autocango

Один общий `source='autocango'`, три раздела разделяются префиксом `source_id`:

| Префикс | Раздел | Что |
|---|---|---|
| `ACU…` | /usedcar | подержанные дилеров |
| `ACN…` | /newcar | новые машины |
| `ACF…` | /fleet | B2B-прайслисты (попадает в `fleet_*` таблицы) |

## Схема БД

### `cars` — основная таблица объявлений
| Категория | Колонки |
|---|---|
| Источник | `source`, `source_id`, `source_language`, `url`, `title` |
| Бренд/модель | `brand_id` → `brands`, `model_id` → `models`, `generation_id` → `model_generations` |
| Метаданные модели | `mark_original`, `mark`, `series_original`, `model`, `complectation`, `year`, `reg_date` |
| Цена | `price_original`, `price_currency`, `new_price_original`, `new_price_currency` |
| Состояние | `km_age_original`, `km_age_unit`, `km_age`, `color_original`, `color` |
| Тех. характеристики | `body_type`, `engine_type`, `fuel_original`, `transmission_original`, `transmission_type`, `drive_original`, `drive_type`, `displacement`, `horse_power`, `acceleration_time`, `length_mm`, `width_mm`, `height_mm`, `wheelbase_mm` |
| Геометрия продажи | `city_original`, `city`, `reg_city_original`, `reg_city` |
| **Отчёты о проверке** | `owners_count`, `has_accident_record`, `insurance_claims_count`, `battery_health_pct`, `maintenance`, `vin` |
| Описание/фото | `description`, `images` (jsonb), `image_count` |
| Дилер | `seller_type`, `shop_name`, `shop_short_name`, `shop_address`, `shop_id`, `shop_cars_count`, `sales_range` |
| Per-source JSONB | `source_data` |
| Жизненный цикл | `first_seen`, `last_seen`, `sold_at`, `published_at`, `listing_updated_at`, `refresh_failed_attempts`, `last_refresh_at` |

### Связанные таблицы

| Таблица | Что | Размер |
|---|---|---|
| `brands` | Бренды (Honda, BMW, ...). С `slug`, `logo_url`, `country`, `source` | ~326 |
| `models` | Модели в составе бренда. Уникальны по `(brand_id, slug)` | ~1800 |
| `model_generations` | Поколения с диапазоном `start_year..end_year`. Загружается из `data/model_generations.json` + ручные правки. | ~2570 |
| `model_variants` | Каталог комплектаций (motor_power_kw, range_km, msrp_cny). Парсится с autocango. | ~3200 |
| `fleet_offers` | B2B-предложения от autocango (offer-level: бренд, MOQ, дата) | по числу ACF |
| `fleet_pricelist` | Строки из xlsx-прайслистов (бренд/модель/комплектация/цена в CNY/USD) | сотни на ACF |
| `pending_ids` | Очередь ID на скрейп (collect → pending → scrape) | dynamic |
| `changes` | Audit-log изменений (опционально) | dynamic |

### Per-source extras в `source_data` JSONB

**che168:**
- `trust_badges` — счётчики "认证二手车", "无重大事故", "事故车", "泡水车" и др. (используются для `has_accident_record`)
- `transfers` — переоформлений (источник `owners_count`)
- `emission`, `dealer_address`, `dealer_id`
- `battery_score`, `battery_health` (источник `battery_health_pct`), `battery_capacity`, `ev_range_km`
- `brand_id_che168`, `series_id_che168`, `spec_id_che168`

**guazi:**
- `trust_badges`
- `transfers`
- **`inspection.grade`** — оценка (一般/良好/优秀)
- **`inspection.body_exterior`**, `interior`, `frame`, `engine_bay`, `ev_components` — "N项注意"
- **`inspection.insurance_claims`** — "N次理赔" (источник `insurance_claims_count`)
- `battery.*` — для EV
- `source_city` — РЕАЛЬНЫЙ город владельца (может отличаться от `city`)

**encar:**
- `accident.recordView`, `accident.resumeView` — флаги (источник `has_accident_record`)
- `diagnosis_car`, `inspection_formats`, `warranty`, `trust`
- `seizing` (залоги/аресты)
- `vehicleId`, `vehicleNo`, `option_codes_*`, `dealer_phone`, `dealer_firm_code`

**autocango:**
- `compliant_180day` — флаг 180-day export rule
- `is_new`, `type_slug` (для разделения used/new)
- `model_code`, `ref_id`, `msrp_cny`
- `battery_capacity_kwh`, `motor_power_kw`, `range_km` (EV)
- `engine_cc`, `doors`, `seats`, `volume_m3`, `weight_kg`, `max_cap_kg` (commercial)

## Расписание GitHub Actions

| Workflow | Cron | Когда (UTC) | Что |
|---|---|---|---|
| `scrape-che168.yml` | `15 */4 * * *` | каждые 4 ч | dealer pool |
| `scrape-guazi.yml` | `30 */2 * * *` | каждые 2 ч | C2C |
| `scrape-encar.yml` | `0 * * * *` | каждый час | Korea API |
| `scrape-autocango.yml` | `45 */12 * * *` | каждые 12 ч | used+new общий |
| `scrape-autocango-new.yml` | `0 22 * * *` | 22:00 UTC | только новые |
| `scrape-autocango-fleet.yml` | manual | — | B2B xlsx |
| `enrich-brand-logos.yml` | manual | — | autocango badges |
| `import-brands.yml` | `0 22 * * 1` | пн 22:00 | brands + Clearbit |
| `import-model-specs.yml` | `0 23 1 * *` | 1-е число | model_variants |
| `mirror-images.yml` | daily | — | копия в Storage |
| `normalize.yml` | after-each-scrape | — | apply chinese_maps |

Все можно запустить вручную через **workflow_dispatch**.

## Дефолтные фильтры (общие для china-used)

| | |
|---|---|
| Города | Beijing, Shanghai, Guangzhou, Shenzhen, Chengdu, Hangzhou |
| Год регистрации | ≥ 2020 |
| Пробег | ≤ 100,000 km |
| Цена | ≥ ¥5,000 |
| Sold | исключены |

`/newcar` и `/fleet` секции autocango идут **без фильтров** (там и так мало вариантов).

## Поколения моделей

`model_generations` — каталог поколений (BMW 5 series E60/F10/G30, Audi A4 B7/B8/B9 и т.д.).

- Загружен из `data/model_generations.json` (2516 поколений, 112 брендов) + ~50 ручных правок для свежих китайских EV (NIO, Xpeng, Li Auto, AITO, Wuling MINIEV и т.д.) и корейских синонимов (Avante↔Elantra, Morning↔Picanto, K3↔Forte).
- Уникальный ключ: `(brand_name, model_name, gen, full_name)`.
- `end_year IS NULL` = поколение всё ещё в производстве.
- Backfill `cars.generation_id` идёт по диапазону года: `c.year BETWEEN g.start_year AND COALESCE(g.end_year, 9999)`.
- Текущий match rate: **70% всех машин с годом** (encar 85%, guazi 64%, che168 53%, autocango 47%).

## Отчёты о проверке (плоские колонки на `cars`)

| Колонка | Тип | Источник | Заполнено |
|---|---|---|---|
| `owners_count` | INT | guazi.transfers + che168.transfers + autocango (редко) | ~1075 |
| `has_accident_record` | BOOL | encar.accident.recordView ИЛИ che168.trust_badges.事故车>0 | ~2095 |
| `insurance_claims_count` | INT | guazi.inspection.insurance_claims ("N次理赔" → N) | ~453 |
| `battery_health_pct` | NUMERIC(5,2) | che168.battery_health ("96.17%" → 96.17) | ~419 EV |
| `vin` | TEXT | encar/che168/autocango | ~1825 |

Это позволяет фронту фильтровать `WHERE owners_count <= 1 AND has_accident_record = false` без JSON-обхода.

## Inspection-сервис (будущее)

Готовая инфраструктура для интеграции с китайскими VIN-сервисами:

| Tier | Партнёр | Цена | Что внутри |
|---|---|---|---|
| Free snippet | 查博士 (Chaboshi) | ~2 CNY | "ДТП есть/нет", "владельцев N" |
| Full VIN report | 查博士 | $19 USD | 266 пунктов, ДТП, ТО, залоги, утопление |
| Physical PPI | 检车家 (Jianchejia) | $249 USD | 376 пунктов, эксперт на месте, 24-48ч |
| Premium export | SGS China | $499 USD | сертификат для таможни |
| AutoCango bundle | AutoCango | $65 USD | только для autocango listings, 48ч |

## Secrets

| Secret | Используется в |
|---|---|
| `SUPABASE_URL` | везде |
| `SUPABASE_KEY` (service_role JWT) | везде |

## Стоимость

**Все 4 парсера = $0/мес**. GitHub Actions free tier + Supabase free tier хватает.

## Что дальше

- [ ] Frontend dashboard (Next.js + Vercel) — KPI, browse cars, generation filter
- [ ] Inspection API: подключить Chaboshi для VIN-snippet
- [ ] LLM-перевод комплектаций (китайские trim-suffixes типа 商务型/豪华型)
- [ ] Encar: model normalization — убрать trim из `cars.model`
- [ ] Догнать оставшиеся ~30 китайских суб-брендов без лого через autocango (CI workflow)

## Документация по источникам

- [`README_che168.md`](./README_che168.md) — VIN + reports
- [`README_guazi.md`](./README_guazi.md) — inspection scorecard
- [`README_encar.md`](./README_encar.md) — Корея
- [`README_autocango.md`](./README_autocango.md) — экспорт-каталог (used + new + fleet)
