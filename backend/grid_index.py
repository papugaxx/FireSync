"""
grid_index.py — БЫСТРЫЙ ИНДЕКС КАЛЕНДАРЯ

Зачем он нужен
--------------
Функция напарника grid_calendar() каждый раз перебирает миллионы исходных
точек: весь мир за месяц считается ~25 секунд. Для сайта это слишком долго.

Мы делаем то же самое ОДИН раз и сохраняем результат в маленькую базу
cache/grid_index.sqlite3: для каждого дня и каждой клетки сетки 0.1°
храним, сколько точек увидел MODIS и сколько VIIRS. После этого календарь
для любой области и любого периода считается за доли секунды.

Правила те же, что у напарника (data_pipeline/GRID_METHOD.md):
  * сетка 0.1°, начало в (-180, -90), координаты округляются до 0.0000001°;
  * MODIS = Terra + Aqua (клетки объединяются), VIIRS = только NOAA-20;
  * на каждый день берётся один срез: SP, если загружен, иначе NRT
    (это правило мы не копируем, а берём прямо из кода напарника).
Отличие одно: область считается целыми клетками — прямоугольник
расширяется до ближайших линий сетки 0.1°. В ответе API это видно в поле bbox.

Как индекс узнаёт о новых данных
--------------------------------
У каждого загруженного среза (день + спутник) в базе напарника есть
контрольная сумма. Индекс запоминает суммы, из которых он построен, и при
обновлении пересчитывает только изменившиеся дни. Поэтому обновление после
новой загрузки из NASA занимает секунды.

Запуск вручную:  python grid_index.py
"""

import math
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config  # первым: подключает папку data_pipeline с модулем напарника
from fires_data.errors import StorageError
from fires_data.store import _canonical_cte  # правило «SP, иначе NRT» — из кода напарника

try:  # блокировка файла, чтобы два обновления не шли одновременно (Linux, macOS)
    import fcntl
except ImportError:  # Windows: просто без межпроцессной блокировки
    fcntl = None


INDEX_VERSION = "1"

# Какие источники и спутники входят в каждый ряд (как в analytics.py напарника)
CHANNELS = {
    "modis": {"sources": ("MODIS_SP", "MODIS_NRT"), "satellites": ("Terra", "Aqua")},
    "viirs": {"sources": ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"), "satellites": ("NOAA-20",)},
}
SOURCE_TO_CHANNEL = {src: ch for ch, info in CHANNELS.items() for src in info["sources"]}

# Номер клетки по координате — ровно та же формула, что в analytics.py напарника
CELL_SQL = """
    SELECT MIN(1799, (CAST(ROUND(latitude * 10000000.0) AS INTEGER) + 900000000) / 1000000) AS cell_y,
           MIN(3599, (CAST(ROUND(longitude * 10000000.0) AS INTEGER) + 1800000000) / 1000000) AS cell_x,
           COUNT(*) AS n
    FROM detections
    WHERE window_id = ? AND satellite IN ({placeholders})
    GROUP BY cell_y, cell_x
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
-- Области (scope) из базы напарника, чтобы API не ходил туда за ними
CREATE TABLE IF NOT EXISTS scopes (
    id TEXT PRIMARY KEY, name TEXT,
    west REAL, south REAL, east REAL, north REAL
);
-- Из каких срезов построен индекс (по ним видно, что изменилось)
CREATE TABLE IF NOT EXISTS windows (
    scope_id     TEXT NOT NULL,
    channel      TEXT NOT NULL,      -- 'modis' или 'viirs'
    day          TEXT NOT NULL,      -- 'YYYY-MM-DD', UTC
    window_id    INTEGER NOT NULL,   -- id среза в базе напарника
    source_code  TEXT NOT NULL,      -- например MODIS_SP
    checksum     TEXT NOT NULL,
    fetched_at   TEXT,
    observations INTEGER NOT NULL,
    PRIMARY KEY (scope_id, channel, day)
) WITHOUT ROWID;
-- Главная таблица: сколько точек было в клетке за день
CREATE TABLE IF NOT EXISTS cells (
    scope_id TEXT NOT NULL,
    day      TEXT NOT NULL,
    cell_y   INTEGER NOT NULL,       -- 0..1799, строка сетки (широта)
    cell_x   INTEGER NOT NULL,       -- 0..3599, столбец сетки (долгота)
    modis    INTEGER NOT NULL DEFAULT 0,
    viirs    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope_id, day, cell_y, cell_x)
) WITHOUT ROWID;
-- Второй порядок хранения: быстро для маленькой области за много лет
CREATE INDEX IF NOT EXISTS cells_by_place ON cells (scope_id, cell_y, cell_x, day);
"""


class IndexNotReady(Exception):
    """Индекс ещё не построен (первый запуск) — нужно подождать."""


# ---------------------------------------------------------------------------
# Подключения
# ---------------------------------------------------------------------------

def _index_path():
    return Path(config.INDEX_PATH)


NOT_READY = "Индекс ещё строится (первый запуск занимает около минуты). Повторите запрос чуть позже."


def _connect_index(create=False):
    path = _index_path()
    if not create and not path.is_file():
        raise IndexNotReady(NOT_READY)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if create:
        conn.execute("PRAGMA journal_mode = WAL")  # читать можно, пока идёт запись
        conn.execute("PRAGMA synchronous = NORMAL")
    elif _get_meta_safe(conn, "last_refresh") is None:
        # Первое построение ещё не закончено — неполные цифры не отдаём
        conn.close()
        raise IndexNotReady(NOT_READY)
    return conn


def _connect_partner():
    """База напарника — только чтение, мы её никогда не меняем."""
    path = Path(config.DB_PATH).resolve()
    if not path.is_file():
        raise StorageError("Не найдена база напарника. Проверьте путь FIRMS_DB_PATH.")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _set_meta(conn, **values):
    conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                     [(k, str(v)) for k, v in values.items()])


def _ensure_schema(conn):
    if _get_meta_safe(conn, "index_version") not in (None, INDEX_VERSION):
        # Формат индекса поменялся — строим заново (данные напарника не трогаем)
        conn.executescript("DROP TABLE IF EXISTS cells; DROP TABLE IF EXISTS windows; "
                           "DROP TABLE IF EXISTS scopes; DROP TABLE IF EXISTS meta;")
    conn.executescript(SCHEMA)
    with conn:
        _set_meta(conn, index_version=INDEX_VERSION)


def _get_meta_safe(conn, key):
    try:
        return _get_meta(conn, key)
    except sqlite3.OperationalError:  # таблицы meta ещё нет
        return None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Построение и обновление индекса
# ---------------------------------------------------------------------------

def partner_signature(src=None):
    """Короткий «отпечаток» базы напарника: меняется после каждой загрузки."""
    own = src is None
    src = src or _connect_partner()
    try:
        row = src.execute("""SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(MAX(fetched_at), '')
                             FROM fetch_windows WHERE status = 'loaded'""").fetchone()
        scopes = src.execute("SELECT COUNT(*) FROM scopes").fetchone()[0]
        return f"{row[0]}|{row[1]}|{row[2]}|{scopes}"
    finally:
        if own:
            src.close()


def _canonical_windows(src, scope_id):
    """Какой срез действует для каждого дня и ряда (SP, если есть, иначе NRT)."""
    cte, params = _canonical_cte(scope_id)
    sources = tuple(SOURCE_TO_CHANNEL)
    sql = cte + f"""
        SELECT w.id, w.source_code, w.day, fw.checksum, fw.fetched_at
        FROM canonical_windows AS w JOIN fetch_windows AS fw ON fw.id = w.id
        WHERE w.source_code IN ({",".join("?" * len(sources))})"""
    return {(SOURCE_TO_CHANNEL[r["source_code"]], r["day"]): dict(r)
            for r in src.execute(sql, [*params, *sources])}


def _rebuild_window(idx, src, scope_id, channel, day, window):
    """Пересчитать один день одного ряда: точки → клетки."""
    satellites = CHANNELS[channel]["satellites"]
    rows = src.execute(CELL_SQL.format(placeholders=",".join("?" * len(satellites))),
                       (window["id"], *satellites)).fetchall()
    with idx:  # одна транзакция: или всё, или ничего
        idx.execute(f"UPDATE cells SET {channel} = 0 WHERE scope_id = ? AND day = ?", (scope_id, day))
        idx.executemany(
            f"""INSERT INTO cells (scope_id, day, cell_y, cell_x, {channel}) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (scope_id, day, cell_y, cell_x) DO UPDATE SET {channel} = excluded.{channel}""",
            [(scope_id, day, r["cell_y"], r["cell_x"], r["n"]) for r in rows])
        idx.execute("DELETE FROM cells WHERE scope_id = ? AND day = ? AND modis = 0 AND viirs = 0",
                    (scope_id, day))
        idx.execute("""INSERT OR REPLACE INTO windows
                       (scope_id, channel, day, window_id, source_code, checksum, fetched_at, observations)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (scope_id, channel, day, window["id"], window["source_code"],
                     window["checksum"], window["fetched_at"], sum(r["n"] for r in rows)))


def _remove_window(idx, scope_id, channel, day):
    with idx:
        idx.execute(f"UPDATE cells SET {channel} = 0 WHERE scope_id = ? AND day = ?", (scope_id, day))
        idx.execute("DELETE FROM cells WHERE scope_id = ? AND day = ? AND modis = 0 AND viirs = 0",
                    (scope_id, day))
        idx.execute("DELETE FROM windows WHERE scope_id = ? AND channel = ? AND day = ?",
                    (scope_id, channel, day))


_thread_lock = threading.Lock()


def _acquire_lock():
    """Только одно обновление за раз — даже если запущено несколько процессов.
    Возвращает «ключ» или None, если обновление уже кто-то выполняет."""
    if not _thread_lock.acquire(blocking=False):
        return None
    handle = None
    if fcntl is not None:
        path = _index_path().with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            _thread_lock.release()
            return None
    return handle or True


def _release_lock(handle):
    if hasattr(handle, "close"):
        handle.close()  # закрытие файла снимает flock
    _thread_lock.release()


def refresh(progress=None):
    """
    Привести индекс в соответствие с базой напарника.
    Пересчитываются только новые и изменившиеся дни.
    """
    lock = _acquire_lock()
    if lock is None:
        return {"status": "busy", "message": "Обновление уже идёт в другом процессе."}
    started = time.monotonic()
    try:
        with closing(_connect_partner()) as src, closing(_connect_index(create=True)) as idx:
            _ensure_schema(idx)
            signature = partner_signature(src)
            scopes = [dict(r) for r in src.execute(
                "SELECT id, name, west, south, east, north FROM scopes ORDER BY id")]
            with idx:
                idx.execute("DELETE FROM scopes")
                idx.executemany("INSERT INTO scopes VALUES (:id, :name, :west, :south, :east, :north)", scopes)
                # области, которых больше нет у напарника
                idx.execute("DELETE FROM windows WHERE scope_id NOT IN (SELECT id FROM scopes)")
                idx.execute("DELETE FROM cells WHERE scope_id NOT IN (SELECT id FROM scopes)")

            rebuilt = removed = 0
            for scope in scopes:
                current = _canonical_windows(src, scope["id"])
                ours = {(r["channel"], r["day"]): (r["window_id"], r["checksum"])
                        for r in idx.execute("SELECT channel, day, window_id, checksum FROM windows "
                                             "WHERE scope_id = ?", (scope["id"],))}
                for channel, day in sorted(set(ours) - set(current)):
                    _remove_window(idx, scope["id"], channel, day)
                    removed += 1
                todo = sorted(key for key, w in current.items() if ours.get(key) != (w["id"], w["checksum"]))
                for number, (channel, day) in enumerate(todo, 1):
                    _rebuild_window(idx, src, scope["id"], channel, day, current[(channel, day)])
                    rebuilt += 1
                    if progress:
                        progress(f"[{scope['id']}] {number}/{len(todo)}  {day}  {channel}")

            if rebuilt or removed:
                idx.execute("ANALYZE")  # подсказка SQLite, какой порядок хранения быстрее
            with idx:
                _set_meta(idx, signature=signature, last_refresh=_now())
            return {"status": "ok", "rebuilt_days": rebuilt, "removed_days": removed,
                    "seconds": round(time.monotonic() - started, 1)}
    finally:
        _release_lock(lock)


def needs_refresh():
    """Изменилась ли база напарника с последнего обновления индекса."""
    if not _index_path().is_file():
        return True
    with closing(sqlite3.connect(_index_path(), timeout=30)) as idx:
        stored = _get_meta_safe(idx, "signature")
    return stored != partner_signature()


def is_ready():
    try:
        with closing(_connect_index()):
            return True
    except IndexNotReady:
        return False


_auto = {"started": False, "last_error": None, "last_result": None}


def start_auto_refresh(interval_seconds):
    """
    Фоновый поток внутри API: раз в interval секунд проверяет, не появились ли
    новые данные у напарника, и если появились — обновляет индекс.
    Так сайт сам подхватывает свежие загрузки из NASA, перезапуск не нужен.
    """
    if interval_seconds <= 0 or _auto["started"]:
        return
    _auto["started"] = True

    def loop():
        while True:
            try:
                if needs_refresh():
                    _auto["last_result"] = refresh()
                _auto["last_error"] = None
            except Exception as exc:  # поток не должен умирать из-за одной ошибки
                _auto["last_error"] = str(exc)
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="grid-index-refresh", daemon=True).start()


# ---------------------------------------------------------------------------
# Геометрия сетки
# ---------------------------------------------------------------------------

def _ticks(value):
    """Координата → целое число шагов по 0.0000001° (округление «от нуля», как в SQLite)."""
    return int(math.copysign(math.floor(abs(value) * 10_000_000 + 0.5), value))


def cell_range(bbox):
    """
    Прямоугольник (west, south, east, north) → номера клеток, которые он задевает.
    Возвращает (y_from, y_to, x_from, x_to) включительно.
    """
    west, south, east, north = bbox
    x_from = (_ticks(west) + 1_800_000_000) // 1_000_000
    x_to = -(-(_ticks(east) + 1_800_000_000) // 1_000_000) - 1   # «потолок» минус 1
    y_from = (_ticks(south) + 900_000_000) // 1_000_000
    y_to = -(-(_ticks(north) + 900_000_000) // 1_000_000) - 1
    clamp = lambda v, hi: max(0, min(hi, v))
    return clamp(y_from, 1799), clamp(max(y_to, y_from), 1799), clamp(x_from, 3599), clamp(max(x_to, x_from), 3599)


def cells_to_bbox(cells):
    """Номера клеток → прямоугольник по линиям сетки (то, что реально посчитано)."""
    y_from, y_to, x_from, x_to = cells
    return [round(x_from / 10 - 180, 1), round(y_from / 10 - 90, 1),
            round((x_to + 1) / 10 - 180, 1), round((y_to + 1) / 10 - 90, 1)]


# ---------------------------------------------------------------------------
# Чтение (используется в API)
# ---------------------------------------------------------------------------

def get_scope(scope_id):
    with closing(_connect_index()) as idx:
        row = idx.execute("SELECT * FROM scopes WHERE id = ?", (scope_id,)).fetchone()
    if row is None:
        raise ValueError(f"Область данных '{scope_id}' не загружена.")
    return dict(row)


def resolve_area(scope_id, bbox=None):
    """
    Проверить область и перевести её в клетки.
    bbox=None — вся область данных (для 'world' — весь мир).
    """
    scope = get_scope(scope_id)
    bounds = (scope["west"], scope["south"], scope["east"], scope["north"])
    if bbox is None:
        return {"scope_id": scope_id, "cells": None, "bbox": list(bounds), "requested_bbox": None}
    west, south, east, north = bbox
    if not (bounds[0] <= west < east <= bounds[2] and bounds[1] <= south < north <= bounds[3]):
        raise ValueError("Область должна лежать внутри загруженной области данных "
                         f"{list(bounds)} и иметь west < east, south < north.")
    cells = cell_range(bbox)
    snapped = cells_to_bbox(cells)
    snapped = [max(snapped[0], bounds[0]), max(snapped[1], bounds[1]),
               min(snapped[2], bounds[2]), min(snapped[3], bounds[3])]
    return {"scope_id": scope_id, "cells": cells, "bbox": snapped, "requested_bbox": list(bbox)}


def _where(area, start, end):
    sql = "scope_id = ? AND day BETWEEN ? AND ?"
    params = [area["scope_id"], start.isoformat(), end.isoformat()]
    if area["cells"] is not None:
        y_from, y_to, x_from, x_to = area["cells"]
        sql += " AND cell_y BETWEEN ? AND ? AND cell_x BETWEEN ? AND ?"
        params += [y_from, y_to, x_from, x_to]
    return sql, params


def _loaded_days(idx, scope_id, start, end):
    loaded = {"modis": set(), "viirs": set()}
    windows = []
    for r in idx.execute("""SELECT channel, day, source_code, checksum, fetched_at, observations
                            FROM windows WHERE scope_id = ? AND day BETWEEN ? AND ?
                            ORDER BY day, source_code""", (scope_id, start.isoformat(), end.isoformat())):
        loaded[r["channel"]].add(r["day"])
        windows.append({"day": r["day"], "source_code": r["source_code"], "checksum": r["checksum"],
                        "fetched_at": r["fetched_at"], "row_count": r["observations"]})
    return loaded, windows


METHOD = {
    # Те же поля, что в отчёте напарника: по ним его calibrate_calendar() проверяет совместимость
    "id": "common-grid-0p1deg-v1",
    "engine": "firesync-cell-index-v1",
    "harmonized": False,
    "harmonization_status": "not_calibrated",
    "r2": None,
    "grid_degrees": 0.1,
    "grid_crs": "EPSG:4326",
    "time_basis": "UTC",
    "origin": {"longitude": -180, "latitude": -90},
    "coordinate_quantization_degrees": 1e-7,
    "coordinate_rounding": "nearest integer tick; halfway away from zero",
    "daily_unit": "active_cells_per_UTC_day",
    "total_unit": "active_cell_days",
    "modis_platforms": ["Terra", "Aqua"],
    "modis_combination": "union of occupied cells per UTC day",
    "viirs_platforms": ["NOAA-20"],
    "processing_preference": "loaded SP, otherwise loaded NRT, per family and UTC day",
    "confidence_filter": "all",
    "type_filter": "all",
    "wildfire_only": False,
    "equal_area": False,
    "burned_area": False,
    "bbox_semantics": "whole 0.1-degree grid cells; the requested rectangle is expanded outward to grid lines",
    "interpretation": "Observed active cell-days, not unique fires or burned area; platform exposures differ.",
}


def calendar(scope_id, start, end, bbox=None):
    """Календарь по дням — в том же формате, что grid_calendar() напарника."""
    area = resolve_area(scope_id, bbox)
    requested_days = (end - start).days + 1
    where, params = _where(area, start, end)
    with closing(_connect_index()) as idx:
        loaded, windows = _loaded_days(idx, scope_id, start, end)
        grouped = {r["day"]: dict(r) for r in idx.execute(f"""
            SELECT day,
                   SUM(modis) AS modis_observations, SUM(viirs) AS viirs_observations,
                   SUM(modis > 0) AS modis_cells, SUM(viirs > 0) AS viirs_cells,
                   SUM(modis > 0 AND viirs > 0) AS shared_cells
            FROM cells WHERE {where} GROUP BY day""", params)}

    daily = []
    for offset in range(requested_days):
        day = (start + timedelta(days=offset)).isoformat()
        values = grouped.get(day, {})
        row = {"date": day}
        for channel in ("modis", "viirs"):
            ok = day in loaded[channel]
            row[channel] = {
                "status": "loaded" if ok else "missing",
                "observations": int(values.get(f"{channel}_observations") or 0) if ok else None,
                "active_cells": int(values.get(f"{channel}_cells") or 0) if ok else None,
            }
        both = day in loaded["modis"] and day in loaded["viirs"]
        row["shared_active_cells"] = int(values.get("shared_cells") or 0) if both else None
        daily.append(row)

    totals = {}
    for channel in ("modis", "viirs"):
        complete = len(loaded[channel]) == requested_days
        totals[channel] = {
            "observations": sum(r[channel]["observations"] for r in daily) if complete else None,
            "active_cell_days": sum(r[channel]["active_cells"] for r in daily) if complete else None,
        }
    return {
        "scope_id": scope_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "bbox": area["bbox"],
        "requested_bbox": area["requested_bbox"],
        "method": dict(METHOD),
        "daily": daily,
        "coverage": {ch: {"loaded_days": len(loaded[ch]), "requested_days": requested_days}
                     for ch in ("modis", "viirs")},
        "totals": totals,
        "input_windows": windows,
    }


def monthly(scope_id, start, end, bbox=None):
    """Суммы по месяцам: ячейко-дни и число наблюдений, плюс полнота данных."""
    area = resolve_area(scope_id, bbox)
    where, params = _where(area, start, end)
    with closing(_connect_index()) as idx:
        sums = {r["month"]: dict(r) for r in idx.execute(f"""
            SELECT substr(day, 1, 7) AS month,
                   SUM(modis) AS modis_observations, SUM(viirs) AS viirs_observations,
                   SUM(modis > 0) AS modis_cell_days, SUM(viirs > 0) AS viirs_cell_days,
                   SUM(modis > 0 AND viirs > 0) AS shared_cell_days
            FROM cells WHERE {where} GROUP BY month""", params)}
        loaded = {}
        for r in idx.execute("""SELECT channel, substr(day, 1, 7) AS month, COUNT(*) AS n FROM windows
                                WHERE scope_id = ? AND day BETWEEN ? AND ? GROUP BY channel, month""",
                             (scope_id, start.isoformat(), end.isoformat())):
            loaded[(r["channel"], r["month"])] = r["n"]

    months = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        first, last = max(cursor, start), min(next_month - timedelta(days=1), end)
        key = cursor.strftime("%Y-%m")
        values = sums.get(key, {})
        item = {"month": key, "year": cursor.year, "month_number": cursor.month,
                "days": (last - first).days + 1}
        for channel in ("modis", "viirs"):
            n = loaded.get((channel, key), 0)
            item[channel] = {
                "status": "missing" if n == 0 else ("complete" if n == item["days"] else "partial"),
                "loaded_days": n,
                "active_cell_days": int(values.get(f"{channel}_cell_days") or 0) if n else None,
                "observations": int(values.get(f"{channel}_observations") or 0) if n else None,
            }
        both = item["modis"]["loaded_days"] and item["viirs"]["loaded_days"]
        item["shared_cell_days"] = int(values.get("shared_cell_days") or 0) if both else None
        months.append(item)
        cursor = next_month
    return {"scope_id": scope_id, "bbox": area["bbox"], "requested_bbox": area["requested_bbox"],
            "date_from": start.isoformat(), "date_to": end.isoformat(), "months": months}


def map_cells(scope_id, start, end, bbox=None, step=1, limit=20_000):
    """
    Клетки для карты. step — во сколько раз укрупнить клетки 0.1°
    (1 → 0.1°, 10 → 1°). Возвращает самые активные клетки первыми.
    """
    area = resolve_area(scope_id, bbox)
    where, params = _where(area, start, end)
    step = int(step)
    with closing(_connect_index()) as idx:
        rows = [dict(r) for r in idx.execute(f"""
            SELECT cell_y / {step} AS gy, cell_x / {step} AS gx,
                   SUM(modis) AS modis_observations, SUM(viirs) AS viirs_observations,
                   SUM(modis > 0) AS modis_cell_days, SUM(viirs > 0) AS viirs_cell_days,
                   COUNT(DISTINCT day) AS active_days
            FROM cells WHERE {where}
            GROUP BY gy, gx
            ORDER BY active_days DESC, modis_observations + viirs_observations DESC
            LIMIT ?""", [*params, limit + 1])]
    size = step / 10
    for r in rows:
        r["lon"] = round((r["gx"] * step + step / 2) / 10 - 180, 4)
        r["lat"] = round((r["gy"] * step + step / 2) / 10 - 90, 4)
        r["cell_size_degrees"] = size
    return {"area": area, "cells": rows[:limit], "truncated": len(rows) > limit}


def loaded_summary():
    """Что есть в индексе: по каждой области и ряду — первый/последний день и количество."""
    with closing(_connect_index()) as idx:
        result = {}
        for r in idx.execute("""SELECT scope_id, channel, MIN(day) AS first_day, MAX(day) AS last_day,
                                       COUNT(*) AS loaded_days, SUM(observations) AS observations,
                                       MAX(fetched_at) AS last_fetched_at
                                FROM windows GROUP BY scope_id, channel ORDER BY scope_id, channel"""):
            result.setdefault(r["scope_id"], {})[r["channel"]] = {
                k: r[k] for k in ("first_day", "last_day", "loaded_days", "observations", "last_fetched_at")}
        meta = {r["key"]: r["value"] for r in idx.execute("SELECT key, value FROM meta")}
        cells = idx.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
    return {"scopes": result, "last_refresh": meta.get("last_refresh"), "cell_rows": cells,
            "size_mb": round(_index_path().stat().st_size / 1024 / 1024, 1)}


def auto_refresh_state():
    return {"enabled": _auto["started"], "last_error": _auto["last_error"],
            "last_result": _auto["last_result"]}


if __name__ == "__main__":
    print("Обновляю индекс календаря...")
    print(refresh(progress=lambda message: print("  ", message, flush=True)))
