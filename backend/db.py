"""
db.py — ДАННЫЕ НАПАРНИКА НАПРЯМУЮ

Большая часть API работает через быстрый индекс (grid_index.py). Сюда
вынесено то, что нужно читать прямо из базы напарника:
  * отдельные точки пожаров — для карты и CSV;
  * эталонный календарь его функцией grid_calendar() — медленно, зато
    «как в оригинале», чтобы можно было сверить наш быстрый расчёт.

Базу напарника мы только читаем и никогда не меняем.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import config  # первым: подключает папку data_pipeline с модулем напарника
from fires_data import Store, grid_calendar
from fires_data.errors import StorageError
from fires_data.store import _bbox_filter, _bbox_values, _canonical_cte

# «Окно» в базу напарника. Соединения он открывает и закрывает сам.
store = Store(config.DB_PATH)

# Поля точки, которые отдаём фронту (служебные поля напарника не нужны)
POINT_FIELDS = ["observed_at", "day", "sensor", "satellite", "source_code",
                "latitude", "longitude", "frp_mw", "brightness_k",
                "confidence_raw", "daynight", "type_code"]


def database_info():
    path = Path(config.DB_PATH)
    if not path.is_file():
        return {"found": False}
    return {"found": True, "size_gb": round(path.stat().st_size / 1024 ** 3, 2)}


# ---------- Точки для карты ----------

def get_points(scope_id, start, end, bbox=None, sensor=None, limit=1000, offset=0):
    """Отдельные обнаружения пожаров, страницами по limit штук (функция напарника)."""
    rows = store.observations(scope_id, start, end, sensor=sensor,
                              limit=limit, offset=offset, bbox=bbox)
    return [{"id": row["record_hash"][:16], **{f: row.get(f) for f in POINT_FIELDS}} for row in rows]


# ---------- Точки для CSV (потоком) ----------

def _connect():
    path = Path(config.DB_PATH).resolve()
    if not path.is_file():
        raise StorageError("Не найдена база напарника. Проверьте путь FIRMS_DB_PATH.")
    # check_same_thread=False: CSV отдаётся кусками, и куски читаются из разных потоков
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _points_query(scope_id, start, end, bbox, sensor):
    # _canonical_cte — правило напарника «на каждый день SP, иначе NRT»
    cte, params = _canonical_cte(scope_id, start.isoformat(), end.isoformat())
    body = """
        FROM detections AS d JOIN canonical_windows AS w ON w.id = d.window_id
        WHERE 1 = 1"""
    if sensor:
        body += " AND d.sensor = ?"
        params.append(sensor)
    bbox_sql, bbox_params = _bbox_filter(_bbox_values(bbox))
    return cte, body + bbox_sql, params + bbox_params


def count_points(scope_id, start, end, bbox=None, sensor=None, cap=None):
    """Сколько точек попадёт в выгрузку (считаем максимум до cap+1, чтобы не тратить время)."""
    cte, body, params = _points_query(scope_id, start, end, bbox, sensor)
    with closing(_connect()) as conn:
        return conn.execute(cte + f"SELECT COUNT(*) FROM (SELECT 1 {body} LIMIT ?)",
                            [*params, cap + 1]).fetchone()[0]


def stream_points(scope_id, start, end, bbox=None, sensor=None, cap=None):
    """Генератор: отдаёт точки по одной, не держа всю выгрузку в памяти."""
    cte, body, params = _points_query(scope_id, start, end, bbox, sensor)
    columns = ", ".join(["d.observed_at", "w.day", "d.sensor", "d.satellite", "w.source_code",
                         "d.latitude", "d.longitude", "d.frp_mw", "d.brightness_k",
                         "d.confidence_raw", "d.daynight", "d.type_code"])
    conn = _connect()
    try:
        for row in conn.execute(cte + f"SELECT {columns} {body} ORDER BY d.observed_at LIMIT ?",
                                [*params, cap]):
            yield dict(row)
    finally:
        conn.close()


# ---------- Эталонный календарь напарника ----------

def reference_calendar(scope_id, start, end, bbox=None):
    """Медленный, но «оригинальный» расчёт (для сверки с быстрым индексом)."""
    return grid_calendar(store, scope_id, start, end, bbox=bbox)
