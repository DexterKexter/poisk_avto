# Poisk Avto — мульти-источник парсер автомобилей для импорта в КЗ

Парсер объявлений с **4 источников** (2 китайских + 1 международный + 1 корейский), плюс каталог брендов, моделей и поколений. Цель — показать клиенту из Казахстана **готовые к ввозу** машины с реальными ценами, фото, VIN и историей проверок.

База — Supabase Postgres. Парсеры — Python + GitHub Actions. **Стоимость инфры — $0/мес**.

## Структура репо

```
poisk_avto/
├── README.md                       # этот файл
├── README_che168.md                # 🇨🇳 dealer-площадка, VIN + reports
├── README_encar.md                 # 🇰🇷 корейский б/у — VIN, ДТП-отчёты
├── README_autocango.md             # 🇨🇳 экспорт, FOB USD
│
├── db.py                           # Supabase REST API helpers
├── chinese_maps.py                 # CN→EN brand/color/fuel/transmission maps
├── stealth.py                      # Anti-bot helpers для Playwright
├── requirements.txt                # requests
├── requirements-scrapling.txt      # + playwright
│
├── collect_che168.py               # playwright, 6 городов + фильтры
├── scrape_che168.py                # playwright, VIN + photos + trust badges
│
├── collect_guazi_en.py             # EN guazi (en.guazi.com, playwright, без прокси)
├── scrape_guazi_en.py              # EN guazi detail pages (USD FOB, Grade, inspection)
│
├── collect_encar.py                # Korea API (direct HTTP)
├── scrape_encar.py                 # Korea detail (direct HTTP, Full HD photos)
│
├── collect_autocango.py            # playwright + фильтры
├── scrape_autocango.py             # playwright + full-res photos
│
├── import_brands_autocango.py      # справочник брендов + logo
├── import_model_specs.py           # справочник комплектаций → model_variants
├── enrich_brand_logos.py           # лого из autocango CDN
├── mirror_images.py                # зеркалит autoimg.cn → Supabase Storage
│
├── data/
│   └── model_generations.json      # 2516 поколений
├── migrations/
│   ├── 20260519_model_generations.sql
│   └── 20260524_guazi_en_columns.sql  # +27 колонок (inspection, EV, engine)
│
└── .github/workflows/
    ├── scrape-che168.yml           # */4h
    ├── scrape-guazi-en.yml         # */3h (EN export, USD FOB)
    ├── scrape-encar.yml            # ежечасно (paused)
    ├── scrape-autocango.yml        # */12h
    ├── import-model-specs.yml      # 1-е число месяца
    └── mirror-images.yml           # manual + post-step в che168
```

## Источники

| Источник | Метод | Язык | Валюта | Главная фишка |
|---|---|---|---|---|
| **che168** | playwright | CN→EN (chinese_maps) | CNY | VIN + maintenance/insurance reports |
| **guazi** | playwright | English | USD FOB | Grade A-S, inspection scores, partial VIN, 110 колонок |
| **encar** | direct HTTP API | KR→EN | KRW | VIN, ДТП, Full HD photos |
| **autocango** | playwright | EN | USD | FOB pricing, original-paint флаг |

## Архитектура

```
┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ che168.com   │ │ en.guazi.com │ │ encar.com    │ │ autocango.com    │
│ playwright   │ │ playwright   │ │ Korea API    │ │ export catalog   │
│ CN→EN maps   │ │ English      │ │ direct HTTP  │ │ playwright       │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘
       └────────────────┼────────────────┼──────────────────┘
                        ▼                ▼
          ┌──────────────────────────────────────────┐
          │         Supabase Postgres                 │
          │                                           │
          │  cars ─→ brands ─→ models                │
          │    └──→ model_generations (FK by year)   │
          │    └──→ model_variants (trim catalog)    │
          │                                           │
          │  pending_ids  (ID-queue per source)      │
          │  changes      (audit log)                │
          │  kolesa_price_cache  (KZ price compare)  │
          │                                           │
          │  Storage bucket: car-images              │
          │    (mirror для che168 autoimg.cn → ORB)   │
          │                                           │
          │  Edge Function: kolesa-match             │
          │    (on-demand KZ price aggregator)        │
          │                                           │
          │  Views:                                   │
          │    cars_kz_view (photos_ready + KZ rules) │
          │    brand_picker, model_picker (UI)        │
          └──────────────────────────────────────────┘
```

## Схема `cars` (110 колонок)

| Категория | Колонки |
|---|---|
| Источник | `source`, `source_id`, `source_language`, `url`, `title`, `spu_id` |
| Бренд/модель | `brand_id`→brands, `model_id`→models, `generation_id`→model_generations, `mark`, `mark_original`, `model`, `series_original`, `complectation` |
| Даты | `year`, `reg_date`, `mfg_date`, `published_at`, `listing_updated_at` |
| Цена | `price_original`, `price_currency`, `new_price_original`, `new_price_currency` |
| Пробег | `km_age`, `km_age_original`, `km_age_unit` |
| Двигатель ICE | `engine_type`, `fuel_original`, `displacement`, `horse_power`, `engine_power_kw`, `engine_model`, `num_cylinders`, `cylinder_arrangement`, `valves_per_cylinder`, `valve_train`, `torque_nm`, `power_rpm`, `torque_rpm`, `fuel_consumption` |
| EV / Батарея | `battery_kwh`, `battery_type`, `battery_health_pct`, `ev_range_km`, `energy_consumption`, `motor_power_kw`, `total_motor_torque_nm`, `front_motor_power_kw`, `front_motor_torque_nm`, `rear_motor_power_kw`, `rear_motor_torque_nm`, `charge_time_fast`, `charge_time_slow` |
| Трансмиссия | `transmission_type`, `transmission_original`, `drive_type`, `drive_original` |
| Кузов / размеры | `body_type`, `color`, `color_original`, `interior_color_original`, `length_mm`, `width_mm`, `height_mm`, `wheelbase_mm`, `curb_weight_kg`, `doors`, `seats` |
| Инспекция | `inspection_grade`, `inspection_score`, `inspection_data` (jsonb), `accident_free`, `no_water_damage`, `no_fire_damage`, `insurance_claims_count`, `owners_count` |
| Гео / логистика | `city`, `city_original`, `reg_city`, `reg_city_original`, `port`, `steering`, `export_ready` |
| Фото | `images` (jsonb), `image_count` |
| Дилер | `seller_type`, `shop_name`, `shop_short_name`, `shop_address`, `shop_id`, `shop_cars_count`, `sales_range` |
| VIN / отчёты | `vin`, `keys_count`, `maintenance`, `description` |
| Жизненный цикл | `first_seen`, `last_seen`, `sold_at`, `refresh_failed_attempts`, `last_refresh_at` |
| LLM / QA | `llm_normalized_at`, `llm_suggestion`, `llm_suggested_at`, `quarantine`, `quarantine_reasons`, `labels` |
| Прочее | `source_data` (jsonb), `acceleration_time` |

## Расписание

| Workflow | Cron | Статус |
|---|---|---|
| `scrape-che168.yml` | `15 */4 * * *` | ✅ active |
| `scrape-guazi-en.yml` | `45 */3 * * *` | ✅ active |
| `scrape-encar.yml` | `0 * * * *` | ⏸️ paused |
| `scrape-autocango.yml` | `45 */12 * * *` | ✅ active |
| `import-model-specs.yml` | `0 23 1 * *` | ✅ active |
| `mirror-images.yml` | post-step в che168 | ✅ active |

## Secrets

| Secret | Где |
|---|---|
| `SUPABASE_URL` | везде |
| `SUPABASE_KEY` | везде |
| `GUAZI_EMAIL` / `GUAZI_PASSWORD` | en.guazi.com (опционально) |
| `OPENROUTER_API_KEY` | (зарезервирован для LLM) |

## Edge Functions (Supabase)

| Функция | Назначение |
|---|---|
| `kolesa-match` | On-demand сравнение цен с kolesa.kz. Кэш 24ч. |

## Что дальше

- [x] ~~Стабилизировать EN guazi scraper~~ → cron `*/3h`, все поля в колонках
- [ ] Включить encar обратно (cron paused)
- [ ] Frontend dashboard (Next.js + Vercel)
- [ ] Customs calculator с учётом EREV (0%) vs HEV/PHEV (15%)
- [ ] Inspection API: подключить Chaboshi для VIN-snippet
