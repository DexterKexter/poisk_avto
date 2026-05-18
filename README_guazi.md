# guazi.com — 瓜子二手车 парсер

Крупнейший C2C-маркетплейс б/у-машин Китая (Chehaoduo Group). #1 по рейтингу 2025. Главная фишка — **детальный inspection scorecard на каждой машине** (счётчик дефектов по 5 секциям: кузов, рама, салон, мотор, EV-компоненты) + insurance claim count.

## Доступ

- **Прямой HTTP**, $0 — без Oxylabs / playwright
- UTF-8 (проще че168 GB2312)
- Без анти-бота для просмотра; нужны только корректные `User-Agent` + `Accept-Language` + `Referer`

## Файлы

- `collect_guazi.py` — собирает листинги по 6 городам (по 40 карточек на стр)
- `scrape_guazi.py` — детали, parallel (`--workers 8` по умолчанию)
- `.github/workflows/scrape-guazi.yml` — daily 20:30 UTC

## Фильтры (можно переопределить через workflow_dispatch)

| Параметр | Значение по умолчанию |
|---|---|
| Города | Beijing, Shanghai, Guangzhou, Shenzhen, Chengdu, Hangzhou |
| Год регистрации | ≥ 2020 |
| Пробег | ≤ 100,000 km |
| Цена | ≥ ¥5,000 |
| Pages per city | 20 |
| Sold filter | `excludeSold=1` |

## Что вытаскиваем — все поля на одну машину

### Из listing-карточки

| Поле | В нашу базу | Извлечение |
|---|---|---|
| URL deail | `url` | `/car-detail/c{long_id}.html` |
| `clue_id` | `source_id` | 15-значный ID |
| Title (alt-attribute) | `title` | "哪吒汽车 哪吒N01 2020款 380t..." |
| Thumb URL | `thumb_url` | image-public.guazistatic.com |
| Год регистрации | `year` | "2019年" |
| Пробег | `km_age` | "3.37万公里" |
| Город (отображения) | `city` | "北京" |
| **Tags** ✓ | `metadata.tags` | `已检测`, `纯电动` etc |
| Цена (×万元) | `price_original` | "2.72" → 27200 CNY |

### Из detail-страницы (escape JSON inline)

Pairs приходят в формате `\"label\":\"X\",\"value\":\"Y\"`:

| Поле | В нашу базу | Что |
|---|---|---|
| 首次上牌 | `reg_date`, `year` | дата первой регистрации |
| 表显里程 | `km_age` | пробег |
| **过户次数** | `source_data.transfers` | количество переоформлений |
| **车源地** | `source_data.source_city` | город, ОТКУДА продаётся (C2C — может отличаться от displayed city!) |
| 发动机 | `source_data.displacement` | объём (для EV "0.0L") |
| 变速箱 | `transmission_original`, `transmission` | трансмиссия |
| **排放标准** | `source_data.emission` | "新能源" для EV, "国V" / "国VI" для ICE |
| 驱动方式 | `drive_type`, `drive_type_original` | привод |
| **车身颜色** | `color`, `color_original` | цвет |
| **能源类型** | `engine_type`, `fuel_original` | "纯电动", "汽油" и т.д. |

### Inspection scorecard (это самое ценное!)

Все поля в `source_data.inspection`:

| Поле | Что |
|---|---|
| `grade` | **Общая оценка**: 一般 (average) / 良好 (good) / 优秀 (excellent) |
| `ev_components` | "1项注意" — кол-во проблем с электрикой (EV) |
| `body_exterior` | "2项注意" — кузов снаружи |
| `interior` | "4项注意" — салон |
| **`frame`** | "5项注意" — **рама** (критично!) |
| `engine_bay` | "0项注意" — моторный отсек |
| `insurance_claims` | "1次理赔" — **количество страховых случаев** |
| `guarantee` | "每车必检" — гарантия проверки |

### Battery details (для EV) — `source_data.battery`

| Поле | Что |
|---|---|
| `capacity_kwh` | "35kWh" |
| `type` | "三元锂" (Ternary Lithium) / "磷酸铁锂" (LFP) |
| `new_range_km` | "301km" |
| `fast_charge` | "支持" / "不支持" |
| `fast_charge_time` | "0.5h" |
| `drive_motor` | "前置前驱" расположение |

### VIN

**guazi не показывает VIN на странице** — он скрыт до контакта с дилером. `vin: NULL` в нашей базе.

### Фото HD

Шаблон: `https://image-public.guazistatic.com/...{HASH}.jpg`

| Query string | Размер | Вес |
|---|---|---|
| `?...w_330,h_220` (default thumb) | 330×220 | 41KB |
| `?...w_1920,h_1280` (наш HD) | **1920×1280** | 633KB |
| `?x-bce-process=image/quality,q_95` (без resize) | 1376×1032 (оригинал) | 245KB |

В коде: добавляем `?x-bce-process=image/quality,q_95/resize,m_fill,w_1920,h_1280`

## Запуск

```bash
# GitHub Actions
gh workflow run scrape-guazi.yml -f scrape_limit=5000 -f workers=8

# Локально
python collect_guazi.py
python scrape_guazi.py --limit 1000 --workers 8
```

## Особенности guazi

- **C2C-модель** — машины в одном городе могут быть из другого. `metadata.city` = displayed city, `source_data.source_city` = реальный город владельца. Доставку организует guazi.
- 40 карточек на 1 листинг-странице (плюсуем 6 городов × 20 страниц = ~4800 уникальных машин за прогон)
- Inline data — escaped JSON прямо в HTML, не Next.js `__NEXT_DATA__`
- VIN скрыт публично; для VIN-отчётов лучше использовать che168
