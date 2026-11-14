"""
config.py — НАСТРОЙКИ

Здесь только переменные. Любую можно переопределить переменной окружения,
не меняя код (так делают на сервере).
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Модуль напарника (fires_data) лежит рядом, в папке data_pipeline.
# Добавляем её в список мест, где Python ищет модули: тогда `import fires_data`
# работает при любом способе запуска — даже если его не ставили через pip.
_PIPELINE_DIR = str(BASE_DIR / "data_pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from fires_data import load_settings  # noqa: E402  (импорт после настройки пути)

# ---------- Базы данных ----------

# База напарника (точки пожаров из NASA). Путь берём ТАК ЖЕ, как его загрузчик:
#   1) переменная окружения FIRMS_DB_PATH,
#   2) иначе файл data_pipeline/.env,
#   3) иначе data_pipeline/var/fires.sqlite3.
# Поэтому API и загрузчик всегда смотрят в один и тот же файл.
DB_PATH = load_settings().db_path

# Наш быстрый индекс календаря (создаётся и обновляется сам, в git не попадает)
INDEX_PATH = Path(os.environ.get("FIRESYNC_INDEX_PATH", BASE_DIR / "cache" / "grid_index.sqlite3"))

# Как часто API проверяет, не появились ли новые данные (секунды). 0 — не проверять.
AUTO_REFRESH_SECONDS = int(os.environ.get("FIRESYNC_AUTO_REFRESH", "60"))

# Область данных напарника по умолчанию: весь мир
SCOPE_ID = "world"

# ---------- Фронтенд ----------

# Адреса сайта, которым можно обращаться к API (CORS). На сервере:
#   FRONTEND_URLS=https://firesync.example.com
FRONTEND_URLS = [u.strip() for u in os.environ.get("FRONTEND_URLS", "http://localhost:3000").split(",")
                 if u.strip()]

# ---------- Готовые регионы для демо ----------
# bbox = [запад, юг, восток, север] — сначала долгота, потом широта.
# scope — в какой области данных напарника искать. Если напарник загрузит
# историю отдельно для региона (--scope-id ukraine), поменяйте тут "world" на "ukraine".
REGIONS = {
    "world":          {"name": "Весь мир",                  "bbox": None,                      "scope": "world"},
    "ukraine":        {"name": "Украина (прямоугольник)",   "bbox": [22.0, 44.0, 41.0, 53.0],  "scope": "world"},
    "central_africa": {"name": "Центральная Африка",        "bbox": [12.0, -18.0, 35.0, 0.0],  "scope": "world"},
    "amazon":         {"name": "Амазония",                  "bbox": [-70.0, -15.0, -45.0, 0.0], "scope": "world"},
    "siberia":        {"name": "Сибирь и Якутия",           "bbox": [90.0, 50.0, 140.0, 70.0], "scope": "world"},
    "australia":      {"name": "Австралия",                 "bbox": [112.0, -44.0, 154.0, -10.0], "scope": "world"},
    "california":     {"name": "Калифорния",                "bbox": [-124.5, 32.5, -114.0, 42.0], "scope": "world"},
}

# ---------- Ограничения (защита сервера от слишком тяжёлых запросов) ----------
MAX_CALENDAR_DAYS = 3660      # календарь по дням: до 10 лет за запрос
MAX_REFERENCE_DAYS = 366      # эталонный расчёт напарника медленный: до 1 года
MAX_POINT_DAYS = 7            # отдельные точки для карты: до недели
MAX_POINTS_PER_PAGE = 5000
MAX_EXPORT_DAYS = 31          # CSV: до месяца
MAX_EXPORT_ROWS = 200_000
MAX_MAP_CELLS = 20_000        # клеток в ответе /cells
