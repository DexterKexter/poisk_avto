# AutoCango.com — парсер б/у машин для экспорта (Китай)

Парсер объявлений с китайского экспорт-классифайда [autocango.com](https://www.autocango.com). Это **не внутренний рынок**, а **площадка для иностранных байеров** — машины с FOB-ценами в USD, готовые к экспорту в КЗ/СНГ.

Главная фишка: **прямой playwright + GitHub Actions = $0 за прогон**. Oxylabs не используем.

---

## Содержание

1. [Почему именно autocango](#почему-именно-autocango)
2. [Архитектура](#архитектура)
3. [Стратегия "качественной выборки"](#стратегия-качественной-выборки)
4. [Файлы](#файлы)
5. [Шаг 1: collect_autocango.py](#шаг-1-collect_autocangopy)
6. [Шаг 2: scrape_autocango.py](#шаг-2-scrape_autocangopy)
7. [Брендовый каталог](#брендовый-каталог-brands--логотипы)
8. [View `cars_export_eligibility`](#view-cars_export_eligibility)
9. [GitHub Actions](#github-actions)
10. [Стоимость](#стоимость)
11. [Известные особенности](#известные-особенности)

---

## Почему именно autocango

| | autocango | dongchedi | encar |
|---|---|---|---|
| Аудитория | **иностранные байеры** | китайский рынок | корейский рынок |
| Цены | **USD FOB Shanghai** | CNY | KRW |
| Язык | **английский** | китайский | корейский |
| Готовность к экспорту | **из коробки** | надо договариваться | надо договариваться |
| MSRP заводская | **есть** (¥) | нет | нет |
| 180-Day Rule mark | **есть** на каждом | нет | нет |

Для **импорта в КЗ** autocango даёт самую релевантную выборку: всё уже отфильтровано под экспорт, цены в долларах, дилеры знакомы с международной логистикой.

---

## Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│ Шаг 1: collect_autocango.py                                  │
│   playwright (headless Chromium, US IP)                      │
│   Итерация: 6 топ-городов × N страниц с фильтрами:           │
│     minPrice=5000 / minModelYear=2021                        │
│     country=China / originalPaint=22                         │
│     excludeSold=true / sort=6                                │
│     provinceId={X} / cityId={Y}                              │
│   URL: /usedcar/minPrice=.../cityId=.../page=N               │
│   Из DOM: <div class="car-item"> → 30 машин/страница         │
│        ↓                                                     │
│   pending_ids (Supabase) — id + URL + 28 полей в metadata    │
└──────────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────┐
│ Шаг 2: scrape_autocango.py                                   │
│   playwright открывает /sku/usedcar-{Brand}-{Model}-{ID}     │
│   Из DOM:                                                    │
│     - VIN-аналог: vehicleNo, ref_id                          │
│     - Дилер: имя, телефон, адрес                             │
│     - Spec: dimensions LxWxH, weight, seats, doors           │
│     - Accessories: Sun Roof / Leather / 360 Camera / ...     │
│     - Цены: $X export USD + ¥Y MSRP CNY                      │
│     - До 30 фото (full-res, без resize-параметров)           │
│     - Описание дилера                                        │
│        ↓                                                     │
│   cars (Supabase) с полной карточкой                         │
└──────────────────────────────────────────────────────────────┘
```

WAF проходим через playwright с патчами:
- `--disable-blink-features=AutomationControlled`
- `Object.defineProperty(navigator, 'webdriver', ...)` через init-script
- Realistic User-Agent

---

## Стратегия "качественной выборки"

Фильтры применяем **на стадии URL** — autocango сам фильтрует на своей стороне, мы получаем уже отобранное.

| Фильтр | Значение | Зачем |
|---|---|---|
| `originalPaint=22` | вкладка "Original Paint" | без перекрасов после ДТП |
| `minPrice=5000` | $5,000+ USD | отсекаем хлам, такси, аварийки |
| `minModelYear=2021` | 2021+ | укладываемся в **180-Day Rule КЗ** |
| `country=China` | Китай | export-ready inventory |
| `excludeSold=true` | без проданных | только живые объявления |
| `sort=6` | новейшие первыми | парсим самые свежие |
| `cityId={X}` + `provinceId={Y}` | топ-6 хабов | большие города = большие дилеры |

### 6 городов-экспортных хабов

| Город | provinceId | cityId | Почему |
|---|---|---|---|
| Шанхай | 310000 | 310100 | главный экспортный порт (FOB Shanghai) |
| Гуанчжоу | 440000 | 440100 | южный хаб, дилеры BYD/GAC |
| Шэньчжэнь | 440000 | 440300 | EV-столица, Tesla/BYD/Xpeng |
| Пекин | 110000 | 110100 | премиум-сегмент, импортные |
| Тяньцзинь | 120000 | 120100 | северный порт |
| Чэнду | 510000 | 510100 | западный хаб |

**Выборка:** 6 городов × ~10-20 страниц × 30 машин ≈ **1,500-3,000 уникальных** премиум-кандидатов.

---

## Файлы

```
poisk_avto/
├── collect_autocango.py            # Шаг 1: city loop, listings → pending_ids
├── scrape_autocango.py             # Шаг 2: detail pages → cars (full-res)
├── import_brands_autocango.py      # /ucbrand → brands table
├── enrich_brand_logos.py           # дотягиваем недостающие logo_url
├── README_autocango.md             # этот файл
├── requirements-scrapling.txt      # playwright deps (отдельно от requests-only)
└── .github/workflows/
    ├── scrape-autocango.yml        # daily 21:00 UTC
    └── import-brands.yml           # weekly Monday 22:00 UTC
```

Общая инфра (db.py, refresh_cars.py) общая со всеми источниками.

---

## Шаг 1: `collect_autocango.py`

**Что делает.** Для каждого из 6 городов открывает листинг через playwright, листает страницы, из каждой карточки `div.car-item` извлекает:

- **`Id`** (ACU... префикс для used, ACN... для new) — наш `source_id`
- URL детальной страницы (`/sku/usedcar-{Brand}-{Model}-{Id}`)
- Brand-slug, model-slug из URL
- Текст карточки → парсится через regex: год, пробег, топливо, КПП, цвет, рулевое, "180-Day Rule Compliant" flag
- Превью-фото (3 шт)
- Цена $USD

Сохраняет в `pending_ids.metadata` (JSONB).

**Параметры:**

```
--cities         "Shanghai,Guangzhou,Shenzhen,Beijing,Tianjin,Chengdu"
--pages-per-city 20         # макс страниц на город
--min-price      5000       # минимальная цена в USD
--min-year       2021       # минимальный модельный год
--original-paint 22         # код "Original Paint" таба
--exclude-sold   true
--limit          10000      # макс новых IDs за прогон
```

**Output:** запись в `pending_ids` с metadata = весь dict машины (28 полей).

**Что в `metadata`:**
- `href`, `type_slug`, `brand_slug`, `model_slug`
- `images` (превью URLs)
- `price_usd` (цена с listing)
- `source_city` (один из 6 хабов)
- Распарсенные текстовые поля: `reg_year`, `reg_month`, `model_year`, `mileage_km`, `fuel`, `engine_cc`, `transmission`, `color`, `steering`, `compliant_180day`

---

## Шаг 2: `scrape_autocango.py`

**Что делает.** Берёт ID из `pending_ids` (исключая `cars` и quarantine), playwright открывает `/sku/usedcar-...-{Id}`, scrape через regex по innerText.

**Что извлекаем:**

| Поле в `cars` | Откуда |
|---|---|
| `mark` / `mark_original` | "Brand GAC Trumpchi" → `GAC Trumpchi` |
| `model` / `series_original` | "Series GS8" → `GS8` |
| `year` | "Model Year 2023" |
| `reg_date` | "Reg. Year 2019-06" → `2019-06-01` |
| `price_original` | "$7,604" → 7604, currency=USD |
| `new_price_original` | "MSRP ¥182,800" → 182800, currency=CNY |
| `km_age` | "Mlg(km) 105000" |
| `color` | "Exterior Color White" |
| `engine_type` | "Fuel Petrol/Diesel/Hybrid/BEV/PHEV" |
| `transmission_type` | "Transmission AT/MT/CVT/DCT" → Automatic/Manual/CVT/DCT |
| `drive_type` | "Drivetrain 2WD" → FWD, "4WD" → AWD |
| `displacement` | "Engine 2.0T 201HP L4" → 2.0 |
| `horse_power` | "Engine 2.0T 201HP L4" → 201 |
| `length_mm` / `width_mm` / `height_mm` | "Dim.(mm) 4810*1910*1770" |
| `body_type` | "Body Type SUV" |
| `images` | до 30 фото full-res (`?x-image-process=` обрезан) |
| `description` | блок "Description...Contact your AutoCango" |

**В `source_data` JSONB:**
- `ref_id`, `steering`, `model_code`, `engine_cc`
- `seats`, `doors`, `weight_kg`, `volume_m3`, `max_cap_kg`
- `battery_capacity_kwh`, `range_km`, `motor_power_kw` (для EV)
- `accessories` — массив (Sun Roof, Leather Seat, 360 Camera, и т.д.)
- `compliant_180day` (boolean) — флаг 180-Day Rule для КЗ-импорта
- `msrp_cny`, `type_slug` (usedcar/newcar)

**Параметры:**

```
--limit 500   # макс карточек за прогон
```

**Warm-up.** В начале scrape playwright делает один заход на `/usedcar/excludeSold=true` чтобы получить WAF-cookies, потом эти cookies используются для всех последующих карточек в одной сессии.

---

## Брендовый каталог (brands + логотипы)

**`import_brands_autocango.py`** — однократный/еженедельный скрапинг `/ucbrand` страницы. Из неё извлекаем:
- 303 уникальных бренда (slug, name)
- 35 логотипов из featured-сетки (40×40 png/svg)

**`enrich_brand_logos.py`** — для брендов без logo_url открывает `/usedcar/brandName={slug}` и берёт лого из header. Дотянули **296 из 303** (97.7%).

Логотипы лежат на `https://i1.autocango.com/brand/{CODE}.webp` (например Audi = `78W`, BMW = `M4L`, BYD = `ME4`).

**Workflow `import-brands.yml`** делает оба шага последовательно: `import_brands` → `enrich_brand_logos`. Weekly Monday 22:00 UTC.

---

## View `cars_export_eligibility`

Postgres view поверх `cars` с расчётом готовности к экспорту по **180-Day Rule КЗ**:

```sql
SELECT *,
  (CURRENT_DATE - reg_date)::int                  AS days_since_reg,
  GREATEST(0, 180 - (CURRENT_DATE - reg_date))::int AS days_until_export_eligible,
  CASE
    WHEN reg_date IS NULL THEN 'unknown_reg_date'
    WHEN (CURRENT_DATE - reg_date) >= 180 THEN 'eligible_now'
    ELSE 'wait_' || (180 - (CURRENT_DATE - reg_date)) || '_days'
  END AS export_status,
  (reg_date IS NOT NULL AND (CURRENT_DATE - reg_date) >= 180) AS is_export_eligible
FROM cars
```

**Зачем:** фронт может фильтровать "только готовые к экспорту сегодня" или показывать "доступна через N дней".

```sql
-- Готовы сейчас
SELECT * FROM cars_export_eligibility
WHERE source='autocango' AND is_export_eligible;

-- Ждут регистрации (180-day)
SELECT mark, model, year, days_until_export_eligible
FROM cars_export_eligibility
WHERE export_status LIKE 'wait_%'
ORDER BY days_until_export_eligible;
```

---

## GitHub Actions

### `scrape-autocango.yml` — основной парсер

**Триггеры:**
- `schedule: 0 21 * * *` — каждый день 21:00 UTC = 05:00 Пекин
- `workflow_dispatch` — вручную с параметрами (cities, pages_per_city, min_price, min_year, original_paint, collect_limit, scrape_limit)

**Шаги:**
1. Setup Python 3.12 + `pip install -r requirements-scrapling.txt` (playwright + deps)
2. `python -m playwright install chromium --with-deps`
3. `python collect_autocango.py …` — 6 городов × N страниц
4. `python scrape_autocango.py --limit …` — детальные карточки

### `import-brands.yml` — каталог брендов

**Триггеры:**
- `schedule: 0 22 * * 1` — каждый понедельник 22:00 UTC
- `workflow_dispatch`

**Шаги:**
1. `python import_brands_autocango.py` — собрать список 303 брендов
2. `python enrich_brand_logos.py` — дотянуть недостающие лого

### Secrets

| Имя | Содержимое |
|---|---|
| `SUPABASE_URL` | https://pdmbdclhqiqyoomeswxs.supabase.co |
| `SUPABASE_KEY` | service_role JWT |

**Oxylabs не нужен** — playwright в Actions работает напрямую с autocango.com.

---

## Стоимость

**$0/мес.** Только GitHub Actions runner-time.

| Операция | Время | Стоимость |
|---|---|---|
| 1 страница listing (30 машин) | ~5 сек | $0 |
| 1 detail page | ~5 сек | $0 |
| Полный bootstrap 3000 машин | ~5-6 часов | $0 |
| Daily cron | ~30 мин | $0 |

GitHub Actions Free tier = 2000 минут/мес. Хватает с большим запасом.

---

## Известные особенности

- **2 типа ID:**
  - `ACU` префикс = used car (бывшая в употреблении)
  - `ACN` префикс = new car (новая, из салона)
- **Цены:** export USD (`$X,XXX`) видна в листинге и карточке; MSRP CNY (`¥XXX,XXX`) — только в карточке как референс
- **180-Day Rule.** В каждой карточке есть текст "180-Day Rule Compliant". Это означает что машина зарегистрирована больше 180 дней назад (китайское правило для разрешения экспорта). Этот флаг мы сохраняем в `source_data.compliant_180day`.
- **WAF.** autocango использует Cloudflare-стиль защиту. Прямые `requests.get()` получают HTML "Security Verification". Нужен полноценный браузер с stealth-патчами. Поэтому playwright.
- **Полноразмерные фото.** Аliyun OSS обработка `?x-image-process=image/resize,h_900/quality,q_80/format,webp` в исходном URL. Мы стрипим query-string — фронт получает оригиналы (full-res).
- **Pagination.** `/page=N` сегмент в конце URL. Каждый город даёт ~30 unique машин на странице (часто после ~5-10 страниц инвентарь с нашими фильтрами кончается).

---

## История discovery

1. Прямой `requests.post` к API → 403 (WAF "Security Verification")
2. Oxylabs `xhr=True` ловил POST к `/api/web/usedcar/search` — но Oxylabs тоже срабатывал WAF
3. Попытка через scrapling — нужны patchright/camoufox (не установились)
4. **Чистый playwright + stealth init script** — WAF проходит, 79 cookies (включая `__cf_bm`) выставляются
5. Прямой POST к API из браузерного контекста — всё равно 403 (CSRF check)
6. **Решение: DOM scraping** на `div.car-item` — без POST вообще
7. URL-сегменты для пагинации/фильтров — `/usedcar/cityId=.../page=N`
