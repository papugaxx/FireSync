# FireSync — бэкенд (FastAPI)

API календаря пожарной активности по спутникам NASA **MODIS** (Terra + Aqua) и **VIIRS NOAA-20**.
В одной базе лежит весь архив 2000–2025 и всё, что потом приходит из NASA FIRMS API.
Фронтенд (`fire-calendar`) получает данные по адресам `/api/...` — ровно в том виде, который он ожидает.

**Главное в цифрах**

| | |
|---|---|
| Архив `NASA_FIRMS_2000_2025.csv` | 50 ГБ, 548 млн строк |
| В базе | **267 млн обнаружений**: MODIS 111,4 млн (2000-11-01 → 2025-12-31), NOAA-20 155,9 млн (2018-04-01 → 2025-12-31) |
| Размер базы | **≈ 3 ГБ** (около 11 байт на обнаружение) |
| Импорт архива | ≈ 10 минут, можно прерывать и продолжать |
| Новые данные NASA | скачиваются сами, в фоне, каждые 3 часа |
| Тесты | 44, без ключа, без сети и без настоящей базы |

---

## Быстрый старт (на своём компьютере)

```bash
cd ~/Desktop/FireSync/backend

python3 -m venv venv               # один раз
source venv/bin/activate           # в каждом новом окне терминала
pip install -r requirements.txt    # добавился numpy
pip install -e ./data_pipeline     # модуль напарника (клиент NASA, разбор CSV, калибровка)

python importer.py                 # один раз: data/raw/NASA_FIRMS_2000_2025.csv → data/firesync.sqlite3
python -m pytest                   # 44 passed

python -m uvicorn main:app --reload
```

Открыть **http://localhost:8000/docs** — все запросы с описаниями и кнопками «Try it out».

Чтобы сайт показывал настоящие данные, во фронтенде нужен файл `fire-calendar/.env.local`:

```text
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Потом `npm run dev` в папке `fire-calendar` и **http://localhost:3000/explore**.
Без этого файла сайт работает на своих демо-данных.

> База (`data/firesync.sqlite3`, ~3 ГБ) и CSV (`data/raw/`, 50 ГБ) в git не попадают.
> Коллегам быстрее скопировать готовую базу, чем заново импортировать CSV.

---

## Откуда берутся данные

```
data/raw/NASA_FIRMS_2000_2025.csv ──(importer.py, один раз)──┐
                                                              ▼
NASA FIRMS API ──(updater.py, в фоне каждые 3 часа)──► data/firesync.sqlite3
                                                              │
                        сайт ──► /api/... (frontend_api.py) ──┤  reports.py
                        другие ──► /calendar, /cells … (main.py) ┘
```

### 1. Архив — `importer.py` (один раз)

* Берёт строки MODIS (Terra/Aqua) и VIIRS NOAA-20. **VIIRS S-NPP (281 млн строк) пропускается**:
  ряд VIIRS в проекте — только NOAA-20, иначе VIIRS посчитался бы дважды.
* Все обнаружения одного дня и одного спутника хранятся одним сжатым блоком. Поэтому 50 ГБ CSV
  превращаются в 3 ГБ, а день читается за миллисекунды. Значения сохраняются **точно**
  (координаты до 5 знаков, FRP и яркость до 2 знаков — как у NASA).
* Если у дня есть и SP, и NRT — остаётся только SP (они никогда не складываются).
* Ctrl+C — безопасно: прогресс сохраняется вместе с данными, следующий запуск продолжит с того же места.
  `python importer.py --max-minutes 10` сам остановится примерно через 10 минут.
* Проверено на настоящем файле: за 2024-08-15 в CSV 106 758 строк NOAA-20 и 21 936 MODIS — в базе столько же.

### 2. Новые данные — `updater.py` (сам, в фоне)

Через минуту после запуска API и потом каждые 3 часа:

1. спрашивает у NASA, какие даты есть (SP — окончательные, NRT — оперативные);
2. скачивает **только то, чего нет** после конца архива: один запрос = один день одного спутника на весь мир,
   сначала последняя неделя (чтобы свежие пожары появились сразу), потом остальное по порядку;
3. пересчитывает таблицы регионов за изменившиеся месяцы — сайт сразу видит новые дни.

| Ситуация | Что делает |
|---|---|
| дня нет в базе | качает SP, если NASA его уже выпустила, иначе NRT |
| день есть как NRT, а NASA выпустила SP | перекачивает и заменяет на SP |
| NRT за последние 2 дня | перекачивает (NASA дописывает новые пролёты) |
| день есть как SP (весь архив) | **никогда не качает повторно** |
| весь мир за день пришёл пустым | не сохраняет: это сбой спутника, а не «пожаров не было» |
| лимит запросов / квота NASA / диск / размер базы | останавливается с понятной причиной, следующий запуск продолжит |

Ключ берётся из `data_pipeline/.env` (`FIRMS_MAP_KEY`) и **никуда не уходит**: не пишется в логи,
базу и ответы API. Догнать период после архива (с 2026-01-01 до сегодня) — около 640 запросов,
это займёт несколько запусков подряд (между ними 10 минут).

Вручную:
```bash
python updater.py --plan      # что будет скачано
python updater.py             # одно обновление сейчас
python updater.py --status    # что лежит в базе и как прошло последнее обновление
```
По HTTP то же самое: `GET /api/updates/` и `GET /status`.

---

## Что отдаёт API

### Для сайта (`frontend_api.py`) — ровно по `fire-calendar/types/api.ts`

| Адрес | Что отдаёт |
|---|---|
| `GET /api/meta/` | регионы (bbox в порядке фронтенда `[юг, запад, север, восток]`) и годы с данными |
| `GET /api/calendar/?region=` | календарь «год × месяц»: ячейко-дни в масштабе MODIS, медиана по месяцам, коэффициент гармонизации и R² |
| `GET /api/month/?region=&year=&month=` | дни месяца: активные клетки MODIS и NOAA-20 + гармонизированное значение |
| `GET /api/monthly/?region=&year=` | 12 месяцев: MODIS, VIIRS в масштабе MODIS, площадь занятых клеток, средняя и максимальная FRP |
| `GET /api/hotspots/?region=&year=&month=` | точки для карты: активная клетка 0,1° за день, кто её видел (MODIS / VIIRS / BOTH), FRP |
| `GET /api/export/?region=&year=&month=` | CSV с настоящими отдельными обнаружениями |
| `GET /api/updates/` | что в базе и что делает автообновление |

Регионы фронтенда (`world`, `ukraine`, `argentina`, `california`, `amazonas`) есть в `config.REGIONS`
с теми же прямоугольниками — календарь считает ровно то, что рисует карта.

### Общие (`main.py`)

| Адрес | Что отдаёт |
|---|---|
| `GET /status` | что в базе, за какие даты, состояние автообновления |
| `GET /regions` | готовые регионы |
| `GET /calendar` | **по дням**: активные клетки MODIS и VIIRS + уровень 0–4 |
| `GET /calendar/monthly` | **по месяцам**, с полнотой данных, площадью и FRP |
| `GET /cells` | слой карты GeoJSON (до 92 дней) |
| `GET /points` | отдельные обнаружения (до 7 дней), страницами |
| `GET /harmonization` | сведение MODIS и VIIRS в один ряд + проверка на отложенных днях |
| `GET /anomaly` | месяц против медианы **прошлых** лет (нужно минимум 3 полных года) |
| `GET /export.csv` | обнаружения файлом (до 31 дня) |
| `GET /health` | сервер жив? |

**Область**: `region=ukraine`, либо `west, south, east, north` (сначала долгота), либо ничего — весь мир.
Свой прямоугольник считается прямо по обнаружениям, поэтому период для него — до 366 дней.
**Период**: `date_from` и `date_to` (`ГГГГ-ММ-ДД`, UTC). Ошибки всегда `{"error": "понятный текст"}`.

### Единицы и правила

* **Активная клетка** — клетка 0,1° (~10 км), где за сутки UTC был хотя бы один очаг. Это не число пожаров
  и не площадь гари. За месяц — **ячейко-дни** (сумма по дням).
* `null` — **данных нет**; `0` — данные есть, пожаров нет. Неполный месяц — `null` (в `*_partial` видно, что есть).
* Площадь — площадь различных занятых клеток с учётом широты (у полюсов клетки меньше). Это не площадь гари.
* Средняя FRP — по обнаружениям, у которых FRP есть; пропуск FRP не считается нулём.
* Гармонизация: на первых 2/3 общих дней MODIS + NOAA-20 подбирается `k` (MODIS ≈ k × VIIRS), на последней трети
  проверяется. Пропуски MODIS заполняются `k × VIIRS` **только если** `k` выиграл у обоих эталонов на отложенных днях.

---

## Файлы

| Файл | За что отвечает |
|---|---|
| `main.py` | приложение, общие адреса, ошибки, CORS; запускает фоновое обновление |
| `frontend_api.py` | адреса `/api/...` для сайта |
| `store.py` | база: сжатые блоки по дням и таблицы регионов |
| `reports.py` | календарь, месяцы, клетки, точки — для региона или своего прямоугольника |
| `importer.py` | импорт архивного CSV |
| `updater.py` | автообновление из NASA FIRMS API |
| `analytics.py` | математика: раскраска, гармонизация, аномалии |
| `config.py` | настройки: пути, регионы, лимиты обновления |
| `data/` | `firesync.sqlite3` и `raw/NASA_FIRMS_2000_2025.csv` (не в git) |
| `tests/` | 44 теста на сгенерированном архиве в настоящем формате |
| `deploy/` | systemd, nginx, необязательный cron |
| `docs/` | документация MkDocs (`mkdocs serve -a 127.0.0.1:8001`) |

Старые `grid_index.py` и `db.py` больше не нужны (они читали базу напарника) и лежат в `_old/`.
База напарника `data_pipeline/var/fires.sqlite3` (3 ГБ) API больше не использует; её можно удалить, если
она не нужна для его собственных команд.

---

## Сервер (Ubuntu 24.04)

Нужно: 2 ГБ памяти, от 20 ГБ диска (база 3 ГБ + рост около 0,1 ГБ в месяц).

```bash
# 1. Пакеты, пользователь, код
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx git
sudo adduser --disabled-password --gecos "" firesync
sudo mkdir -p /srv/FireSync && sudo chown firesync /srv/FireSync
sudo -iu firesync
git clone <адрес репозитория> /srv/FireSync
cd /srv/FireSync/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && pip install -e ./data_pipeline
mkdir -p data
echo "FIRMS_MAP_KEY=ваш_ключ" > data_pipeline/.env
exit
```

```bash
# 2. База (3 ГБ) — копируем с Mac, а не импортируем 50 ГБ заново. НА MAC:
scp ~/Desktop/FireSync/backend/data/firesync.sqlite3 ЛОГИН@СЕРВЕР:/tmp/
shasum -a 256 ~/Desktop/FireSync/backend/data/firesync.sqlite3
# НА СЕРВЕРЕ: переложить и сверить сумму
sudo mv /tmp/firesync.sqlite3 /srv/FireSync/backend/data/ && sudo chown -R firesync /srv/FireSync/backend/data
sha256sum /srv/FireSync/backend/data/firesync.sqlite3
```

```bash
# 3. API как служба (сам качает новые данные NASA) и nginx. Сначала замените YOUR-... в deploy/
sudo cp /srv/FireSync/backend/deploy/firesync-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now firesync-api
sudo cp /srv/FireSync/backend/deploy/nginx.conf /etc/nginx/sites-available/firesync
sudo ln -s /etc/nginx/sites-available/firesync /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.YOUR-DOMAIN
curl https://api.YOUR-DOMAIN/status
```
