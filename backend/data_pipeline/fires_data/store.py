"""SQLite storage independent of the application's web framework.

Constructing Store never creates a file. Call initialize explicitly. Each
operation owns its SQLite connection, so readers can be called from FastAPI's
thread pool while one ingestion worker performs bounded write transactions.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Iterable
from uuid import uuid4

from .errors import StorageError
from .types import Availability, FetchPayload, Observation, PRODUCTS, Scope, utc_now, utc_text


SCHEMA_VERSION = 1
JOB_STATUSES = {"pending", "running", "completed", "paused", "failed"}
JOB_FIELDS = {"status", "completed_units", "skipped_units", "failed_units", "error"}


def _day(value):
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("Dates must be datetime.date values.")
    return value.isoformat()


def _period(start, end):
    start_text, end_text = _day(start), _day(end)
    if end < start:
        raise ValueError("End date precedes start date.")
    return start_text, end_text


def _days(start, end):
    count = (end - start).days + 1
    for offset in range(count):
        yield start + timedelta(days=offset)


def _source(source_code):
    if source_code not in PRODUCTS:
        raise ValueError(f"Unsupported source code: {source_code!r}.")
    return PRODUCTS[source_code]


def _safe_error(error):
    text = str(error)
    text = re.sub(r"(/api/(?:area|data_availability)/csv/)[^/\s]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(MAP_KEY=)[^&\s]+", r"\1[redacted]", text)
    return text[:4000]


def _scope_id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A scope_id is required; global aggregation across scopes is not supported.")
    return value


def _nonnegative_integer(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
    return value


def _bbox_values(bbox):
    if bbox is None:
        return None
    try:
        return Scope.from_bbox(bbox).bbox
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("bbox must be west,south,east,north within geographic bounds.") from exc


def _bbox_filter(bbox):
    if bbox is None:
        return "", []
    west, south, east, north = bbox
    return (" AND d.longitude>=? AND d.longitude<=? AND d.latitude>=? AND d.latitude<=?",
            [west, east, south, north])


def _canonical_cte(scope_id=None, start=None, end=None):
    conditions = ["w.status = 'loaded'"]
    params = []
    if scope_id is not None:
        conditions.append("w.scope_id = ?")
        params.append(scope_id)
    if start is not None:
        conditions.append("w.day >= ?")
        params.append(start)
    if end is not None:
        conditions.append("w.day <= ?")
        params.append(end)
    # Prefer by loaded WINDOW, not by the presence of rows. A successful empty
    # SP day must suppress an older NRT snapshot of the same family and day.
    sql = """
        WITH ranked_windows AS (
            SELECT w.id, w.scope_id, w.source_code, w.day,
                   ROW_NUMBER() OVER (
                       PARTITION BY w.scope_id, p.family, w.day
                       ORDER BY p.priority DESC, w.id DESC
                   ) AS preference
            FROM fetch_windows AS w
            JOIN products AS p ON p.source_code = w.source_code
            WHERE """ + " AND ".join(conditions) + """
        ), canonical_windows AS (
            SELECT id, scope_id, source_code, day
            FROM ranked_windows WHERE preference = 1
        )
    """
    return sql, params


class Store:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise ValueError("Use a temporary SQLite file, not :memory:, with per-operation connections.")
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def _connection(self, *, write=False):
        if not self.path.is_file():
            raise StorageError("Database is not initialized. Run the init command first.")
        mode = "rw" if write else "ro"
        conn = None
        try:
            conn = sqlite3.connect(self.path.as_uri() + f"?mode={mode}", uri=True,
                                   timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise StorageError("Unsupported database schema version. Initialize the pipeline database first.")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute("BEGIN")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"SQLite operation failed: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()

    def initialize(self):
        """Create an empty pipeline database or verify an existing one."""
        conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise StorageError(f"Unsupported database schema version: {version}.")
            if version == 0:
                existing = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise StorageError("This is another application's database. Choose a new pipeline database path.")
            conn.execute("PRAGMA journal_mode = WAL")
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            conn.executescript("BEGIN IMMEDIATE;\n" + schema)
            conn.executemany(
                """INSERT INTO products(source_code, sensor, family, processing, priority, expected_platform)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_code) DO UPDATE SET sensor=excluded.sensor,
                   family=excluded.family, processing=excluded.processing,
                   priority=excluded.priority, expected_platform=excluded.expected_platform""",
                [(p.code, p.sensor, p.family, p.processing, p.priority, p.expected_platform)
                 for p in PRODUCTS.values()],
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        except (OSError, sqlite3.Error) as exc:
            if conn is not None:
                conn.rollback()
            raise StorageError(f"Cannot initialize pipeline database: {exc}") from exc
        except BaseException:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _require_scope(conn, scope_id):
        _scope_id(scope_id)
        row = conn.execute("SELECT * FROM scopes WHERE id=?", (scope_id,)).fetchone()
        if row is None:
            raise StorageError(f"Scope {scope_id!r} does not exist.")
        return row

    @staticmethod
    def _save_scope(conn, scope):
        row = conn.execute("SELECT * FROM scopes WHERE id=?", (scope.id,)).fetchone()
        if row is not None:
            bounds = tuple(row[name] for name in ("west", "south", "east", "north"))
            if bounds != scope.bbox:
                raise StorageError("This scope_id already belongs to a different bounding box.")
            conn.execute("UPDATE scopes SET name=? WHERE id=?", (scope.name, scope.id))
        else:
            duplicate = conn.execute(
                "SELECT id FROM scopes WHERE west=? AND south=? AND east=? AND north=?", scope.bbox
            ).fetchone()
            if duplicate is not None:
                raise StorageError(f"This bounding box is already registered as scope {duplicate['id']!r}.")
            conn.execute(
                "INSERT INTO scopes(id,name,west,south,east,north,created_at) VALUES(?,?,?,?,?,?,?)",
                (scope.id, scope.name, *scope.bbox, utc_text(utc_now())),
            )

    def save_scope(self, scope: Scope):
        with self._connection(write=True) as conn:
            self._save_scope(conn, scope)

    def get_scope(self, scope_id) -> Scope:
        with self._connection() as conn:
            row = self._require_scope(conn, scope_id)
            return Scope(row["id"], row["name"], row["west"], row["south"], row["east"], row["north"])

    def list_scopes(self):
        with self._connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM scopes ORDER BY name, id")]

    def save_availability(self, values: dict[str, Availability]):
        if not values:
            raise ValueError("An empty availability result cannot replace known availability.")
        for code, value in values.items():
            _source(code)
            if not isinstance(value, Availability) or code != value.source_code:
                raise ValueError("Availability keys must match their source_code.")
        checked_at = utc_text(utc_now())
        with self._connection(write=True) as conn:
            conn.execute("DELETE FROM availability")
            conn.executemany(
                "INSERT INTO availability(source_code,min_date,max_date,checked_at) VALUES(?,?,?,?)",
                [(code, _day(v.min_date), _day(v.max_date), checked_at) for code, v in values.items()],
            )

    def get_availability(self):
        with self._connection() as conn:
            return {row["source_code"]: Availability(row["source_code"], date.fromisoformat(row["min_date"]),
                                                      date.fromisoformat(row["max_date"]))
                    for row in conn.execute("SELECT * FROM availability ORDER BY source_code")}

    def get_window(self, scope_id, source_code, day):
        _source(source_code)
        with self._connection() as conn:
            self._require_scope(conn, scope_id)
            row = conn.execute(
                "SELECT * FROM fetch_windows WHERE scope_id=? AND source_code=? AND day=?",
                (scope_id, source_code, _day(day)),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_windows(self, scope_id, start, end):
        start_text, end_text = _period(start, end)
        with self._connection() as conn:
            self._require_scope(conn, scope_id)
            return [dict(row) for row in conn.execute(
                "SELECT * FROM fetch_windows WHERE scope_id=? AND day BETWEEN ? AND ? ORDER BY day, source_code",
                (scope_id, start_text, end_text),
            )]

    @staticmethod
    def _observation_values(observation, product, scope, window_ids):
        if not isinstance(observation, Observation):
            raise ValueError("Expected an Observation value.")
        day_text = _day(observation.day)
        if day_text not in window_ids:
            raise ValueError("Observation lies outside the fetched date interval.")
        if observation.sensor != product.sensor:
            raise ValueError("Observation sensor does not match its source product.")
        allowed = {"SP"} if product.processing == "SP" else {"NRT", "RT", "URT"}
        if observation.processing not in allowed:
            raise ValueError("Observation processing does not match its source product.")
        if not isinstance(observation.satellite, str) or not observation.satellite.strip():
            raise ValueError("Observation satellite cannot be empty.")
        if not isinstance(observation.product_version, str) or not observation.product_version.strip():
            raise ValueError("Observation version cannot be empty.")
        lat, lon = observation.latitude, observation.longitude
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (lat, lon)):
            raise ValueError("Observation coordinates must be finite numbers.")
        if not (scope.west <= lon <= scope.east and scope.south <= lat <= scope.north):
            raise ValueError("Observation lies outside the fetched scope.")
        for name in ("brightness_k", "frp_mw", "scan_km", "track_km"):
            number = getattr(observation, name)
            if number is not None and (not isinstance(number, (int, float)) or isinstance(number, bool)
                                       or not math.isfinite(number) or number < 0):
                raise ValueError(f"Observation {name} must be finite and non-negative.")
        if observation.daynight not in (None, "D", "N"):
            raise ValueError("Observation daynight must be D, N or null.")
        if not isinstance(observation.record_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", observation.record_hash):
            raise ValueError("Observation record_hash must be a SHA-256 hex string.")
        raw_json = json.dumps(dict(observation.raw), sort_keys=True, ensure_ascii=False, allow_nan=False)
        return (window_ids[day_text], utc_text(observation.observed_at), observation.sensor,
                observation.satellite, lat, lon, observation.brightness_k, observation.frp_mw,
                observation.confidence_raw, observation.daynight, observation.product_version,
                observation.processing, observation.scan_km, observation.track_km, observation.type_code,
                raw_json, observation.record_hash.lower())

    def replace_batch(self, scope: Scope, payload: FetchPayload,
                      observations: Iterable[Observation]):
        if payload.scope_id != scope.id:
            raise ValueError("Fetched payload belongs to a different scope.")
        product = _source(payload.source_code)
        _period(payload.start, payload.end)
        fetched_at = utc_text(payload.fetched_at)
        checksum = payload.checksum
        day_keys = [_day(d) for d in _days(payload.start, payload.end)]
        # Reconstruct provenance from non-secret request parameters; never store
        # an arbitrary request URL that might contain the owner's MAP_KEY.
        request_url = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/[redacted]/"
                       f"{payload.source_code}/{scope.api_area}/"
                       f"{len(day_keys)}/{payload.start.isoformat()}")
        with self._connection(write=True) as conn:
            self._save_scope(conn, scope)
            window_ids = {}
            for day_text in day_keys:
                conn.execute(
                    "INSERT INTO fetch_windows(scope_id,source_code,day) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                    (scope.id, payload.source_code, day_text),
                )
                window_id = conn.execute(
                    "SELECT id FROM fetch_windows WHERE scope_id=? AND source_code=? AND day=?",
                    (scope.id, payload.source_code, day_text),
                ).fetchone()[0]
                window_ids[day_text] = window_id
                conn.execute("DELETE FROM detections WHERE window_id=?", (window_id,))
            insert_sql = """INSERT INTO detections(
                window_id,observed_at,sensor,satellite,latitude,longitude,brightness_k,frp_mw,
                confidence_raw,daynight,product_version,processing,scan_km,track_km,type_code,raw_json,record_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(window_id,record_hash) DO NOTHING"""
            batch = []
            for observation in observations:
                batch.append(self._observation_values(observation, product, scope, window_ids))
                if len(batch) >= 1000:
                    conn.executemany(insert_sql, batch)
                    batch.clear()
            if batch:
                conn.executemany(insert_sql, batch)
            total_rows = 0
            for window_id in window_ids.values():
                count = conn.execute("SELECT COUNT(*) FROM detections WHERE window_id=?", (window_id,)).fetchone()[0]
                total_rows += count
                conn.execute(
                    """UPDATE fetch_windows SET status='loaded',row_count=?,checksum=?,fetched_at=?,
                       last_attempt_at=?,attempt_count=attempt_count+1,last_error=NULL,request_url_redacted=?
                       WHERE id=?""",
                    (count, checksum, fetched_at, fetched_at, request_url, window_id),
                )
            return {"rows": total_rows, "days": len(day_keys)}

    def record_failure(self, scope_id, source_code, start, end, error):
        _source(source_code)
        _period(start, end)
        stamp = utc_text(utc_now())
        safe_error = _safe_error(error)
        with self._connection(write=True) as conn:
            self._require_scope(conn, scope_id)
            conn.executemany(
                """INSERT INTO fetch_windows(scope_id,source_code,day,status,last_attempt_at,last_error,attempt_count)
                   VALUES(?,?,?,'failed',?,?,1)
                   ON CONFLICT(scope_id,source_code,day) DO UPDATE SET
                   status=CASE WHEN fetch_windows.status='loaded' THEN 'loaded' ELSE 'failed' END,
                   last_attempt_at=excluded.last_attempt_at,last_error=excluded.last_error,
                   attempt_count=fetch_windows.attempt_count+1""",
                [(scope_id, source_code, _day(d), stamp, safe_error) for d in _days(start, end)],
            )

    def create_job(self, scope_id, sources, start, end, total_units):
        start_text, end_text = _period(start, end)
        _nonnegative_integer(total_units, "total_units")
        if not isinstance(sources, list) or not sources:
            raise ValueError("A job needs a non-empty list of sources.")
        sources = list(dict.fromkeys(sources))
        for source in sources:
            _source(source)
        job_id, stamp = uuid4().hex, utc_text(utc_now())
        with self._connection(write=True) as conn:
            self._require_scope(conn, scope_id)
            conn.execute(
                """INSERT INTO sync_jobs(id,scope_id,sources_json,start,end,total_units,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (job_id, scope_id, json.dumps(sources), start_text, end_text, total_units, stamp, stamp),
            )
        return job_id

    def update_job(self, job_id, **fields):
        if not fields or not set(fields) <= JOB_FIELDS:
            raise ValueError("Unsupported or empty job update.")
        if "status" in fields and fields["status"] not in JOB_STATUSES:
            raise ValueError("Unsupported job status.")
        for key in ("completed_units", "skipped_units", "failed_units"):
            if key in fields:
                _nonnegative_integer(fields[key], key)
        if fields.get("error") is not None:
            fields["error"] = _safe_error(fields["error"])
        fields["updated_at"] = utc_text(utc_now())
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._connection(write=True) as conn:
            cursor = conn.execute(f"UPDATE sync_jobs SET {assignments} WHERE id=?", (*fields.values(), job_id))
            if cursor.rowcount != 1:
                raise StorageError("Job does not exist.")

    @staticmethod
    def _job_dict(row):
        result = dict(row)
        result["sources"] = json.loads(result.pop("sources_json"))
        return result

    def get_job(self, job_id):
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM sync_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise StorageError("Job does not exist.")
            return self._job_dict(row)

    def list_jobs(self, limit=20):
        _nonnegative_integer(limit, "limit")
        with self._connection() as conn:
            return [self._job_dict(row) for row in conn.execute(
                "SELECT * FROM sync_jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            )]

    def observations(self, scope_id, start, end, sensor=None, satellite=None, limit=1000, offset=0,
                     *, bbox=None):
        _scope_id(scope_id)
        start_text, end_text = _period(start, end)
        _nonnegative_integer(limit, "limit")
        _nonnegative_integer(offset, "offset")
        if sensor is not None and sensor not in ("MODIS", "VIIRS"):
            raise ValueError("Sensor must be MODIS or VIIRS.")
        if satellite is not None and (not isinstance(satellite, str) or not satellite.strip()):
            raise ValueError("Satellite cannot be empty.")
        bounds = _bbox_values(bbox)
        sql, params = _canonical_cte(scope_id, start_text, end_text)
        sql += """SELECT d.*,w.scope_id,w.source_code,w.day FROM detections AS d
                   JOIN canonical_windows AS w ON w.id=d.window_id WHERE 1=1"""
        if sensor is not None:
            sql += " AND d.sensor=?"
            params.append(sensor)
        if satellite is not None:
            sql += " AND d.satellite=?"
            params.append(satellite)
        bbox_sql, bbox_params = _bbox_filter(bounds)
        sql += bbox_sql
        params += bbox_params
        sql += " ORDER BY d.observed_at,w.source_code,d.record_hash LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._connection() as conn:
            self._require_scope(conn, scope_id)
            result = []
            for row in conn.execute(sql, params):
                item = dict(row)
                item["id"] = f"{scope_id}:{item['source_code']}:{item['day']}:{item['record_hash']}"
                item["raw"] = json.loads(item.pop("raw_json"))
                result.append(item)
            return result

    def daily_counts(self, scope_id, start, end, *, bbox=None):
        _scope_id(scope_id)
        start_text, end_text = _period(start, end)
        bounds = _bbox_values(bbox)
        sql, params = _canonical_cte(scope_id, start_text, end_text)
        sql += """SELECT w.day,d.sensor,d.satellite,COUNT(*) AS count
                   FROM detections AS d JOIN canonical_windows AS w ON w.id=d.window_id
                   WHERE 1=1"""
        bbox_sql, bbox_params = _bbox_filter(bounds)
        sql += bbox_sql
        params += bbox_params
        sql += " GROUP BY w.day,d.sensor,d.satellite ORDER BY w.day,d.sensor,d.satellite"
        with self._connection() as conn:
            self._require_scope(conn, scope_id)
            return [dict(row) for row in conn.execute(sql, params)]

    def status(self, scope_id=None):
        if scope_id is not None:
            _scope_id(scope_id)
        where = " WHERE scope_id=?" if scope_id is not None else ""
        params = [scope_id] if scope_id is not None else []
        with self._connection() as conn:
            if scope_id is not None:
                self._require_scope(conn, scope_id)
            windows = {"total": 0, "loaded": 0, "pending": 0, "failed": 0}
            for row in conn.execute("SELECT status,COUNT(*) AS n FROM fetch_windows" + where + " GROUP BY status", params):
                windows[row["status"]] = row["n"]
                windows["total"] += row["n"]
            physical_sql = """SELECT COUNT(*) FROM detections AS d
                              JOIN fetch_windows AS w ON w.id=d.window_id"""
            if scope_id is not None:
                physical_sql += " WHERE w.scope_id=?"
            stored_rows = conn.execute(physical_sql, params).fetchone()[0]
            canonical_sql, canonical_params = _canonical_cte(scope_id)
            canonical_sql += "SELECT COUNT(*) FROM detections AS d JOIN canonical_windows AS w ON w.id=d.window_id"
            canonical_rows = conn.execute(canonical_sql, canonical_params).fetchone()[0]
            sources = [dict(row) for row in conn.execute(
                """SELECT source_code,
                   SUM(CASE WHEN status='loaded' THEN 1 ELSE 0 END) AS loaded_days,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_days,
                   SUM(row_count) AS row_count,MIN(day) AS first_day,MAX(day) AS last_day
                   FROM fetch_windows""" + where + " GROUP BY source_code ORDER BY source_code", params)]
            jobs = {row["status"]: row["n"] for row in conn.execute(
                "SELECT status,COUNT(*) AS n FROM sync_jobs" + where + " GROUP BY status", params)}
            return {"database": str(self.path), "scope_id": scope_id,
                    "scope_count": conn.execute("SELECT COUNT(*) FROM scopes").fetchone()[0],
                    "stored_rows": stored_rows, "canonical_rows": canonical_rows,
                    "windows": windows, "sources": sources, "jobs_by_status": jobs}
