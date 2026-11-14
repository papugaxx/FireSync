"""
db.py — THE PARTNER'S DATA, DIRECTLY

Most of the API works through the fast index (grid_index.py). This module
holds what must be read straight from the partner's database:
  * individual fire points — for the map and CSV;
  * the reference calendar via his grid_calendar() function — slow, but
    "as in the original", so that our fast calculation can be cross-checked.

We only read the partner's database and never modify it.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import config  # first: adds the data_pipeline folder with the partner's module
from fires_data import Store, grid_calendar
from fires_data.errors import StorageError
from fires_data.store import _bbox_filter, _bbox_values, _canonical_cte

# A "window" into the partner's database. It opens and closes connections itself.
store = Store(config.DB_PATH)

# Point fields we send to the frontend (the partner's internal fields are not needed)
POINT_FIELDS = ["observed_at", "day", "sensor", "satellite", "source_code",
                "latitude", "longitude", "frp_mw", "brightness_k",
                "confidence_raw", "daynight", "type_code"]


def database_info():
    """
    Whether the pipeline database file exists and how big it is (GB).

    Used by `/status`. The file path is deliberately not included, so it is never exposed to clients.
    """
    path = Path(config.DB_PATH)
    if not path.is_file():
        return {"found": False}
    return {"found": True, "size_gb": round(path.stat().st_size / 1024 ** 3, 2)}


# ---------- Points for the map ----------

def get_points(scope_id, start, end, bbox=None, sensor=None, limit=1000, offset=0):
    """Individual fire detections, in pages of `limit` items (the partner's function)."""
    rows = store.observations(scope_id, start, end, sensor=sensor,
                              limit=limit, offset=offset, bbox=bbox)
    return [{"id": row["record_hash"][:16], **{f: row.get(f) for f in POINT_FIELDS}} for row in rows]


# ---------- Points for CSV (streamed) ----------

def _connect():
    path = Path(config.DB_PATH).resolve()
    if not path.is_file():
        raise StorageError("Не найдена база напарника. Проверьте путь FIRMS_DB_PATH.")
    # check_same_thread=False: the CSV is sent in chunks, and the chunks are read from different threads
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _points_query(scope_id, start, end, bbox, sensor):
    # _canonical_cte — the partner's rule: "for each day take SP, otherwise NRT"
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
    """How many points will end up in the export (we count at most cap+1 to save time)."""
    cte, body, params = _points_query(scope_id, start, end, bbox, sensor)
    with closing(_connect()) as conn:
        return conn.execute(cte + f"SELECT COUNT(*) FROM (SELECT 1 {body} LIMIT ?)",
                            [*params, cap + 1]).fetchone()[0]


def stream_points(scope_id, start, end, bbox=None, sensor=None, cap=None):
    """Generator: yields points one by one without holding the whole export in memory."""
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


# ---------- The partner's reference calendar ----------

def reference_calendar(scope_id, start, end, bbox=None):
    """Slow but "original" calculation (for cross-checking against the fast index)."""
    return grid_calendar(store, scope_id, start, end, bbox=bbox)
