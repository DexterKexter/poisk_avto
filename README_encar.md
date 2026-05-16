# Encar.com — парсер б/у автомобилей (Корея)

Парсер объявлений с южнокорейского классифайда [encar.com](https://www.encar.com). Те же поля что у dongchedi + **VIN** и история ДТП. Используется тот же multi-source schema в Supabase.

---

## Содержание

1. [Архитектура](#архитектура)
2. [Откуда берутся данные](#откуда-берутся-данные)
3. [Файлы парсера](#файлы-парсера)
4. [Шаг 1: `collect_encar.py`](#шаг-1-collect_encarpy)
5. [Шаг 2: `scrape_encar.py`](#шаг-2-scrape_encarpy)
6. [Маппинг полей](#маппинг-полей)
7. [GitHub Actions](#github-actions)
8. [Локальный запуск](#локальный-запуск)
9. [Стоимость](#стоимость)
10. [Известные особенности](#известные-особенности)

---

## Архитектура

```
┌────────────────────────────────────────────────────────────┐
│ Шаг 1: collect_encar.py                                    │
│   GET car.encar.com/list/car?page=N&search=...             │
│   render=html, 1 страница = ~250 машин                     │
│   Из __NEXT_DATA__:                                        │
│     props.pageProps.initialState.ryvussApi.queries.*       │
│     getCarNormal (200) + Preferential (40) + Premium (10)  │
│        ↓                                                   │
│   pending_ids (Supabase) — 28 полей в metadata             │
└────────────────────────────────────────────────────────────┘
        ↓
┌────────────────────────────────────────────────────────────┐
│ Шаг 2: scrape_encar.py                                     │
│   GET api.encar.com/v1/readside/vehicles                   │
│       ?vehicleIds=ID1,ID2,ID3,ID4,ID5                      │
│       &include=SPEC,ADVERTISEMENT,PHOTOS,...               │
│   БЕЗ render → $0.002 за batch из 5 машин                  │
│        ↓                                                   │
│   cars (Supabase) с VIN + опциями + фото + описанием       │
└────────────────────────────────────────────────────────────┘
```

---

## Откуда берутся данные

### Шаг 1 — листинг (`car.encar.com/list/car`)

Encar построен на Next.js. Открываем страницу через Oxylabs `render=html`, извлекаем `<script id="__NEXT_DATA__">…</script>`. Внутри JSON-структура:

```
props.pageProps.initialState.ryvussApi.queries.<функция>(<JSON-аргументы>)
  .data.SearchResults  →  список машин
```

На одной странице 3 раздела (объединяем все):

| Раздел | Кол-во | Что |
|---|---|---|
| `getCarNormal` | 200 | Обычные объявления |
| `getCarPreferential` | 40 | Premium tier (платное продвижение) |
| `getCarPremium` | 10 | Top Premium |

**Пагинация** через `?page=N`. Сортировка по `MobileModifiedDate` (свежие первыми).

Поля одной машины из листинга (28 шт):
`Id, Manufacturer, Model, ModelGroup, Badge, Year, FormYear, Mileage, Price, Color, ColorExpression, SeatColor, FuelType, Transmission, Photos[], OfficeCityState, Trust[], ServiceMark[], Condition[], AdType[], BuyType[], …`

Этого достаточно для базовой карточки, но **нет VIN, опций, описания, ДТП**.

### Шаг 2 — карточка (`api.encar.com/v1/readside/vehicles`)

Encar держит публичный (без авторизации) JSON-эндпоинт:

```
GET https://api.encar.com/v1/readside/vehicles
    ?vehicleIds=ID1,ID2,ID3,ID4,ID5
    &include=SPEC,ADVERTISEMENT,PHOTOS,CATEGORY,MANAGE,CONTACT,VIEW,
             OPTIONS,CONDITION,PARTNERSHIP,CONTENTS,VEHICLETYPE
```

Возвращает массив объектов по 5 машин за запрос. Каждый объект имеет 15 верхнеуровневых блоков:

| Блок | Что внутри |
|---|---|
| `manage` | id, даты регистрации/изменения, viewCount |
| `category` | manufacturer/model/grade (KR + EN), yearMonth, originPrice, warranty |
| `advertisement` | price, trust[], diagnosisCar, status |
| `contact` | userId, userType (DEALER/PRIVATE), phone, address |
| `spec` | mileage, displacement, fuelName, transmissionName, colorName, bodyName, seatCount |
| `photos[]` | до 20 фото с типами INNER/OUTER/OPTION |
| `options` | списки кодов опций (standard/etc/choice/tuning) |
| `condition` | accident (recordView/resumeView), inspection, seizing |
| `partnership` | dealer info, диагностические центры |
| `contents` | описание от продавца на корейском |
| `view` | количество просмотров |
| `vin` | 17-значный VIN ✅ |
| `vehicleNo` | корейский регистрационный номер |

**Эндпоинт работает без render** — поэтому стоит $0.002 вместо $0.04.

---

## Файлы парсера

```
poisk_avto/
├── collect_encar.py                  # Шаг 1: listing → pending_ids
├── scrape_encar.py                   # Шаг 2: API → cars
├── README_encar.md                   # этот файл
└── .github/workflows/
    └── scrape-encar.yml              # daily 20:00 UTC + manual dispatch
```

Общая инфраструктура (тоже используется):
- `db.py` — Supabase REST API клиент (общий для всех источников)
- `refresh_cars.py` — refresh + sold detection (пока только для dongchedi, нужна доработка для encar)

---

## Шаг 1: `collect_encar.py`

**Что делает.** Параллельно (2 воркера) идёт по страницам листинга, объединяет машины из всех трёх разделов, дедуплицирует по `Id`, фильтрует по году, записывает в `pending_ids`.

**Параметры:**

```
--pages        5         # сколько страниц фетчить (по ~250 машин)
--batch-size   2         # параллельных запросов
--batch-pause  3
--min-year     0         # 0 = без фильтра, иначе Year < min_year*100 отбрасывается
--limit        10000     # макс новых ID в БД
```

**Output:** записи в `pending_ids` с metadata = весь dict машины из листинга (28 полей минус Photos).

**Фильтр года.** В листинге `Year` — это `int` формата YYYYMM (например `202210` = октябрь 2022). Параметр `--min-year 2022` транслируется в `Year >= 202200`. Поскольку для КЗ-фильтра пока решили `пока нет фильтра`, дефолт = 0.

---

## Шаг 2: `scrape_encar.py`

**Что делает.** Берёт ID из `pending_ids` (исключая уже спарсенные и quarantine), группирует по 5, параллельно дёргает API, маппит JSON в схему `cars`, записывает.

**Параметры:**

```
--limit    500   # макс машин за прогон
--workers  5     # параллельных batch-запросов (каждый = 5 машин)
```

**Quarantine.** Если batch вернул ошибку или машина не пришла в ответе — `pending_ids.failed_attempts += 1`. После 3-х подряд ID в карантине.

---

## Маппинг полей

Полная таблица соответствия encar API → `cars` schema:

| Колонка в `cars` | Источник | Пример |
|---|---|---|
| `source` | `'encar'` | — |
| `source_id` | `manage.dummyVehicleId` | `"41203231"` |
| `source_language` | `'ko'` | — |
| `url` | `https://fem.encar.com/cars/detail/{source_id}` | — |
| `title` | `manufacturerEnglishName + modelGroupEnglishName + gradeEnglishName` | `"BMW 5-Series 520i Luxury"` |
| `mark_original` | `category.manufacturerName` | `"BMW"` |
| `mark` | `category.manufacturerEnglishName` | `"BMW"` |
| `series_original` | `category.modelName` | `"5시리즈 (G30)"` |
| `model` | `modelGroupEnglishName + gradeEnglishName` | `"5-Series 520i Luxury"` |
| `complectation` | `category.gradeEnglishName` | `"520i Luxury"` |
| `year` | `int(category.yearMonth[:4])` | `2022` |
| `price_original` | `advertisement.price * 10000` | `31_700_000` |
| `price_currency` | `'KRW'` | — |
| `new_price_original` | `category.originPrice * 10000` | `66_000_000` |
| `km_age_original` / `km_age` | `spec.mileage` | `68546` |
| `color_original` | `spec.colorName` | `"흰색"` |
| `color` | через `COLOR_MAP` | `"White"` |
| `body_type` | `spec.bodyName` через `BODY_MAP` | `"Sedan"` |
| `engine_type` | `spec.fuelName` через `FUEL_MAP` | `"Petrol"` |
| `transmission_type` | `spec.transmissionName` через `TRANSMISSION_MAP` | `"Automatic"` |
| `displacement` | `spec.displacement / 1000` | `2.0` |
| `city_original` | первое слово `contact.address` | `"경기"` |
| `city` | через `REGION_MAP` | `"Gyeonggi"` |
| `reg_date` | `yearMonth` → `YYYY-MM-01` | `"2022-10-01"` |
| `vin` | `api_car.vin` (top-level) | `"WBA11BH03NWX84984"` |
| `images` | `[IMAGE_BASE + p.path for p in photos]` | до 20 URL |
| `seller_type` | `Dealer` если `contact.userType == "DEALER"` | `"Dealer"` |
| `shop_name` | `partnership.dealer.firm.name` | `"아차차"` |
| `description` | `contents.text` | (длинный корейский текст) |
| `source_data` | JSONB со всем остальным (см. ниже) | — |

**В `source_data` JSONB:**

```json
{
  "vehicle_no": "115버6345",
  "vehicle_id": 41202236,
  "year_month": "202210",
  "import_type": "REGULAR_IMPORT",
  "domestic": false,
  "warranty": {...},
  "trust": ["HomeService", "Warranty"],
  "diagnosis_car": true,
  "accident": {"recordView": true, "resumeView": true},
  "inspection_formats": ["TABLE"],
  "seizing": {"seizingCount": 0, "pledgeCount": 0},
  "option_codes_standard": ["001", "004", ...],
  "option_codes_etc": [],
  "option_codes_choice": [],
  "option_codes_tuning": [],
  "dealer_phone": "05062322680",
  "dealer_firm_code": "4829",
  "dealer_diagnosis_centers": [{...}, {...}],
  "view_count": 756,
  "subscribe_count": 24,
  "regist_datetime": "2025-12-19T15:07:26",
  "first_advertised_datetime": "2026-04-19T21:24:18",
  "modify_datetime": "2026-05-07T14:24:05"
}
```

**Корейские словари переводов** в `scrape_encar.py`:

- `COLOR_MAP` — 흰색→White, 검정색→Black, …
- `FUEL_MAP` — 가솔린→Petrol, 디젤→Diesel, 하이브리드→Hybrid, …
- `TRANSMISSION_MAP` — 오토→Automatic, 수동→Manual, …
- `BODY_MAP` — 중형차→Sedan, SUV→SUV, 미니밴→Minivan, …
- `REGION_MAP` — 서울→Seoul, 경기→Gyeonggi, 부산→Busan, …

---

## GitHub Actions

### `scrape-encar.yml`

**Триггеры:**
- `schedule: 0 20 * * *` — каждый день 20:00 UTC = 05:00 Сеул
- `workflow_dispatch` — вручную (pages, min_year, collect_limit, scrape_limit, workers)

**Шаги:**
1. Setup Python + `pip install -r requirements.txt`
2. `python collect_encar.py …` — собрать новые ID
3. `python scrape_encar.py …` — спарсить карточки через API

**Secrets** (те же что у dongchedi):
- `OXY_USER`, `OXY_PASS` — Oxylabs
- `SUPABASE_URL`, `SUPABASE_KEY` — service_role JWT

---

## Локальный запуск

```bash
export OXY_USER="..."
export OXY_PASS="..."
export SUPABASE_URL="https://pdmbdclhqiqyoomeswxs.supabase.co"
export SUPABASE_KEY="..."

# Шаг 1: собрать ID (5 страниц = ~1250 машин, ~5 мин)
python collect_encar.py --pages 5 --min-year 0 --limit 5000

# Шаг 2: спарсить карточки (~50 batch'ей по 5 = 250 машин)
python scrape_encar.py --limit 250 --workers 5
```

---

## Стоимость

| Операция | Цена | Что |
|---|---|---|
| 1 страница листинга | $0.04 | 250 машин (render=html) |
| 1 batch карточек (5 машин) | $0.002 | API без render |
| Bootstrap 2500 машин | **$1.40** | 10 страниц + 500 batch'ей |
| Daily refresh новых ~500/день | **$0.30** | 2 страницы + 100 batch'ей |
| Месячный бюджет (daily cron) | **~$10** | 30 дней |

**В 30 раз дешевле dongchedi** на ту же базу. Главная причина — публичный API без render.

---

## Известные особенности

- **VIN всегда есть** в детальной API-ответе как top-level поле — это главное преимущество encar над dongchedi.
- **Цена в `万`** (10000 KRW) — нужно умножать на 10000.
- **`yearMonth`** в формате `"202210"` — год-месяц регистрации.
- **`vehicleId` ≠ `dummyVehicleId`** — это два разных ID. `dummyVehicleId` (он же `Id` в листинге) используется для URL; `vehicleId` — для некоторых внутренних API. Мы храним `dummyVehicleId` как `source_id`.
- **Фото** через `https://ci.encar.com{path}` где path выглядит как `/carpicture10/pic4120/41202236_001.jpg`. Если URL не работает — попробовать другие хосты (img1.encar.com и т.п.).
- **Опции** возвращаются как **коды** (`["001", "004", …]`). Расшифровка кодов потребует отдельного словаря (см. эндпоинт `/verification/{Id}/simple?optionIds=...`).
- **API не требует авторизации** на момент написания. Если encar внедрит токены — переключаемся на render-режим (всё ещё дёшево по сравнению с dongchedi).
- **Корейский регистрационный номер** (`vehicleNo`) — например `"115버6345"`. Хранится в `source_data` для справки.

---

## История recon-открытий

1. **`car.encar.com/list/car`** — Next.js SSR, данные в `__NEXT_DATA__`.
2. **3 раздела** на странице (Normal/Preferential/Premium) = 250 машин за запрос.
3. **`fem.encar.com/cars/detail/{Id}`** — React-приложение, в HTML данных нет, всё через XHR.
4. **`api.encar.com/v1/readside/vehicles?...`** — публичный JSON-эндпоинт, поддерживает batch до 5 ID.
5. **VIN, опции, ДТП, фото, описание** — всё в одном API-ответе.
6. **API работает без render** через Oxylabs — $0.002 вместо $0.04 за запрос.
