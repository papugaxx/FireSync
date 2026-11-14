# FireSync — бэкенд (FastAPI)

API календаря пожарной активности по спутникам NASA **MODIS** и **VIIRS**.
Данные из NASA загружает модуль напарника (`data_pipeline/`), этот бэкенд
превращает их в календарь, карту, гармонизированный ряд MODIS ↔ VIIRS и CSV.

**Главное в цифрах** (настоящая база, август 2024):

| | расчёт напарника | наш API |
|---|---|---|
| Календарь всего мира за месяц | ~28 с | **0,25 с** |
| Календарь Украины за месяц | ~22 с | **0,12 с** |
| Совпадение цифр | эталон | **31 из 31 дня, до единицы** |
| Гармонизация MODIS ↔ VIIRS (Украина) | k = 0.3342, ошибка 223 → 34.5 | **то же самое** |
| Гармонизация по всему миру | — | **ошибка на проверочных днях −95,5 %** |
| Карта всего мира (9 096 клеток) | — | **91 КБ** со сжатием (без него 1,8 МБ) |

---

## Быстрый старт (на своём компьютере)

```bash
cd ~/Desktop/FireSync/backend

python3 --version                  # нужен Python 3.11 или новее
# если версия меньше: brew install python@3.12  — и дальше вместо python3 пишите python3.12

python3 -m venv venv               # отдельная «коробка» для библиотек проекта
source venv/bin/activate           # делать в каждом новом окне терминала
pip install -r requirements.txt
pip install -e ./data_pipeline     # модуль напарника как библиотека

python -m fires_data init          # один раз: подготовить базу напарника (данные не меняются)
python -m pytest                   # 26 тестов, должно быть 26 passed

python -m uvicorn main:app --reload   # запустить API (именно через python -m — см. ниже)
```

Открыть **http://localhost:8000/docs** — там все запросы с описаниями, их можно
пробовать кнопками «Try it out» → «Execute».

> Индекс календаря (`cache/grid_index.sqlite3`) уже построен. На другом компьютере
> он построится сам при первом запуске (около минуты) или командой `python grid_index.py`.

---

## Что умеет API

| Адрес | Что отдаёт |
|---|---|
| `GET /status` | что загружено, за какие даты, когда обновлялось |
| `GET /regions` | готовые регионы для демо (Украина, Африка, Амазония, Сибирь…) |
| `GET /calendar` | **по дням**: активные клетки MODIS и VIIRS + уровень 0–4 для раскраски |
| `GET /calendar/monthly` | **по месяцам** (для календаря «год × месяц»), с полнотой данных |
| `GET /cells` | **слой карты** GeoJSON: активные клетки, самые горячие первыми |
| `GET /points` | отдельные точки пожаров (до 7 дней), страницами |
| `GET /harmonization` | **сведение MODIS и VIIRS в один ряд** + честная проверка точности |
| `GET /anomaly` | месяц против медианы прошлых лет (заработает, когда загрузят историю) |
| `GET /export.csv` | скачать точки файлом (до 31 дня) |
| `GET /health` | сервер жив? |

**Область** во всех запросах: либо `region=ukraine`, либо четыре числа
`west, south, east, north` (сначала долгота, потом широта), либо ничего — весь мир.
**Период**: `date_from` и `date_to` в формате `ГГГГ-ММ-ДД` (UTC).

### Примеры для фронтенда

```
/calendar?date_from=2024-08-01&date_to=2024-08-31&region=ukraine
/calendar/monthly?date_from=2000-01-01&date_to=2026-12-31&region=ukraine
/cells?date_from=2024-08-01&date_to=2024-08-31
/harmonization?date_from=2024-08-01&date_to=2024-08-31&region=ukraine
/export.csv?date_from=2024-08-15&date_to=2024-08-15&west=30&south=46&east=36&north=50
```

Один день в ответе `/calendar`:
```json
{"date": "2024-08-01",
 "modis": {"status": "loaded", "observations": 207, "active_cells": 135, "level": 2},
 "viirs": {"status": "loaded", "observations": 861, "active_cells": 349, "level": 3},
 "shared_active_cells": 68}
```
* `active_cells` — сколько клеток 0.1° (~10 км) «горело» за сутки. **Это главное число для календаря.**
* `level` 0–4 — готовый уровень для цветовой шкалы (0 — пожаров нет, 4 — пик).
* `status: "missing"` и `null` — данные за день **не загружены** (это не «пожаров не было»).

Слой карты подключается к MapLibre одной строкой: `map.addSource('fires', {type: 'geojson', data: 'http://localhost:8000/cells?...'})`.

Ошибки всегда приходят так: `{"error": "понятный текст"}` с кодом 400/422/503.

---

## Как это устроено

```
NASA FIRMS ──(загрузчик напарника)──► data_pipeline/var/fires.sqlite3   (4,9 млн точек, 3 ГБ)
                                              │  только чтение
                                              ▼
                           grid_index.py: точки → клетки 0.1° по дням
                                              │
                                              ▼
                              cache/grid_index.sqlite3   (1 млн строк, 64 МБ)
                                              │
              браузер ──► main.py (FastAPI) ──┘   + db.py для точек и CSV
```

| Файл | За что отвечает |
|---|---|
| `main.py` | адреса API: принимает параметры, проверяет их, отдаёт JSON |
| `grid_index.py` | **быстрый индекс**: раскладывает точки по клеткам один раз, потом календарь считается мгновенно |
| `db.py` | то, что читается прямо из базы напарника: отдельные точки, CSV, эталонный расчёт |
| `analytics.py` | математика: раскраска, гармонизация, аномалии (без базы, легко тестировать) |
| `config.py` | настройки: пути, регионы, ограничения |
| `tests/` | 26 тестов на временной базе, собранной кодом напарника |
| `deploy/` | файлы для сервера: обновление по расписанию, systemd, nginx |

### Почему так быстро
Функция напарника `grid_calendar()` при каждом запросе перебирает миллионы точек.
Мы делаем эту работу **один раз**: для каждого дня и каждой клетки сетки храним,
сколько точек увидел MODIS и сколько VIIRS. Календарь — это сумма по маленькой таблице.

### Почему цифрам можно верить
* Правила те же, что у напарника: сетка 0.1°, MODIS = Terra + Aqua, VIIRS = NOAA-20,
  на каждый день берётся SP, а если его нет — NRT. Правило выбора SP/NRT мы не копируем,
  а вызываем из его кода.
* Результат сверен с эталонными файлами напарника (`data_pipeline/examples/`):
  весь мир и Украина за август 2024 совпали **до единицы**.
* Есть режим сверки прямо в API: `/calendar?...&engine=reference` считает оригинальной
  функцией напарника.
* Одно осознанное отличие: область считается целыми клетками сетки. Точка ровно
  на границе двух регионов попадает **в один** из них, а не в оба — двойного счёта нет.

### Как данные обновляются сами
Каждый загруженный день у напарника имеет контрольную сумму. API раз в минуту
проверяет «отпечаток» его базы и, если появились новые данные, пересчитывает
**только изменившиеся дни** (секунды, а не минуты). Перезапускать сервер не нужно.

### Гармонизация (суть челленджа)
VIIRS видит пожары лучше MODIS, поэтому их ряды нельзя сравнивать напрямую.
`/harmonization` на первых 2/3 дней подбирает коэффициент `k` (MODIS ≈ k × VIIRS),
а на последней трети **проверяет** его на днях, которые модель не видела.
В ответе `series` — единый ряд: где есть MODIS — MODIS, где только VIIRS — `k × VIIRS`,
у каждого значения подписан источник.

---

## Сервер (Ubuntu 24.04)

Нужно: 2 ГБ памяти, от 20 ГБ диска (база 3 ГБ + рост ~2 ГБ в месяц при обновлении всего мира).

```bash
# 1. Пакеты и пользователь
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx git
sudo adduser --disabled-password --gecos "" firesync
sudo mkdir -p /srv/FireSync && sudo chown firesync /srv/FireSync

# 2. Код (от пользователя firesync)
sudo -iu firesync
git clone <адрес вашего репозитория> /srv/FireSync
cd /srv/FireSync/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && pip install -e ./data_pipeline
mkdir -p cache data_pipeline/var
```

```bash
# 3. База (3 ГБ, в git её нет) — копируем с вашего Mac. Выполнять НА MAC:
scp ~/Desktop/FireSync/backend/data_pipeline/var/fires.sqlite3 ВАШ_ЛОГИН@СЕРВЕР:/tmp/
shasum -a 256 ~/Desktop/FireSync/backend/data_pipeline/var/fires.sqlite3

# НА СЕРВЕРЕ: переложить на место и сверить сумму — она должна совпасть с суммой на Mac
sudo mv /tmp/fires.sqlite3 /srv/FireSync/backend/data_pipeline/var/
sudo chown firesync /srv/FireSync/backend/data_pipeline/var/fires.sqlite3
sha256sum /srv/FireSync/backend/data_pipeline/var/fires.sqlite3
```

```bash
# 4. Ключ NASA и подготовка (на сервере, от firesync)
cd /srv/FireSync/backend
echo "FIRMS_MAP_KEY=ваш_ключ" > data_pipeline/.env      # ключ: https://firms.modaps.eosdis.nasa.gov/api/map_key/
python -m fires_data init
python grid_index.py                                     # построить индекс (около минуты)
chmod +x deploy/update.sh && crontab deploy/crontab.txt  # обновление каждые 3 часа
exit
```

```bash
# 5. API как служба и nginx (sudo). Сначала замените YOUR-... в файлах deploy/ на свои домены
sudo cp /srv/FireSync/backend/deploy/firesync-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now firesync-api
sudo cp /srv/FireSync/backend/deploy/nginx.conf /etc/nginx/sites-available/firesync
sudo ln -s /etc/nginx/sites-available/firesync /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.YOUR-DOMAIN

# 6. Проверка
curl https://api.YOUR-DOMAIN/health
curl https://api.YOUR-DOMAIN/status
```

Полезное: логи API — `journalctl -u firesync-api -f`, логи обновления —
`tail -f /srv/FireSync/backend/cache/update.log`, перезапуск — `sudo systemctl restart firesync-api`.

---

## Что дальше команде

1. **История.** Сейчас целиком загружен только август 2024. Для календаря «с 2000-х»
   напарнику стоит загрузить всю историю для 1–3 демо-регионов (весь мир за 20 лет —
   сотни гигабайт). Пример:
   `python -m fires_data plan --bbox 22 44 41 53 --scope-id ukraine --all-history --sources MODIS_SP VIIRS_NOAA20_SP`
   Потом в `config.py` у региона поменять `"scope": "world"` на `"scope": "ukraine"`.
   Индекс подхватит новую область сам.
2. **Аномалии** (`/anomaly`) заработают автоматически, когда для месяца будет хотя бы 3 года полных данных.

## Частые проблемы

| Сообщение | Что делать |
|---|---|
| `requires a different Python` при `pip install -e` | нужен Python 3.11+: `brew install python@3.12` |
| `Индекс ещё строится` | подождать минуту или выполнить `python grid_index.py` |
| `База данных недоступна` | нет файла `data_pipeline/var/fires.sqlite3` (или задайте путь в `FIRMS_DB_PATH`) |
| В браузере ошибка CORS | добавить адрес фронта в `FRONTEND_URLS` (в `config.py` или переменной окружения) |
| `Address already in use` | API уже запущен в другом окне, или запустите на другом порту: `--port 8001` |
| `No module named 'fires_data'` / `fastapi` | терминал взял чужой `uvicorn`, а не из `venv`. Запускайте `python -m uvicorn main:app --reload`; проверить: `which python` должен показывать `.../backend/venv/bin/python` |

Старые версии ваших файлов сохранены в папке `_old/` (в git она не попадает).
