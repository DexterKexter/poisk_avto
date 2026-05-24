# Poisk Avto — мульти-источник парсер автомобилей для импорта в КЗ

Парсер объявлений с **4 источников** (3 китайских + 1 корейский), плюс каталог брендов, моделей и поколений. Цель — показать клиенту из Казахстана **готовые к ввозу** машины с реальными ценами, фото, VIN и историей проверок.

База — Supabase Postgres. Парсеры — Python + GitHub Actions. **Стоимость инфры — $0/мес**.

## Структура репо

```
poisk_avto/
├── README.md                       # этот файл
├── README_che168.md                # 🇨🇳 dealer-площадка, VIN + reports
├── README_guazi.md                 # 🇨🇳 C2C с inspection scorecard
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
├── collect_guazi.py                # Chinese guazi (playwright + Oxylabs)
├── scrape_guazi.py                 # Chinese guazi detail pages
├── collect_guazi_en.py             # EN export guazi (en.guazi.com, playwright)
├── scrape_guazi_en.py              # EN guazi detail pages (USD, Grade, inspection)
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
│   ├── model_generations.json      # 2516 поколений
│   └── open_vehicle_db.json        # 69 брендов, справочник моделей
├── migrations/
│   └── 20260519_model_generations.sql
│
└── .github/workflows/
    ├── scrape-che168.yml           # */4h
    ├── scrape-guazi.yml            # */2h (Chinese)
    ├── scrape-guazi-en.yml         # manual (EN export, в разработке)
    ├── scrape-encar.yml            # ежечасно (paused)
    ├── scrape-autocango.yml        # */12h
    ├── import-brands.yml           # пн 22:00 UTC
    ├── import-model-specs.yml      # 1-е число месяца
    └── mirror-images.yml           # manual + post-step в che168
```

## Источники

| Источник | Метод | Язык | Валюта | Главная фишка |
|---|---|---|---|---|
| **che168** | playwright | CN→EN (chinese_maps) | CNY | VIN + maintenance/insurance reports |
| **guazi (CN)** | playwright + Oxylabs | CN→EN | CNY | inspection scorecard |
| **guazi (EN)** | playwright | English | USD | Grade A-D, 60-84 фото, export-ready |
| **encar** | direct HTTP API | KR→EN | KRW | VIN, ДТП, Full HD photos |
| **autocango** | playwright | EN | USD | FOB pricing, original-paint флаг |

## Архитектура

```
┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ che168.com   │ │ guazi.com    │ │ encar.com    │ │ autocango.com    │
│ + en.guazi   │ │ (CN + EN)   │ │ Korea API    │ │ export catalog   │
│ playwright   │ │ playwright   │ │ direct HTTP  │ │ playwright       │
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

## Схема `cars`

| Категория | Колонки |
|---|---|
| Источник | `source`, `source_id`, `source_language`, `url`, `title` |
| Бренд/модель | `brand_id`→brands, `model_id`→models, `generation_id`→model_generations |
| Метаданные | `mark_original`, `mark`, `series_original`, `model`, `complectation`, `year`, `reg_date` |
| Цена | `price_original`, `price_currency`, `new_price_original`, `new_price_currency` |
| Состояние | `km_age_original`, `km_age_unit`, `km_age`, `color_original`, `color` |
| Техника | `body_type`, `engine_type`, `fuel_original`, `transmission_type`, `drive_type`, `displacement`, `horse_power` |
| Гео | `city_original`, `city`, `reg_city_original`, `reg_city` |
| Инспекция | `inspection_score`, `accident_free`, `export_ready`, `inspection_data` (jsonb), `labels` (jsonb), `steering`, `keys_count` |
| Отчёты | `owners_count`, `vin`, `maintenance` |
| Фото | `images` (jsonb), `image_count` |
| Дилер | `seller_type`, `shop_name`, `shop_id` |
| Жизненный цикл | `first_seen`, `last_seen`, `sold_at`, `published_at` |
| LLM | `llm_normalized_at` |

## Расписание

| Workflow | Cron | Статус |
|---|---|---|
| `scrape-che168.yml` | `15 */4 * * *` | ✅ active |
| `scrape-guazi.yml` | `30 */2 * * *` | ✅ active |
| `scrape-guazi-en.yml` | manual | 🔧 в разработке |
| `scrape-encar.yml` | `0 * * * *` | ⏸️ paused |
| `scrape-autocango.yml` | `45 */12 * * *` | ✅ active |
| `import-brands.yml` | `0 22 * * 1` | ✅ active |
| `import-model-specs.yml` | `0 23 1 * *` | ✅ active |
| `mirror-images.yml` | post-step в che168 | ✅ active |

## Secrets

| Secret | Где |
|---|---|
| `SUPABASE_URL` | везде |
| `SUPABASE_KEY` | везде |
| `OXY_USER` / `OXY_PASS` | guazi CN (Oxylabs proxy) |
| `OPENROUTER_API_KEY` | (зарезервирован для LLM) |
| `GUAZI_EMAIL` / `GUAZI_PASSWORD` | en.guazi.com dealer auth |

## Edge Functions (Supabase)

| Функция | Назначение |
|---|---|
| `kolesa-match` | On-demand сравнение цен с kolesa.kz. Кэш 24ч. |

## Что дальше

- [ ] Стабилизировать EN guazi scraper → перевести на cron, отключить Chinese
- [ ] Включить encar обратно (cron paused)
- [ ] Frontend dashboard (Next.js + Vercel)
- [ ] Customs calculator с учётом EREV (0%) vs HEV/PHEV (15%)
- [ ] Inspection API: подключить Chaboshi для VIN-snippet
