# Dongchedi.com Scraper — Документация

Парсер объявлений о продаже б/у автомобилей с китайского сайта dongchedi.com через Oxylabs Web Scraper API. Собирает структурированные данные в SQLite базу.

---

## Архитектура

Проект состоит из двух Python скриптов, работающих с одной общей SQLite базой `cars.db`:

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  Шаг 1:  collect_ids.py                                      │
│          ↓                                                   │
│          Открывает страницу-листинг dongchedi в headless     │
│          браузере через Oxylabs, скроллит вниз чтобы         │
│          подгрузить машины через внутренний API сайта,       │
│          извлекает sku_id из финального HTML                 │
│          ↓                                                   │
│          Записывает sku_id в таблицу pending_ids             │
│                                                              │
│  Шаг 2:  scrape_dongchedi.py --skip-listing                  │
│          ↓                                                   │
│          Берёт sku_id из pending_ids, для каждого            │
│          открывает страницу карточки через Oxylabs           │
│          (render=html), извлекает JSON __NEXT_DATA__,        │
│          парсит ~40 полей, переводит китайский на латиницу   │
│          ↓                                                   │
│          Записывает полные данные в таблицу cars             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

Файлы:
- `collect_ids.py` — сбор sku_id с листинговой страницы dongchedi
- `scrape_dongchedi.py` — парсинг полной карточки по sku_id
- `cars.db` — SQLite база с таблицами `pending_ids`, `cars`, `seen_ids`

---

## Технологический стек

| Компонент | Что | Зачем |
|---|---|---|
| **Oxylabs Web Scraper API** | Realtime endpoint `https://realtime.oxylabs.io/v1/queries` | Прокси-сервис с китайскими IP и headless-браузером. Обходит блокировки dongchedi |
| **source: universal** | Тип job в Oxylabs API | Универсальный скрейпинг произвольных URL |
| **geo_location: China** | Параметр Oxylabs | Запрос идёт с IP внутри Китая (Beijing) — иначе dongchedi отдаёт пустую страницу |
| **render: html** | Параметр Oxylabs | Запускает реальный браузер (Chromium) для рендера JavaScript |
| **browser_instructions** | Команды браузеру | Действия после загрузки (скролл, клик, ожидание) |
| **__NEXT_DATA__** | JSON-блок в HTML карточки | Содержит все структурированные данные о машине (Next.js гидратация) |
| **Python 3.12** | runtime | Локально на Windows |
| **requests** | HTTP клиент | Запросы к Oxylabs |
| **sqlite3** | стандартная библиотека Python | Локальная база |
| **concurrent.futures.ThreadPoolExecutor** | стандартная библиотека | Параллельная обработка карточек |

---

## Шаг 1. Сбор sku_id (collect_ids.py)

### Что делает

Открывает URL листинга dongchedi в headless-браузере Oxylabs, скроллит страницу вниз 10 раз. На каждом скролле сам сайт через свой внутренний JS-код подгружает следующую порцию объявлений (lazy loading). После всех скроллов забирается финальный HTML с накопленными карточками. Из HTML регуляркой извлекаются все sku_id (ссылки `/usedcar/{цифры}` где число от 7 знаков).

### Ключевые параметры

URL листинга:
```
https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x
```
19 позиций `x` — это места под фильтры (бренд, цена, год, кузов и т.д.). Все `x` = "без фильтра" = "все машины".

Oxylabs payload:
```python
{
    "source": "universal",
    "url": LISTING_URL,
    "geo_location": "China",
    "locale": "zh-CN",
    "render": "html",
    "browser_instructions": [
        {"type": "scroll_to_bottom", "wait_time_s": 2},
        ...   # 10 раз
    ]
}
```

`scroll_to_bottom` с `wait_time_s: 2` — скролл в самый низ + пауза 2 сек, чтобы успел отработать lazy-load. 10 скроллов даёт ~70 машин за один прогон (лимит времени Oxylabs ~120 сек на job с render+instructions).

### Регулярка извлечения sku_id

```python
CARD_LINK_RE = re.compile(r'/usedcar/(\d{7,})')
```

7+ цифр — это минимум для реальных ID объявлений. Короче — навигационные ссылки (`/usedcar/5`, `/usedcar/0`).

### Запуск

```powershell
$env:OXY_USER="ВАШ_USER"
$env:OXY_PASS="ВАШ_PASS"

python collect_ids.py --limit 1000 --scrolls 10
```

Один запуск возвращает ~70-80 уникальных ID. Повторные запуски докидывают в `pending_ids` новые ID которых ещё не было (dongchedi отдаёт разный порядок при каждом обращении).

### Стоимость

Один запуск листинга с render+browser_instructions = ~$0.03-0.05 в Oxylabs. Собрать 1000 ID = ~$0.50-1.00 (15 прогонов).

---

## Шаг 2. Парсинг карточек (scrape_dongchedi.py)

### Что делает

Для каждого sku_id из таблицы `pending_ids` (или из листинга если запущено без `--skip-listing`):
1. Открывает URL карточки `https://www.dongchedi.com/usedcar/{sku_id}` в headless-браузере Oxylabs
2. Из готового HTML извлекает JSON-блок `<script id="__NEXT_DATA__">`
3. Из JSON парсит все поля, переводит китайский на латиницу через словари
4. Сохраняет в таблицу `cars`

### Структура __NEXT_DATA__

Все данные карточки лежат в `props.pageProps.skuDetail`:

```
skuDetail
├── car_info
│   ├── brand_name              → mark_cn ("奔驰")
│   ├── series_name             → series_cn ("奔驰GLA")
│   ├── car_name                → используется в model
│   ├── year                    → year (2017)
│   ├── body_color              → color_cn
│   ├── mileage                 → km_age (после парсинга "8.20万公里")
│   ├── series_type             → body_type (код 0-8)
│   └── series_new_energy_type  → engine_type (код 0-4)
│
├── source_sh_price             → price_cny (делим на 100: фынь → CNY)
├── source_offical_price        → new_price_cny
│
├── car_config_overview
│   ├── power
│   │   ├── acceleration_time     → acceleration_time ("8.5s")
│   │   ├── capacity              → displacement ("1.6T")
│   │   ├── fuel_form             → fuel_cn ("汽油")
│   │   ├── gearbox_description   → transmission_cn ("7挡双离合")
│   │   └── horsepower            → horse_power ("156马力" → 156)
│   ├── manipulation.driver_form  → drive_cn ("前置前驱" → FWD)
│   └── space                     → length_mm/width_mm/height_mm/wheelbase_mm
│
├── other_params (массив name/value)
│   ├── 上牌地       → reg_city_cn (где зарегистрировано)
│   ├── 车源地       → city_cn (источник)
│   ├── 过户次数     → owners_count
│   ├── 上牌时间     → reg_date ("2017年08月" → "2017-08-01")
│   ├── 排量         → displacement (резервный источник)
│   ├── 变速箱       → transmission_cn (резервный)
│   ├── 车身颜色     → color_cn (резервный)
│   ├── 内饰颜色     → interior_color_cn
│   └── 保养方式     → maintenance
│
├── head_images (до 30 URL фото)  → images, image_count
├── sh_car_desc                   → description
└── shop_info
    ├── shop_name                 → shop_name
    ├── shop_short_name           → shop_short_name
    ├── shop_address              → shop_address
    ├── city_name                 → city_cn (резервный)
    ├── shop_id                   → shop_id
    ├── sales_car_num             → shop_cars_count
    └── shop_type                 → seller_type ("Dealer" / "Private")
```

### Переводы китайский → латиница

Применяются через словари в коде:

- **BRAND_MAP** (~120 брендов): 奔驰→Mercedes-Benz, 宝马→BMW, 比亚迪→BYD, 蔚来→NIO, 理想→Li Auto, 小米→Xiaomi, 领克→Lynk & Co, 红旗→Hongqi, 荣威→Roewe, 极氪→Zeekr, 智己→IM Motors, 深蓝→Deepal, 哪吒→Neta, 问界→AITO и т.д.
- **COLOR_MAP**: 白色→White, 黑色→Black, 银色→Silver, 灰色→Gray, 蓝色→Blue, 红色→Red, 棕色→Brown, 香槟色→Champagne и т.д.
- **FUEL_MAP**: 汽油→Petrol, 柴油→Diesel, 纯电→Electric, 油电混合→Hybrid, 插电混动→PHEV, 增程式→EREV
- **TRANSMISSION_MAP**: 手动→Manual, 自动→Automatic, 无级变速→CVT, 双离合→DCT
- **DRIVE_MAP**: 前置前驱→FWD, 前置后驱→RWD, 全时四驱→AWD, 适时四驱→AWD
- **BODY_MAP** (резервный): 轿车→Sedan, SUV→SUV, MPV→Minivan, 跑车→Sports Car, 皮卡→Pickup и т.д.

Для body_type приоритет — числовой код `series_type` в JSON (0=Sedan, 1=SUV, 2=Minivan, 3=Pickup, 4=Sports Car, 6=Light Commercial, 7=Microvan, 8=Mini Truck). Если код не задан — fallback на анализ series_name (содержит "SUV", "越野", "MPV").

### Парсеры значений

```python
parse_wan("8.20万公里")     → 82000.0      # "万" = 10000
parse_reg_date("2017年08月") → "2017-08-01"
parse_horse_power("156马力") → 156
parse_displacement("1.6T")   → 1.6         # парсит "1.6T" и "2.0L"
parse_owners("4次")          → 4
```

Цены: dongchedi возвращает в JSON `source_sh_price: 5880000` — это **фынь** (1/100 юаня). Делим на 100 → 58800 CNY.

### Запуск

```powershell
# Если уже есть sku_id в pending_ids (после collect_ids.py):
python scrape_dongchedi.py --skip-listing --limit 1000 --workers 5

# Или быстрый прогон без collect_ids (берёт IDs прямо с первой страницы листинга, ~60 машин):
python scrape_dongchedi.py --cities bj --limit 60 --workers 5
```

### Параллелизм

`--workers 5` запускает 5 потоков параллельно. Oxylabs выдерживает 10+ параллельных запросов на один аккаунт. Производительность: ~50 машин за 5 минут, ~600 машин в час.

### Стоимость

Каждая карточка = 1 рендер через Oxylabs = ~$0.002. **1000 машин ≈ $2.**

### Результат проверенного прогона

Тестовый прогон на 50 машинах:
- 48 OK / 2 FAIL = **96% успех**
- Спарсенные бренды: BMW, Mercedes-Benz, Audi, Toyota, Ford, Volkswagen, Roewe, Hyundai, Lynk & Co, BYD, Porsche, Honda, Nissan, Buick, Volvo, Kia, Chevrolet, Cadillac, Smart, Hongqi, Land Rover, Changan, Lincoln, Haval
- Все поля заполнены корректно: цены в юанях, пробег в км, габариты, фото (15-30 шт на машину), описание

---

## База данных (cars.db)

### Таблица pending_ids

Очередь sku_id для обработки. Заполняется `collect_ids.py`, читается `scrape_dongchedi.py --skip-listing`.

| Поле | Тип | Описание |
|---|---|---|
| sku_id | TEXT PK | ID объявления на dongchedi |
| brand_name, series_name, car_name | TEXT | Из listing API (если успели подтянуть) |
| car_year | INTEGER | Год выпуска |
| car_source_city_name | TEXT | Город-источник |
| sh_city_name | TEXT | Город фильтра |
| shop_id | TEXT | ID магазина |
| transfer_cnt | INTEGER | Кол-во передач |
| found_at | TEXT | ISO timestamp когда нашли |

### Таблица cars

Главная таблица с полными данными по машинам. PK: `inner_id` (= sku_id).

```sql
CREATE TABLE cars (
    inner_id TEXT PRIMARY KEY,           -- ID карточки на dongchedi
    url TEXT,                            -- https://www.dongchedi.com/usedcar/{id}
    title TEXT,                          -- Полный заголовок объявления
    mark_cn TEXT, mark TEXT,             -- Бренд (китайский / латиница)
    series_cn TEXT,                      -- Серия (китайский)
    model TEXT,                          -- Полное название "奔驰GLA GLA 200 动感型"
    complectation TEXT,                  -- Только trim "GLA 200 动感型"
    year INTEGER,                        -- Год выпуска
    price_cny REAL,                      -- Цена в юанях (число)
    new_price_cny REAL,                  -- Цена нового авто в юанях
    km_age REAL,                         -- Пробег в км (число)
    color_cn TEXT, color TEXT,           -- Цвет кузова
    body_type TEXT,                      -- Sedan / SUV / Minivan / Pickup / ...
    engine_type TEXT, fuel_cn TEXT,      -- Petrol / Electric / Hybrid / PHEV / EREV
    transmission_cn TEXT,                -- КПП (китайский, полное)
    transmission_type TEXT,              -- Manual / Automatic / CVT / DCT
    drive_cn TEXT, drive_type TEXT,      -- FWD / RWD / AWD
    displacement REAL,                   -- Объём двигателя (литры, например 1.6)
    horse_power INTEGER,                 -- Мощность в л.с.
    acceleration_time TEXT,              -- Разгон 0-100 ("8.5s")
    length_mm INTEGER,                   -- Длина в мм
    width_mm INTEGER,                    -- Ширина в мм
    height_mm INTEGER,                   -- Высота в мм
    wheelbase_mm INTEGER,                -- Колёсная база в мм
    city_cn TEXT,                        -- Город (китайский)
    reg_city_cn TEXT,                    -- Город регистрации
    reg_date TEXT,                       -- Дата регистрации (YYYY-MM-DD)
    owners_count INTEGER,                -- Кол-во владельцев
    maintenance TEXT,                    -- Способ обслуживания
    interior_color_cn TEXT,              -- Цвет салона
    description TEXT,                    -- Описание продавца
    images TEXT,                         -- JSON-массив URL фото
    image_count INTEGER,                 -- Кол-во фото
    seller_type TEXT,                    -- Dealer / Private
    shop_name TEXT,                      -- Полное название салона
    shop_short_name TEXT,                -- Короткое название
    shop_address TEXT,                   -- Физический адрес
    shop_id TEXT,                        -- ID салона
    shop_cars_count INTEGER,             -- Сколько машин у этого дилера
    sales_range TEXT,                    -- Радиус продаж
    spu_id TEXT,                         -- SPU ID (родительский)
    first_seen TEXT,                     -- Когда впервые увидели
    last_seen TEXT                       -- Когда обновили последний раз
);

CREATE INDEX idx_mark ON cars(mark);
CREATE INDEX idx_year ON cars(year);
CREATE INDEX idx_price ON cars(price_cny);
CREATE INDEX idx_city ON cars(city_cn);
```

### Таблица seen_ids

Лог всех id которые мы уже спарсили в cars. Используется чтобы не парсить одно и то же повторно.

```sql
CREATE TABLE seen_ids (
    inner_id TEXT PRIMARY KEY,
    first_seen TEXT
);
```

### Resume

Скрипты **resume-friendly**:
- `collect_ids.py` — добавляет в `pending_ids` через INSERT OR REPLACE, не дублирует
- `scrape_dongchedi.py` — для обновления используется `INSERT ... ON CONFLICT DO UPDATE` по PK `inner_id`. Уже обработанные ID берутся из `seen_ids`, новые из `pending_ids \ seen_ids`. Можно прерывать Ctrl+C и запускать заново — продолжит с того же места.

---

## Что собирается (поля)

Сравнение с auto-api.com/dongchedi (конкурент):

| Поле | auto-api | наш парсер |
|---|---|---|
| mark, model, complectation | да | да |
| year, price_cny | да | да |
| **new_price_cny** (цена нового) | нет | **да** |
| km_age | да | да |
| color, body_type, engine_type | да | да |
| transmission_type, drive_type | да | да |
| displacement, horse_power | да | да |
| **acceleration_time** | нет | **да** |
| **габариты (length/width/height/wheelbase)** | нет | **да** |
| city, reg_city, reg_date | да | да |
| owners_count | да | да |
| description | да | да |
| images[] | да | да |
| seller_type, shop_name | да | да |
| **shop_address** (адрес салона) | нет | **да** |
| **shop_cars_count** (кол-во машин у дилера) | нет | **да** |
| VIN | да (если есть) | нет (на dongchedi публично нет) |
| equipment[] | да | пока нет |
| inspection report | нет | в JSON есть, парсинг отложен |

---

## Запуск с нуля

### 1. Установка

```powershell
cd C:\Users\Omen\Documents\trae_projects\china-car
python -m pip install requests
```

### 2. Credentials Oxylabs

В PowerShell перед запуском:
```powershell
$env:OXY_USER="ваш_user"
$env:OXY_PASS="ваш_password"
```

Эти переменные действуют только в текущей сессии PowerShell. Чтобы прописать постоянно — добавить через `[Environment]::SetEnvironmentVariable(...)`.

### 3. Полный pipeline для 1000 машин

```powershell
# Прогон 1: собираем ID. ~70 машин за один вызов, нужно ~15 запусков для 1000.
for ($i=1; $i -le 15; $i++) {
    python collect_ids.py --limit 1000 --scrolls 10
    Start-Sleep -Seconds 5
}

# Прогон 2: парсим карточки. Все ID из pending_ids которых ещё нет в cars.
python scrape_dongchedi.py --skip-listing --limit 1000 --workers 5
```

Время прогона: сбор IDs ~30 минут, парсинг 1000 карточек ~2 часа на workers=5.

Итоговая стоимость 1000 машин: ~$0.50 (IDs) + ~$2 (карточки) = **~$2.50**.

### 4. Просмотр результата

```powershell
python -c "import sqlite3; c=sqlite3.connect('cars.db'); rows=c.execute('SELECT mark, model, year, price_cny, km_age, city_cn FROM cars LIMIT 20').fetchall(); [print(r) for r in rows]"
```

Открыть `cars.db` в **DB Browser for SQLite** (https://sqlitebrowser.org/) для GUI-просмотра.

### 5. Экспорт в CSV / Excel

```powershell
python -c "import sqlite3, pandas as pd; c=sqlite3.connect('cars.db'); pd.read_sql('SELECT * FROM cars', c).to_csv('cars.csv', index=False, encoding='utf-8-sig')"
```

(если нужен pandas: `python -m pip install pandas`)

### 6. Daily refresh

Просто запустить тот же `scrape_dongchedi.py --skip-listing` повторно — это обновит `last_seen` у виденных машин. Новые объявления подберутся через повторный `collect_ids.py`.

SQL для отчётов:
```sql
-- Новые объявления за сутки
SELECT * FROM cars WHERE first_seen > datetime('now', '-1 day');

-- Возможно удалённые (не виделись 3+ дня)
SELECT * FROM cars WHERE last_seen < datetime('now', '-3 days');
```

---

## Ограничения

1. **VIN отсутствует.** Dongchedi не публикует VIN на сайте — это ограничение источника, а не парсера.

2. **scroll_to_bottom грузит ~70 машин за один прогон.** Oxylabs ограничивает время выполнения headless-job ~120 секундами. Чтобы получить много уникальных машин — нужно запускать `collect_ids.py` повторно (порядок выдачи у dongchedi не детерминированный, каждый раз приходят слегка разные машины).

3. **geo_location=China даёт пекинский IP.** Соответственно листинг возвращает машины из Beijing. Для других городов нужно либо вшить фильтр города в URL (требует дополнительного исследования позиций `x`), либо использовать `geo_location=Shanghai/Guangzhou/Shenzhen` (не проверено).

---

## Файлы проекта

```
C:\Users\Omen\Documents\trae_projects\china-car\
├── collect_ids.py           # Сбор sku_id
├── scrape_dongchedi.py      # Парсинг карточек
├── cars.db                  # SQLite база
└── README.md                # Эта документация
```
