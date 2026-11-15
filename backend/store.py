"""
store.py — THE FIRESYNC DATABASE (data/firesync.sqlite3)

One SQLite file holds every MODIS (Terra + Aqua) and VIIRS NOAA-20 fire
detection: the 2000–2025 archive (importer.py) and everything that arrives
later from the NASA FIRMS API (updater.py). The API (main.py, frontend_api.py)
only reads from here.

Why detections are stored per day in compressed blocks
------------------------------------------------------
The archive has about 267 million MODIS + NOAA-20 detections. One SQLite row
per detection costs 30–600 bytes (with indexes), i.e. tens to hundreds of gigabytes. Here
all detections of one UTC day and one sensor are packed into one block: every
column (latitude, longitude, FRP, ...) is stored as whole numbers and
compressed separately. That is about 11 bytes per detection, so the whole
archive fits into about 3 GB, and reading a whole day takes milliseconds.

Values are stored exactly: latitude/longitude × 100 000, FRP, brightness,
scan and track × 100 — the precision NASA publishes.

Tables
------
  days           one row per stored UTC day and sensor: SP or NRT, where it came from,
                 how many detections. A stored day with 0 detections is a measured zero;
                 a day without a row has no data.
  day_data       the compressed detections of that day and sensor
  region_days    for every ready-made region (config.REGIONS) and day: active 0.1° cells,
                 detections and FRP per sensor — the calendar reads only this table
  region_months  per region, month and sensor: cell-days, distinct cells and their area, FRP
  meta           format version, data revision, import and update information

The grid is the partner's (data_pipeline/GRID_METHOD.md): 0.1° cells from
(-180, -90). MODIS = Terra + Aqua, VIIRS = NOAA-20 only. One product per sensor
and day: final science data (SP) if available, otherwise near-real-time (NRT);
they are never added together.
"""

import hashlib
import json
import math
import sqlite3
import struct
import threading
import zlib
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import config

FORMAT_VERSION = "1"
SENSORS = ("MODIS", "VIIRS")                 # VIIRS means VIIRS on NOAA-20
CHANNEL = {"MODIS": "modis", "VIIRS": "viirs"}
SATELLITES = ("Terra", "Aqua", "NOAA-20")    # stored as 0, 1, 2
SENSOR_SATELLITES = {"MODIS": ("Terra", "Aqua"), "VIIRS": ("NOAA-20",)}
PRODUCT_RANK = {"SP": 2, "NRT": 1}          # SP wins over NRT for the same sensor and day

# column -> (stored type, value meaning "missing" or None if never missing)
COLUMNS = {
    "lat": ("<i4", None),           # latitude × 100 000
    "lon": ("<i4", None),           # longitude × 100 000
    "time": ("<u2", None),          # acquisition time HHMM, UTC
    "frp": ("<u4", 0xFFFFFFFF),     # fire radiative power, MW × 100
    "bright": ("<u4", 0xFFFFFFFF),  # K × 100: MODIS `brightness`, VIIRS `bright_ti4`
    "bright2": ("<u4", 0xFFFFFFFF), # K × 100: MODIS `bright_t31`, VIIRS `bright_ti5`
    "scan": ("<u2", 0xFFFF),        # km × 100
    "track": ("<u2", 0xFFFF),       # km × 100
    "confidence": ("u1", 255),      # MODIS 0–100; VIIRS 1 low, 2 nominal, 3 high
    "satellite": ("u1", None),      # index in SATELLITES
    "daynight": ("u1", 0),          # 1 day, 2 night, 0 unknown
    "type": ("u1", 255),            # NASA `type` (0 vegetation fire, 1 volcano, 2 static source, 3 offshore)
    "version": ("u1", None),        # index in the block's list of product versions
}
FRP_MISSING = COLUMNS["frp"][1]
VIIRS_CONFIDENCE = {"l": 1, "low": 1, "n": 2, "nominal": 2, "h": 3, "high": 3}
VIIRS_CONFIDENCE_TEXT = {1: "l", 2: "n", 3: "h"}
MAGIC = b"FSD1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS days (
    id           INTEGER PRIMARY KEY,
    day          TEXT NOT NULL,      -- 'YYYY-MM-DD', UTC
    sensor       TEXT NOT NULL CHECK (sensor IN ('MODIS', 'VIIRS')),
    product      TEXT NOT NULL CHECK (product IN ('SP', 'NRT')),
    origin       TEXT NOT NULL,      -- 'archive' or 'api'
    observations INTEGER NOT NULL,
    cells        INTEGER NOT NULL,   -- distinct active 0.1° cells worldwide
    bytes        INTEGER NOT NULL,   -- size of the compressed block
    loaded_at    TEXT NOT NULL,
    UNIQUE (day, sensor)
);
CREATE TABLE IF NOT EXISTS day_data (
    id    INTEGER PRIMARY KEY,       -- = days.id
    block BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS region_days (
    region        TEXT NOT NULL,
    day           TEXT NOT NULL,
    modis_cells   INTEGER, viirs_cells INTEGER, shared_cells INTEGER,
    modis_obs     INTEGER, viirs_obs   INTEGER,
    modis_frp_n   INTEGER, modis_frp_sum REAL, modis_frp_max REAL,
    viirs_frp_n   INTEGER, viirs_frp_sum REAL, viirs_frp_max REAL,
    modis_product TEXT,    viirs_product TEXT,
    PRIMARY KEY (region, day)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS region_months (
    region            TEXT NOT NULL,
    month             TEXT NOT NULL,  -- 'YYYY-MM'
    sensor            TEXT NOT NULL,
    loaded_days       INTEGER NOT NULL,
    nrt_days          INTEGER NOT NULL,
    cell_days         INTEGER NOT NULL,
    cells             INTEGER NOT NULL,  -- distinct cells active at least once in the month
    area_km2          REAL NOT NULL,     -- area of those distinct cells
    cell_day_area_km2 REAL NOT NULL,     -- sum over days of the active cells' area
    observations      INTEGER NOT NULL,
    frp_n             INTEGER NOT NULL,
    frp_sum           REAL NOT NULL,
    frp_max           REAL,
    PRIMARY KEY (region, month, sensor)
) WITHOUT ROWID;
"""


class StoreNotReady(Exception):
    """The database file does not exist yet (the archive has not been imported)."""


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

def db_path():
    return Path(config.STORE_PATH)


def connect(path=None, *, create=False):
    """A connection to the database. Readers never block the background writer (WAL)."""
    path = Path(path or db_path())
    if not create and not path.is_file():
        raise StoreNotReady("The fire database has not been created yet. Run importer.py first.")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if create:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        with conn:
            if get_meta(conn, "format_version") is None:
                set_meta(conn, format_version=FORMAT_VERSION, revision="0")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -65536")   # 64 MB page cache
    if get_meta(conn, "format_version") not in (None, FORMAT_VERSION):
        conn.close()
        raise StoreNotReady("The database was written by a different FireSync version. Re-run importer.py.")
    return conn


def get_meta(conn, key, default=None):
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:   # table not created yet
        return default
    return default if row is None else row[0]


def set_meta(conn, **values):
    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     [(k, v if v is None or isinstance(v, str) else json.dumps(v)) for k, v in values.items()])


def revision(conn):
    """A number that grows with every change of the data (used to invalidate API caches)."""
    return int(get_meta(conn, "revision", "0"))


def bump_revision(conn):
    set_meta(conn, revision=str(revision(conn) + 1), changed_at=utc_now_text())


def utc_now_text():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Compressed day blocks
# ---------------------------------------------------------------------------

def _shuffle(array):
    """Bytes of every value grouped by position: similar numbers compress much better."""
    size = array.dtype.itemsize
    raw = np.ascontiguousarray(array).view(np.uint8)
    return raw.reshape(-1, size).T.tobytes() if size > 1 else raw.tobytes()


def _unshuffle(data, dtype, n):
    dtype = np.dtype(dtype)
    raw = np.frombuffer(data, np.uint8)
    if dtype.itemsize > 1:
        raw = raw.reshape(dtype.itemsize, n).T
    return np.ascontiguousarray(raw).view(dtype).reshape(n)


def encode_block(columns, versions):
    """
    columns: dict name -> numpy array (all COLUMNS, same length).
    Rows are sorted by latitude, longitude and time; latitude is stored as
    differences, so neighbouring detections cost almost nothing.
    """
    n = len(columns["lat"])
    order = np.lexsort((columns["time"], columns["lon"], columns["lat"]))
    header = {"n": n, "versions": list(versions), "columns": []}
    parts = []
    for name, (dtype, _) in COLUMNS.items():
        values = np.asarray(columns[name], dtype=dtype)[order]
        if name == "lat" and n:
            values = np.diff(values, prepend=np.int32(0)).astype(dtype)
        data = zlib.compress(_shuffle(values), 6)
        header["columns"].append([name, len(data)])
        parts.append(data)
    head = json.dumps(header, separators=(",", ":")).encode()
    return MAGIC + struct.pack("<I", len(head)) + head + b"".join(parts)


def decode_block(block, names=None):
    """Decompress the requested columns (all by default). Returns (columns, versions)."""
    if block[:4] != MAGIC:
        raise ValueError("Unknown data block format.")
    (size,) = struct.unpack_from("<I", block, 4)
    header = json.loads(block[8:8 + size])
    n, position, result = header["n"], 8 + size, {}
    wanted = set(names or COLUMNS)
    for name, length in header["columns"]:
        if name in wanted:
            values = _unshuffle(zlib.decompress(block[position:position + length]), COLUMNS[name][0], n)
            if name == "lat":
                values = np.cumsum(values, dtype=np.int64).astype(np.int32)
            result[name] = values
        position += length
    return result, header["versions"]


def empty_columns():
    return {name: np.zeros(0, dtype=dtype) for name, (dtype, _) in COLUMNS.items()}


# ---------------------------------------------------------------------------
# Grid (identical to the partner's GRID_METHOD.md)
# ---------------------------------------------------------------------------

def cell_ids(lat, lon):
    """Detections → 0.1° cell number = row × 3600 + column, rows from -90°, columns from -180°."""
    gy = np.minimum((lat.astype(np.int64) + 9_000_000) // 10_000, 1799)
    gx = np.minimum((lon.astype(np.int64) + 18_000_000) // 10_000, 3599)
    return gy * 3600 + gx


def _ticks(value):
    return int(math.copysign(math.floor(abs(value) * 10_000_000 + 0.5), value))


def cell_range(bbox):
    """(west, south, east, north) → (y_from, y_to, x_from, x_to) of the whole cells it touches."""
    west, south, east, north = bbox
    x_from = (_ticks(west) + 1_800_000_000) // 1_000_000
    x_to = -(-(_ticks(east) + 1_800_000_000) // 1_000_000) - 1
    y_from = (_ticks(south) + 900_000_000) // 1_000_000
    y_to = -(-(_ticks(north) + 900_000_000) // 1_000_000) - 1
    clamp = lambda v, hi: max(0, min(hi, v))  # noqa: E731
    return clamp(y_from, 1799), clamp(max(y_to, y_from), 1799), clamp(x_from, 3599), clamp(max(x_to, x_from), 3599)


def cells_to_bbox(cells):
    """Cell range → the rectangle that is actually counted (along grid lines)."""
    y_from, y_to, x_from, x_to = cells
    return [round(x_from / 10 - 180, 1), round(y_from / 10 - 90, 1),
            round((x_to + 1) / 10 - 180, 1), round((y_to + 1) / 10 - 90, 1)]


def in_cells(ids, cells):
    """Boolean mask: which cell numbers lie inside a cell range (None = everywhere)."""
    if cells is None:
        return np.ones(len(ids), dtype=bool)
    y_from, y_to, x_from, x_to = cells
    gy, gx = ids // 3600, ids % 3600
    return (gy >= y_from) & (gy <= y_to) & (gx >= x_from) & (gx <= x_to)


EARTH_RADIUS_KM = 6371.0088
_ROW_AREA = np.array([
    math.radians(0.1) * EARTH_RADIUS_KM ** 2
    * (math.sin(math.radians((y + 1) / 10 - 90)) - math.sin(math.radians(y / 10 - 90)))
    for y in range(1800)])


def cell_area_km2(ids):
    """Area of 0.1° cells on a spherical Earth: cells near the poles are smaller."""
    return _ROW_AREA[np.asarray(ids) // 3600]


def summarize_cells(lat, lon, frp):
    """
    Per active cell of one day: number of detections, number with FRP, FRP sum and maximum
    (FRP in MW × 100; detections without FRP are not counted as zero).
    """
    ids = cell_ids(lat, lon)
    if not len(ids):
        z = np.zeros(0, dtype=np.int64)
        return {"cell": z, "obs": z, "frp_n": z, "frp_sum": z, "frp_max": z}
    order = np.argsort(ids)
    ids = ids[order]
    starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
    values = frp[order].astype(np.int64)
    valid = values != FRP_MISSING
    return {"cell": ids[starts],
            "obs": np.diff(np.r_[starts, len(ids)]),
            "frp_n": np.add.reduceat(valid.astype(np.int64), starts),
            "frp_sum": np.add.reduceat(np.where(valid, values, 0), starts),
            "frp_max": np.maximum.reduceat(np.where(valid, values, -1), starts)}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_day(conn, day, sensor, product, origin, columns, versions):
    """
    Store (or replace) all detections of one UTC day and sensor.
    The caller decides whether replacing is allowed (SP is never replaced by NRT).
    Region tables are refreshed separately by rebuild_months().
    """
    if sensor not in SENSORS or product not in PRODUCT_RANK:
        raise ValueError("Unknown sensor or product.")
    block = encode_block(columns, versions)
    n = len(columns["lat"])
    cells = len(np.unique(cell_ids(columns["lat"], columns["lon"]))) if n else 0
    day_text = day if isinstance(day, str) else day.isoformat()
    values = (product, origin, n, cells, len(block), utc_now_text())
    row = conn.execute("SELECT id FROM days WHERE day = ? AND sensor = ?", (day_text, sensor)).fetchone()
    if row:
        conn.execute("UPDATE days SET product = ?, origin = ?, observations = ?, cells = ?, bytes = ?, "
                     "loaded_at = ? WHERE id = ?", (*values, row[0]))
        conn.execute("UPDATE day_data SET block = ? WHERE id = ?", (block, row[0]))
    else:
        cursor = conn.execute("INSERT INTO days (day, sensor, product, origin, observations, cells, bytes, "
                              "loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (day_text, sensor, *values))
        conn.execute("INSERT INTO day_data (id, block) VALUES (?, ?)", (cursor.lastrowid, block))
    return {"day": day_text, "sensor": sensor, "product": product, "observations": n,
            "cells": cells, "bytes": len(block)}


def stored_day(conn, day, sensor):
    """The `days` row of one day and sensor, or None."""
    row = conn.execute("SELECT * FROM days WHERE day = ? AND sensor = ?",
                       (day if isinstance(day, str) else day.isoformat(), sensor)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Region tables
# ---------------------------------------------------------------------------

def region_cells():
    """{region id: cell range or None for the whole world} from config.REGIONS."""
    return {key: None if info["bbox"] is None else cell_range(info["bbox"])
            for key, info in config.REGIONS.items()}


def regions_signature():
    text = json.dumps({k: v["bbox"] for k, v in config.REGIONS.items()}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def read_day(conn, day, sensor, names=("lat", "lon", "frp")):
    """Decoded columns of one stored day, or None if that day is not stored."""
    row = conn.execute("SELECT d.block FROM days JOIN day_data d ON d.id = days.id "
                       "WHERE days.day = ? AND days.sensor = ?",
                       (day if isinstance(day, str) else day.isoformat(), sensor)).fetchone()
    return None if row is None else decode_block(row[0], names)[0]


def month_days(month):
    """'2024-08' → list of 'YYYY-MM-DD' strings."""
    first = date(int(month[:4]), int(month[5:7]), 1)
    following = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    return [(first + timedelta(days=i)).isoformat() for i in range((following - first).days)]


def compute_month(path, month):
    """
    Region rows for one month, computed from the stored blocks (no writing, so it can
    run in a worker process). Returns (region_days rows, region_months rows).
    """
    regions = region_cells()
    day_rows, month_rows = [], []
    with closing(connect(path)) as conn:
        stored = {(r["day"], r["sensor"]): r["product"] for r in conn.execute(
            "SELECT day, sensor, product FROM days WHERE day LIKE ?", (month + "-%",))}
        totals = {(region, sensor): {"loaded_days": 0, "nrt_days": 0, "cell_days": 0, "cells": [],
                                     "cell_day_area_km2": 0.0, "observations": 0, "frp_n": 0,
                                     "frp_sum": 0, "frp_max": None}
                  for region in regions for sensor in SENSORS}
        for day in month_days(month):
            present = {s: stored[(day, s)] for s in SENSORS if (day, s) in stored}
            if not present:
                continue
            summaries = {}
            for sensor in present:
                data = read_day(conn, day, sensor)
                summaries[sensor] = summarize_cells(data["lat"], data["lon"], data["frp"])
            for region, cells in regions.items():
                row = {"region": region, "day": day}
                inside = {}
                for sensor in SENSORS:
                    ch = CHANNEL[sensor]
                    if sensor not in summaries:
                        row.update({f"{ch}_cells": None, f"{ch}_obs": None, f"{ch}_frp_n": None,
                                    f"{ch}_frp_sum": None, f"{ch}_frp_max": None, f"{ch}_product": None})
                        continue
                    s = summaries[sensor]
                    mask = in_cells(s["cell"], cells)
                    inside[sensor] = s["cell"][mask]
                    frp_max = int(s["frp_max"][mask].max()) if mask.any() else -1
                    frp_sum = int(s["frp_sum"][mask].sum())
                    row.update({f"{ch}_cells": int(mask.sum()), f"{ch}_obs": int(s["obs"][mask].sum()),
                                f"{ch}_frp_n": int(s["frp_n"][mask].sum()), f"{ch}_frp_sum": frp_sum / 100,
                                f"{ch}_frp_max": frp_max / 100 if frp_max >= 0 else None,
                                f"{ch}_product": present[sensor]})
                    t = totals[(region, sensor)]
                    t["loaded_days"] += 1
                    t["nrt_days"] += present[sensor] == "NRT"
                    t["cell_days"] += int(mask.sum())
                    t["cells"].append(inside[sensor])
                    t["cell_day_area_km2"] += float(cell_area_km2(inside[sensor]).sum())
                    t["observations"] += int(s["obs"][mask].sum())
                    t["frp_n"] += int(s["frp_n"][mask].sum())
                    t["frp_sum"] += frp_sum
                    if frp_max >= 0:
                        t["frp_max"] = max(t["frp_max"] or 0, frp_max)
                row["shared_cells"] = (len(np.intersect1d(inside["MODIS"], inside["VIIRS"], assume_unique=True))
                                       if len(inside) == 2 else None)
                day_rows.append(row)
    for (region, sensor), t in totals.items():
        if not t["loaded_days"]:
            continue
        distinct = np.unique(np.concatenate(t["cells"])) if t["cells"] else np.zeros(0, dtype=np.int64)
        month_rows.append({"region": region, "month": month, "sensor": sensor,
                           "loaded_days": t["loaded_days"], "nrt_days": t["nrt_days"],
                           "cell_days": t["cell_days"], "cells": len(distinct),
                           "area_km2": round(float(cell_area_km2(distinct).sum()), 1),
                           "cell_day_area_km2": round(t["cell_day_area_km2"], 1),
                           "observations": t["observations"], "frp_n": t["frp_n"],
                           "frp_sum": t["frp_sum"] / 100,
                           "frp_max": None if t["frp_max"] is None else t["frp_max"] / 100})
    return day_rows, month_rows


DAY_COLUMNS = ["region", "day", "modis_cells", "viirs_cells", "shared_cells", "modis_obs", "viirs_obs",
               "modis_frp_n", "modis_frp_sum", "modis_frp_max", "viirs_frp_n", "viirs_frp_sum",
               "viirs_frp_max", "modis_product", "viirs_product"]
MONTH_COLUMNS = ["region", "month", "sensor", "loaded_days", "nrt_days", "cell_days", "cells", "area_km2",
                 "cell_day_area_km2", "observations", "frp_n", "frp_sum", "frp_max"]


def save_month(conn, month, day_rows, month_rows):
    """Replace the region rows of one month (inside the caller's transaction)."""
    conn.execute("DELETE FROM region_days WHERE day LIKE ?", (month + "-%",))
    conn.execute("DELETE FROM region_months WHERE month = ?", (month,))
    conn.executemany(f"INSERT INTO region_days ({', '.join(DAY_COLUMNS)}) VALUES "
                     f"({', '.join('?' * len(DAY_COLUMNS))})", [[r[c] for c in DAY_COLUMNS] for r in day_rows])
    conn.executemany(f"INSERT INTO region_months ({', '.join(MONTH_COLUMNS)}) VALUES "
                     f"({', '.join('?' * len(MONTH_COLUMNS))})", [[r[c] for c in MONTH_COLUMNS] for r in month_rows])


def rebuild_months(conn, months, path=None, pool=None, progress=None):
    """Recompute the region tables for the given months and publish them as one new revision."""
    months = sorted(set(months))
    path = path or db_path()
    jobs = (pool.imap(_compute_month_job, [(str(path), m) for m in months]) if pool
            else (compute_month(path, m) for m in months))
    for number, (month, (day_rows, month_rows)) in enumerate(zip(months, jobs), 1):
        with conn:
            save_month(conn, month, day_rows, month_rows)
        if progress:
            progress(number, len(months), month)
    with conn:
        set_meta(conn, regions_signature=regions_signature())
        bump_revision(conn)


def _compute_month_job(args):
    return compute_month(*args)


def all_months(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT substr(day, 1, 7) FROM days ORDER BY 1")]


# ---------------------------------------------------------------------------
# Reading (used by the API)
# ---------------------------------------------------------------------------

def coverage(conn):
    """Per sensor: first and last stored day, number of days, how many are NRT, detections."""
    result = {}
    for r in conn.execute("""SELECT sensor, MIN(day) AS first_day, MAX(day) AS last_day, COUNT(*) AS days,
                                    SUM(product = 'NRT') AS nrt_days, SUM(observations) AS observations,
                                    SUM(origin = 'api') AS api_days
                             FROM days GROUP BY sensor"""):
        result[CHANNEL[r["sensor"]]] = {k: r[k] for k in ("first_day", "last_day", "days", "nrt_days",
                                                         "observations", "api_days")}
    return result


def stored_days(conn, start, end):
    """{(day, sensor): product} for a period."""
    return {(r["day"], r["sensor"]): r["product"] for r in conn.execute(
        "SELECT day, sensor, product FROM days WHERE day BETWEEN ? AND ?", (str(start), str(end)))}


def region_day_rows(conn, region, start, end):
    return {r["day"]: dict(r) for r in conn.execute(
        "SELECT * FROM region_days WHERE region = ? AND day BETWEEN ? AND ? ORDER BY day",
        (region, str(start), str(end)))}


def region_month_rows(conn, region, first_month, last_month):
    return {(r["month"], r["sensor"]): dict(r) for r in conn.execute(
        "SELECT * FROM region_months WHERE region = ? AND month BETWEEN ? AND ?",
        (region, first_month, last_month))}


_summaries = {}
_summaries_lock = threading.Lock()


def day_cell_summary(conn, day, sensor):
    """Per-cell summary of one stored day (cached until the data changes), or None."""
    key = (revision(conn), str(day), sensor)
    with _summaries_lock:
        if key in _summaries:
            return _summaries[key]
    data = read_day(conn, day, sensor)
    result = None if data is None else summarize_cells(data["lat"], data["lon"], data["frp"])
    with _summaries_lock:
        if len(_summaries) >= 96:
            _summaries.pop(next(iter(_summaries)))
        _summaries[key] = result
    return result


def detections(conn, day, sensor, cells=None):
    """
    Detections of one day and sensor as plain values, optionally only inside a cell range.
    Sorted by time. Returns a list of dicts (empty if the day is not stored).
    """
    row = conn.execute("SELECT d.block FROM days JOIN day_data d ON d.id = days.id "
                       "WHERE days.day = ? AND days.sensor = ?", (str(day), sensor)).fetchone()
    if row is None:
        return []
    data, versions = decode_block(row[0])
    mask = in_cells(cell_ids(data["lat"], data["lon"]), cells)
    data = {k: v[mask] for k, v in data.items()}
    order = np.lexsort((data["lon"], data["lat"], data["time"]))
    day_text = str(day)
    out = []
    for i in order:
        hhmm = int(data["time"][i])
        out.append({
            "acq_date": day_text, "acq_time": f"{hhmm:04d}",
            "observed_at": f"{day_text}T{hhmm // 100:02d}:{hhmm % 100:02d}:00Z",
            "sensor": sensor, "satellite": SATELLITES[data["satellite"][i]],
            "latitude": int(data["lat"][i]) / 100000, "longitude": int(data["lon"][i]) / 100000,
            "frp_mw": _scaled(data["frp"][i], COLUMNS["frp"][1]),
            "brightness_k": _scaled(data["bright"][i], COLUMNS["bright"][1]),
            "brightness2_k": _scaled(data["bright2"][i], COLUMNS["bright2"][1]),
            "scan_km": _scaled(data["scan"][i], COLUMNS["scan"][1]),
            "track_km": _scaled(data["track"][i], COLUMNS["track"][1]),
            "confidence": _confidence(sensor, int(data["confidence"][i])),
            "daynight": {1: "D", 2: "N"}.get(int(data["daynight"][i])),
            "type": None if data["type"][i] == 255 else int(data["type"][i]),
            "version": versions[data["version"][i]],
        })
    return out


def _scaled(value, missing):
    return None if int(value) == missing else int(value) / 100


def _confidence(sensor, value):
    if value == 255:
        return None
    return str(value) if sensor == "MODIS" else VIIRS_CONFIDENCE_TEXT.get(value)


def summary(conn):
    """Short description of what the database holds (for /status and /api/meta)."""
    size = db_path().stat().st_size if db_path().is_file() else None
    return {"coverage": coverage(conn), "revision": revision(conn),
            "changed_at": get_meta(conn, "changed_at"),
            "archive": json.loads(get_meta(conn, "archive_import", "null")),
            "size_mb": None if size is None else round(size / 1024 ** 2, 1)}


_lock = threading.Lock()


def writer_lock():
    """Only one writer (importer, updater, region rebuild) at a time inside one process."""
    return _lock
