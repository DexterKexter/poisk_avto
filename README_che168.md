# che168.com — 二手车之家 парсер

Самая старая и крупная дилерская площадка б/у-машин Китая (Autohome group, с 2005). Главная ценность для нас — **нативный VIN, дата регистрации, история ремонтов/ДТП, HD-фото оригинального размера**.

## Доступ

- **Прямой HTTP**, $0 — без Oxylabs
- Кодировка страницы: **GB2312**, надо явно декодировать
- Анти-бот: первый запрос без сессии получает JS-challenge (987 байт со скриптом, ставящим cookie `__tst_status` + `EO_Bot_Ssid`). Поэтому используем **playwright** — он выполняет JS автоматически.

## Файлы

- `collect_che168.py` — собирает листинги по 6 городам, фильтрует, апсёртит в `pending_ids`
- `scrape_che168.py` — детали по pending IDs, апсёртит в `cars`
- `.github/workflows/scrape-che168.yml` — daily 19:30 UTC

## Фильтры (можно переопределить через workflow_dispatch)

| Параметр | Значение по умолчанию |
|---|---|
| Города | Beijing, Shanghai, Guangzhou, Shenzhen, Chengdu, Hangzhou |
| Год регистрации | ≥ 2020 |
| Пробег | ≤ 100,000 km |
| Цена | ≥ ¥5,000 |
| Pages per city | 30 |

## Что вытаскиваем — все поля на одну машину

### Из listing-карточки (HTML-атрибуты `<li class="cards-li">`)

| Атрибут | В нашу базу | Что |
|---|---|---|
| `infoid` | `source_id` | уникальный ID объявления |
| `brandid` | `source_data.brand_id_che168` | внутренний ID бренда |
| `seriesid` | `source_data.series_id_che168` | внутренний ID модели |
| `specid` | `source_data.spec_id_che168` | внутренний ID комплектации |
| `dealerid` | `source_data.dealer_id` | ID дилера |
| `carname` | `title` | полное название (CN) |
| `price` (×万元) | `price_original` | цена в CNY |
| `milage` (×万公里) | `km_age` | пробег в км |
| `regdate` (YYYY/MM) | `year`, `reg_date` | год+месяц регистрации |
| `publicdate` (ISO) | `published_at` | когда объявление опубликовано |
| `cid` | `city` | id города |
| `cartype` | — | категория кузова |

### Из detail-страницы

| Поле | В нашу базу | Извлечение |
|---|---|---|
| Заголовок | `title` | `<title>` |
| Цена | `price_original` | `26.80万` |
| Город | `city`, `city_original` | по cid |
| Пробег | `km_age` | `表显里程 6.8万公里` |
| Дата регистрации | `year`, `reg_date` | `上牌时间 2022年03月` |
| **Переоформлений** | `source_data.transfers` | `过户次数 0次` |
| Цвет | `color`, `color_original` | `车身颜色 黑色` |
| Привод | `drive_type`, `drive_type_original` | `驱动方式 前置后驱` |
| Трансмиссия | `transmission`, `transmission_original` | `变速箱 自动` |
| Топливо | `engine_type`, `fuel_original` | `燃料类型 汽油` |
| Объём | `source_data.displacement` | `排量 2.0T` |
| Эмиссия | `source_data.emission` | `排放标准 国VI` |
| Адрес дилера | `source_data.dealer_address` | `地址：北京市丰台区...` |
| **VIN** ✓ | `vin` | 17-символьная строка на странице |
| **Battery score** (EV) | `source_data.battery_score` | `电池评分 99分` |
| **Battery health %** (EV) | `source_data.battery_health` | `电池容量保持率 96.17%` |
| Battery capacity | `source_data.battery_capacity` | `电池容量 35kWh` |
| EV range | `source_data.ev_range_km` | `新车续航 301km` |
| **Trust badges** (счётчики вхождений) | `source_data.trust_badges` | `认证二手车`, `无重大事故`, `30天整车保修` и т.д. |
| **Фото HD** | `images` | до 1024×768 webp (можно поднять до 1941×1200 в коде) |

### Trust badges, которые ищем

`认证二手车 / 精选好车 / 无重大事故 / 事故车 / 泡水车 / 30天整车保修 / 7天无理由 / 15天包退 / 30天包退 / 180天质保 / 1年质保 / 原版漆 / 一手车 / 原厂质保 / 111项 / 里程核实 / VIN核实`

### Endpoints для отчётов (не парсятся, ссылка в логах)

- Maintenance & пробег: `/maintenance/vincodesearch.html?vincode={encrypted}` — ~25¥/$3.5 за отчёт
- Insurance claims (ДТП): `/insurance/index.aspx?infoid={id}&vincode={encrypted}` — встроенная справка

## URL-шаблон фото и upscale

Шаблон: `https://car2.autoimg.cn/escimg/.../720x540_0_q87_c42_HASH.jpg`

Размеры (выбираем `1024x768` по умолчанию, баланс качество/вес):
| Размер | Реальные пиксели | Вес |
|---|---|---|
| 720x540 (default) | 720×540 | 54KB |
| 1100x825 | 1100×825 | 100KB |
| 1600x1200 | 1600×1200 | 161KB |
| **0_0 (оригинал)** | **1941×1200** | 533KB |

В коде: `re.sub(r"/\d+x\d+_0_q\d+_", "/1024x768_0_q87_", url)`

## Запуск

```bash
# Через workflow_dispatch на GitHub Actions
gh workflow run scrape-che168.yml -f min_year=2020 -f max_mileage_km=100000

# Локально
SUPABASE_URL=... SUPABASE_KEY=... python collect_che168.py
SUPABASE_URL=... SUPABASE_KEY=... python scrape_che168.py --limit 1000
```

## Известные ограничения

- Detail-страница требует прохождение JS-anti-bot (playwright обходит автоматически)
- Заголовок страницы содержит закодированную цену (формат `_26.8000_`) — backup для парсинга price
- complectation остаётся в китайском (типа "尊享型 M运动套装") — нужен либо LLM-перевод, либо отдельный мап trim-суффиксов
