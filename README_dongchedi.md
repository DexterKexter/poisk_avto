# Dongchedi.com — парсер б/у автомобилей

Парсер объявлений с китайского классифайда [dongchedi.com](https://www.dongchedi.com/usedcar). Собирает структурированные данные через Oxylabs Web Scraper API в Supabase Postgres. Заточен под отбор машин для ввоза в Казахстан (год ≥ 2022, не EV).

---

## Содержание

1. [Архитектура](#архитектура)
2. [Технологический стек](#технологический-стек)
3. [Файлы парсера](#файлы-парсера)
4. [URL-схема dongchedi (28 позиций)](#url-схема-dongchedi-28-позиций)
5. [XHR-захват `sh_sku_list`](#xhr-захват-sh_sku_list)
6. [Шаг 1: `collect_ids.py` — сбор ID](#шаг-1-collect_idspy--сбор-id)
7. [Шаг 2: `scrape_dongchedi.py` — парсинг карточек](#шаг-2-scrape_dongchedipy--парсинг-карточек)
8. [Шаг 3: `refresh_cars.py` — обновление + sold detection](#шаг-3-refresh_carspy--обновление--sold-detection)
9. [Схема БД (Supabase)](#схема-бд-supabase)
10. [GitHub Actions workflows](#github-actions-workflows)
11. [Локальный запуск](#локальный-запуск)
12. [Стоимость Oxylabs](#стоимость-oxylabs)
13. [Brand pool](#brand-pool)
14. [Известные проблемы и TODO](#известные-проблемы-и-todo)

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│ Шаг 1: collect_ids.py                                       │
│   79 брендов × 4 города = 316 URL                           │
│   Oxylabs открывает каждую страницу в headless-браузере,    │
│   скроллит, перехватывает XHR /motor/pc/sh/sh_sku_list      │
│   Фильтр car_year ≥ 2022 ДО записи в БД                     │
│        ↓                                                    │
│   pending_ids (Supabase) — очередь sku_id + метаданные      │
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│ Шаг 2: scrape_dongchedi.py                                  │
│   Берёт sku_id из pending_ids (исключая carantine и         │
│   уже спарсенные), параллельно (10 воркеров) открывает      │
│   /usedcar/{id}, извлекает __NEXT_DATA__.skuDetail,         │
│   парсит 40+ полей                                          │
│        ↓                                                    │
│   cars (Supabase) — главная таблица                         │
│        ↓                                                    │
│   при фейле: pending_ids.failed_attempts += 1               │
│   после 3-х подряд: ID в карантине, больше не парсится      │
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│ Шаг 3: refresh_cars.py (weekly)                             │
│   Re-fetch всех живых машин (sold_at IS NULL),              │
│   старейшие last_refresh_at первыми                         │
│        ↓                                                    │
│   успех + новая цена < старой → changes('price_drop')       │
│   3 фейла подряд → cars.sold_at = now + changes('sold')     │
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│ cars_kz_view — вычисляемые kz_importable / kz_status        │
│   year ≥ 2022 AND engine_type != 'Electric' → ok            │
└─────────────────────────────────────────────────────────────┘
```

---

## Технологический стек

| Компонент | Что |
|---|---|
| Python 3.12 | runtime парсера |
| Oxylabs Realtime API | https://realtime.oxylabs.io/v1/queries (Web Scraper, real account) |
| Supabase Postgres | основная БД через REST API (PostgREST), без `psycopg2` |
| SQLite | fallback для локальной разработки (одинаковая схема) |
| GitHub Actions | runner + cron + manual workflow_dispatch |

Зависимости в `requirements.txt`: одна строка `requests`.

---

## Файлы парсера

```
poisk_avto/
├── collect_ids.py          # Шаг 1: XHR-захват, brand×city
├── scrape_dongchedi.py     # Шаг 2: parse_card(), 40+ полей, словари переводов
├── refresh_cars.py         # Шаг 3: re-check + sold + price drops
├── db.py                   # Supabase REST + SQLite fallback, общий API
├── requirements.txt        # requests
├── README_dongchedi.md     # этот файл
└── .github/
    └── workflows/
        ├── scrape.yml      # daily 19:00 UTC + manual dispatch
        └── refresh.yml     # weekly Sun 22:00 UTC + manual dispatch
```

---

## URL-схема dongchedi (28 позиций)

Расшифровано **эмпирически** через анализ HTML. Листинг б/у имеет ровно 28 позиций через дефис:

```
https://www.dongchedi.com/usedcar/p0-p1-p2-...-p27
```

| Поз | Фильтр | Примеры значений |
|---|---|---|
| 0 | Цена (万 CNY) | `0,3`, `3,5`, `5,10`, `10,15`, `15,20`, `20,!1` |
| 1 | Тип кузова | `0`=Sedan, `1`=SUV, `2`=MPV, `3`=Pickup, `4`=Sports |
| 5 | Объём двигателя | `0,1.0`, `1.1,1.6`, `1.7,2.0`, `2.1,2.5` |
| 6 | Топливо | `1`=Бензин, `2`=Дизель, `3`=Гибрид, `4-6`=NEV |
| 12 | КПП | числовые коды |
| 16 | Пробег (万 km) | `0,1`, `1,3`, `3,5`, `5,10`, `10,!1` |
| 18 | Привод | `1`=FWD, `2`=RWD, `3`=AWD |
| **19** | **Brand ID** | См. [Brand pool](#brand-pool) |
| **21** | **City code** | См. ниже |
| 22 | Режим выдачи | 1-4 |

Все остальные позиции — `x` = "без фильтра".

**City codes** (проверены):

```python
"beijing":   "110000"
"shanghai":  "310000"
"guangzhou": "440100"
"shenzhen":  "440300"
"tianjin":   "120000"
"all":       "x"
```

**Важно:** в URL **нет фильтра по году выпуска**. `车龄` означает не год, а возраст. Год отдаётся в XHR-ответе (`car_year`) и фильтруется в Python (`--min-year`).

---

## XHR-захват `sh_sku_list`

Dongchedi — Next.js SSR. Данные карточек в HTML через `<script id="__NEXT_DATA__">`. Но **листинг машин** подгружается через защищённый `msToken` API `/motor/pc/sh/sh_sku_list` (POST). Напрямую дёрнуть нельзя.

**Решение:** Oxylabs параметр `"xhr": true` ловит все XHR-вызовы, которые browser делает на странице. Мы вытаскиваем ответы `sh_sku_list` — это чистый JSON со списком ~20 машин на каждый вызов.

```python
payload = {
    "source": "universal",
    "url": "https://www.dongchedi.com/usedcar/x-...-110000-x-...",
    "geo_location": "China",       # обязательно
    "locale": "zh-CN",
    "render": "html",
    "xhr": True,                   # ← ключевое
    "browser_instructions": [
        {"type": "scroll_to_bottom", "wait_time_s": 2}
    ] * 8,
}
```

При 8 скроллах — ~11 POST-вызовов `sh_sku_list` ≈ 220 машин в JSON с метаданными:
- `sku_id`, `car_year`, `brand_id`, `brand_name`, `series_name`
- `car_source_city_name`, `transfer_cnt`, `shop_id`

**Не приходит в листинге:** `sh_price` (цена) и `official_price`. Они только в карточке через `__NEXT_DATA__.skuDetail`.

---

## Шаг 1: `collect_ids.py` — сбор ID

**Что делает.** Для каждой комбинации `(город, бренд)` отправляет один Oxylabs-запрос, перехватывает все XHR `sh_sku_list`, собирает уникальные `sku_id`. Фильтрует машины старше `--min-year` ДО записи (экономит парсинг карточек).

**Стратегия brand × city.** Без фильтра по бренду листинг показывает только топ-220 машин по стране. С фильтром по бренду — топ-220 *внутри бренда*. 79 × 4 = 316 URL ≈ 800–1500 новых машин за прогон.

**Параметры:**

```
--cities       beijing,shanghai,guangzhou,shenzhen   # CSV из CITY_CODES
--brands       all                                    # 'all' или CSV из BRAND_POOL
--scrolls      8                                      # скроллов на запрос
--batch-size   4                                      # параллельных запросов
--batch-pause  3                                      # сек между batch'ами
--min-year     2022                                   # отсекаем старые
--limit        10000                                  # макс новых ID за прогон
```

**Output:** записи в `pending_ids` с `metadata` (car_year, brand_name, series_name, city и т.д.).

**Throttling.** Oxylabs при 4+ параллельных запросах рандомно режет 1–2 за batch — это нормально, retry в коде нет. Если *всегда* один город возвращает 0 — снижай `--batch-size` до 2.

---

## Шаг 2: `scrape_dongchedi.py` — парсинг карточек

**Что делает.** Берёт ID из `pending_ids` (исключая уже в `cars` и quarantine с `failed_attempts >= 3`), параллельно через `ThreadPoolExecutor` открывает `/usedcar/{id}` через Oxylabs `render=html`, извлекает `__NEXT_DATA__.props.pageProps.skuDetail`, заполняет 40+ полей.

**Параметры:**

```
--skip-listing                  # обязательный флаг (без него скрипт упадёт)
--limit         2000            # макс карточек за прогон
--workers       10              # параллелизм
```

**Quarantine.** При любом фейле (HTTP non-200, отсутствие `__NEXT_DATA__`, отсутствие `skuDetail`) инкрементим `pending_ids.failed_attempts`. После 3-х подряд ID в карантине — больше не выдаётся `get_pending_ids()`. Раньше каждый прогон тратился запрос на одни и те же мёртвые ID (0.5% базы).

**Парсимые поля:**

| Группа | Поля |
|---|---|
| Идентификация | source, source_id, source_language, url, title, spu_id |
| Бренд/модель | mark_original, mark, series_original, model, complectation, year |
| Цена | price_original, price_currency (CNY), new_price_original, new_price_currency |
| Пробег | km_age_original, km_age_unit (km), km_age |
| Цвет/тип | color_original, color, body_type, engine_type |
| Двигатель | fuel_original, displacement, horse_power, acceleration_time |
| Трансмиссия | transmission_original, transmission_type, drive_original, drive_type |
| Размеры | length_mm, width_mm, height_mm, wheelbase_mm |
| Локация | city_original, city, reg_city_original, reg_city, reg_date |
| Прочее | owners_count, maintenance, interior_color_original, description |
| Фото | images (JSONB array), image_count |
| Диллер | seller_type, shop_name, shop_short_name, shop_address, shop_id, shop_cars_count, sales_range |
| Lifecycle | first_seen, last_seen, sold_at, refresh_failed_attempts, last_refresh_at |
| Резерв | source_data (JSONB) — под inspection report, опции и т.п. |

**Цена.** Хранится в оригинальной валюте (CNY) без конвертации. Фронт сам считает по live FX rate. `sh_price` и `official_price` приходят в *фэнях* (1/100 CNY) — делим на 100.

**Словари переводов.** В коде: `BRAND_MAP`, `COLOR_MAP`, `FUEL_MAP`, `TRANSMISSION_MAP`, `DRIVE_MAP`, `CITY_MAP`. Когда будет второй парсер (che168) — выносить общее в `parsers/common.py`.

**Fallbacks (улучшения 2026-05).**

- **`body_type`** при отсутствии `series_type`: распознаём по series_name и car_name — Range Rover (`揽胜/极光`), Defender (`卫士`), Discovery (`发现`), Land Cruiser/Prado, Wrangler, Grand Cherokee, Highlander, VW Tiguan/Touareg/Teramont, BMW X1-X7, Audi Q3-Q8, Mercedes GLA-GLS; MPV (GL8, Sienna, Odyssey, Vellfire, Alphard); пикапы (`皮卡`); купе (`轿跑/coupe`).
- **`drive_type`**: помимо `前置前驱/前置后驱/全时四驱` добавлены `前置四驱/中置四驱/后置四驱` и EV multi-motor (`双/三/四电机四驱`).
- **`engine_type`** при пустом или `-` значении: парсим `model` — `PHEV/插电` → PHEV, `增程` → EREV, `HEV/混动/油电` → Hybrid, `EV/纯电` → Electric, `TSI/TFSI/Turbo` → Petrol.

---

## Шаг 3: `refresh_cars.py` — обновление + sold detection

**Что делает.** Раз в неделю (или вручную) проходит по всем живым машинам (`sold_at IS NULL`), сортируя по `last_refresh_at ASC NULLS FIRST` (давно не проверенные — первыми). Для каждой:

1. Re-fetch карточки через Oxylabs.
2. **Успех:**
   - Если `new price < old price` → пишем строку в `changes(change_type='price_drop')` с `{price_original}` старым и новым.
   - `upsert_car(rec)` — обновляет все актуальные поля (цена, last_seen и т.д.).
   - `last_refresh_at = now`, `refresh_failed_attempts = 0`.
3. **Фейл** (нет HTML, нет `__NEXT_DATA__`, нет `skuDetail`):
   - `refresh_failed_attempts += 1`.
   - Если стало `>= 3` → `sold_at = now` + строка `changes(change_type='sold')` с `{last_price, consecutive_fails}` и `{sold_at}`.

**Параметры:**

```
--limit     500          # сколько машин за прогон
--all                    # все живые (игнорирует --limit)
--workers   10
--dry-run                # не писать в БД, только показать что бы сделали
```

**Порог 3** настраивается в `db.py:SOLD_FAIL_THRESHOLD`. Quarantine pending_ids — `QUARANTINE_THRESHOLD = 3` там же.

---

## Схема БД (Supabase)

Проект: `pdmbdclhqiqyoomeswxs.supabase.co`.

### `cars`

Универсальная multi-source таблица. Главные поля:

| Поле | Тип | Назначение |
|---|---|---|
| `id` | bigserial PK | автоинкремент |
| `source` + `source_id` | text, UNIQUE | составной ключ (`dongchedi` + sku_id) |
| `source_language` | text | `zh` / `ko` / `ja` для языка `*_original` |
| `*_original` | text | значения на языке источника (mark, color, city, ...) |
| `*` (без суффикса) | text | нормализовано в латиницу |
| `price_original` + `price_currency` | numeric, text | без конвертации — фронт делает |
| `km_age_original` + `km_age_unit` + `km_age` | numeric, text, numeric | km нормализован для cross-market фильтров |
| `images` | jsonb | массив URL |
| `source_data` | jsonb | источник-специфичные поля (inspection report и т.п.) |
| `first_seen`, `last_seen` | timestamptz | дата первого/последнего успешного парсинга |
| `sold_at` | timestamptz | null если живая |
| `refresh_failed_attempts` | int | счётчик подряд фейлов при refresh |
| `last_refresh_at` | timestamptz | последний успешный re-check |

Индексы: `idx_cars_alive` (partial WHERE sold_at IS NULL), `idx_cars_last_refresh`.

### `pending_ids`

```sql
source TEXT, source_id TEXT, metadata JSONB,
found_at TIMESTAMPTZ,
failed_attempts INT NOT NULL DEFAULT 0,
last_failed_at TIMESTAMPTZ,
PRIMARY KEY (source, source_id)
```

`metadata` — снапшот из XHR-collect: car_year, brand_name, series_name, city. Используется в коллекторе для фильтра по году до парсинга карточек.

Индекс `idx_pending_ids_quarantine` для быстрого пропуска квартанированных.

### `changes`

```sql
id BIGSERIAL PK,
source TEXT, source_id TEXT,
change_type TEXT,           -- 'price_drop' | 'sold' | (будущие: 'km_age', 'images')
old_value JSONB, new_value JSONB,
created_at TIMESTAMPTZ
```

Лента событий для фронта. Сейчас пишутся:

| change_type | когда | old_value | new_value |
|---|---|---|---|
| `price_drop` | refresh нашёл цену ниже | `{price_original, price_currency}` | то же, новое |
| `sold` | 3 фейла подряд при refresh | `{last_price, price_currency, consecutive_fails}` | `{sold_at}` |

Подорожание **не** логируется намеренно (редко бывает у б/у; цена в `cars` всё равно обновится через upsert).

### View `cars_kz_view`

Добавляет вычисляемые поля поверх `cars`:

- `age_years` — `EXTRACT(YEAR FROM CURRENT_DATE) - year`
- `evro_class` — 3/4/5/6 по году
- `kz_importable` — `year >= 2022 AND engine_type != 'Electric'`
- `kz_status` — `ok` / `older_than_2022` / `ev_no_subsidy_2026` / `unknown_year`

Если правила КЗ изменятся — пересоздавать view, данные в `cars` не трогать.

### RLS

**Сейчас отключён** на всех таблицах (`cars`, `pending_ids`, `changes`). Намеренно пока нет публичного фронта. Когда подключим anon-доступ — включить и написать политики.

---

## GitHub Actions workflows

### `scrape.yml` — Daily Discover + Scrape

**Триггеры:**
- `schedule: 0 19 * * *` — каждый день в 19:00 UTC = 03:00 Пекин
- `workflow_dispatch` — вручную с 9 параметрами (cities, brands, scrolls, batch_size, batch_pause, min_year, collect_limit, scrape_limit, workers)

**Шаги:**
1. Setup Python 3.12 + `pip install -r requirements.txt`
2. `python collect_ids.py …` — собрать новые ID
3. `python scrape_dongchedi.py --skip-listing …` — спарсить карточки

**Timeout:** 350 минут (полный прогон 25–35 мин для collect + 30–60 мин для scrape).

### `refresh.yml` — Weekly Re-check

**Триггеры:**
- `schedule: 0 22 * * 0` — каждое воскресенье 22:00 UTC = 06:00 Пекин понедельник
- `workflow_dispatch` — вручную: `limit` (или `all=true`), `workers`

**Шаг:** `python refresh_cars.py --all --workers 10`. Cron всегда делает full refresh; manual может ограничить `--limit`.

### Secrets

| Имя | Содержимое |
|---|---|
| `OXY_USER` | Oxylabs username |
| `OXY_PASS` | Oxylabs password |
| `SUPABASE_URL` | https://pdmbdclhqiqyoomeswxs.supabase.co |
| `SUPABASE_KEY` | **service_role** JWT (не anon!) |

⚠️ Имя `SUPABASE_KEY` важное (не `SUPABASE_SERVICE_KEY` как в некоторых старых черновиках) — внутри service_role.

---

## Локальный запуск

```bash
# Переменные окружения
export OXY_USER="..."
export OXY_PASS="..."
export SUPABASE_URL="https://pdmbdclhqiqyoomeswxs.supabase.co"
export SUPABASE_KEY="..."     # service_role

# Шаг 1: собрать ID (10–35 мин)
python collect_ids.py --cities beijing,shanghai,guangzhou,shenzhen \
    --brands all --scrolls 8 --batch-size 4 --batch-pause 3 \
    --min-year 2022 --limit 10000

# Шаг 2: спарсить карточки (~3 мин на 100 карточек)
python scrape_dongchedi.py --skip-listing --limit 2000 --workers 10

# Шаг 3: refresh (только если нужно проверить старые)
python refresh_cars.py --limit 100 --workers 10

# Dry-run refresh — посмотреть что бы изменилось без записи
python refresh_cars.py --limit 50 --dry-run
```

Если `SUPABASE_URL`/`SUPABASE_KEY` не заданы — `db.py` автоматически свалится в SQLite `cars.db` (схема та же).

---

## Стоимость Oxylabs

| Тип запроса | Цена |
|---|---|
| Без `render` | $0.002 |
| `render=html` | $0.003 |
| `render=html + browser_instructions` | $0.04 |
| `render=html + xhr + scrolls` | ~$0.04 |

Один полный daily прогон:
- collect: 316 URL × $0.04 ≈ **$12.6**
- scrape: ~800 новых карточек × $0.04 ≈ **$32**
- **Итого ~$45/день** (пик), после стабилизации база ~$15–20/день

Weekly refresh: 1390 × $0.04 ≈ **$55/неделя**.

Бюджет: **~$200–250/месяц на Oxylabs**. Если дорого — резать кол-во городов или брендов в daily collect.

---

## Brand pool

В `collect_ids.py:BRAND_POOL` — 80 брендов, ID и названия. Группы:

| Группа | Кол-во | Примеры |
|---|---|---|
| Premium Euro | 10 | Mercedes, BMW, Audi, Porsche, Volvo, Land Rover, Lexus, Cadillac, Bentley, Maybach |
| Sport / Luxury | 5 | Ferrari, Rolls-Royce, Aston Martin, Lamborghini, McLaren |
| Mainstream foreign | 12 | VW, Toyota, Honda, Nissan, Ford, Buick, Hyundai, Kia, Tesla, Chevrolet, Jeep, Lincoln |
| Niche foreign | 8 | MINI, smart, Skoda, Mazda, Subaru, Infiniti, Genesis, Peugeot |
| Chinese majors | 12 | BYD, Geely, Chery, Haval, Changan, Roewe, Hongqi, GAC Trumpchi, Lynk&Co, Tank, Great Wall, WEY |
| Chinese EV / NEV | 13 | NIO, XPeng, Li Auto, Xiaomi, AITO, Zeekr, Aion, Leapmotor, Denza, Voyah, Deepal, IM Motors, AVATR |
| Chinese sub-brands | 17 | Changan Qiyuan, Geely Galaxy, Jetour, Exeed, Baojun, Bestune, Geometry, ORA, Arcfox, Radar, Fang Cheng Bao, YangWang, GAC Hyper, Dongfeng eP, Jetta, BAIC, BAIC Off-road |
| Italian + Suzuki | 2 | Maserati, Suzuki |

Полный список 642 брендов dongchedi доступен в их каталоге (можно скачать через тот же XHR — пока не используется).

---

## Известные проблемы и TODO

### Качество данных
- **`body_type` иногда пустой** для редких моделей. Fallback расширен (Range Rover, Defender, BMW X, Audi Q, MB GL*, MPV, пикапы, купе), но для совсем экзотики (Bugatti, Koenigsegg) всё ещё может быть пусто.
- **`engine_type = "-"`** обработано: fallback из `model` (Petrol/PHEV/EREV/Hybrid/Electric).
- **Метаданные из XHR не используются в карточке.** В `pending_ids.metadata` лежат `car_year`, `brand_name` из XHR — парсер карточки получает то же из `__NEXT_DATA__`. Можно использовать metadata как fallback если карточка вернула пусто (низкий приоритет).

### Скорость / стоимость
- **Beijing/Shenzhen иногда возвращают 0** в collect — Oxylabs throttle при 4+ параллельных. Если повторяется — снизить `--batch-size` до 2 (~+20% времени, та же стоимость).
- **Daily collect = $12.6** — самая дорогая часть. Можно сократить до 2 городов (≈ $6) если найдём что они покрывают большинство.

### Расширение
- **VIN** у dongchedi нет в публичных полях → второй парсер **che168.com** (есть VIN, тот же brand×city подход).
- **Inspection report** dongchedi имеет, но мы не парсим — поле `cars.source_data` (JSONB) под это заложено.
- **Больше городов** — сейчас 4 топ-города, в БД 97 уникальных. Расширить до Chengdu/Hangzhou/Chongqing/Wuhan.

### Не работает (проверено и отбросили)
- ❌ Прямой POST к `/motor/pc/sh/sh_sku_list` — защищено `msToken`.
- ❌ `?page=N` в URL листинга — игнорируется.
- ❌ `geo_location="Beijing"` в Oxylabs — поддерживает только `"China"`.
- ❌ Bright Data, Firecrawl — не подошли.

---

## История критических открытий

1. **`__NEXT_DATA__` содержит skuDetail** — все данные карточки в одном JSON-блоке HTML.
2. **URL имеет 28 позиций** через дефис (не 19 как было в старых черновиках).
3. **Oxylabs `xhr: true` захватывает `sh_sku_list`** — структурированный JSON листинга без HTML-regex.
4. **`SUPABASE_KEY` secret name** (не `SUPABASE_SERVICE_KEY`).
5. **Brand × City стратегия** — 79 × 4 = 316 URL → ~800 новых машин за прогон вместо ~220 без фильтра по бренду.
6. **`failed_attempts` quarantine** — 0.5% мёртвых ID больше не тратят бюджет каждый прогон.
7. **`sold_at` via 3 consecutive fails** — детект снятых объявлений без отдельного индикатора со стороны dongchedi.
