"""
updater.py — AUTOMATIC NASA FIRMS UPDATES

The API starts this in the background (unless FIRESYNC_AUTO_UPDATE=0): about a
minute after start and then every FIRESYNC_UPDATE_HOURS hours (3 by default)
it asks NASA which dates exist and downloads only what the database lacks.

    python updater.py              # run one update now
    python updater.py --plan       # show what would be downloaded, download nothing
    python updater.py --status     # what is stored and what the last update did

Rules
-----
* The NASA key is read from data_pipeline/.env (FIRMS_MAP_KEY). It never
  leaves the backend: it is not logged, stored or returned by the API.
* One request = one UTC day of one sensor (MODIS or VIIRS NOAA-20) for the
  whole world. Missing days after the last stored day are downloaded, oldest
  first; the last few days are downloaded first so the newest data appears quickly.
* Final science data (SP) is preferred. Where NASA only has near-real-time data
  (NRT, the last weeks/months), NRT is stored and later replaced by SP once
  NASA publishes it. NRT days younger than FIRESYNC_REFRESH_RECENT_DAYS are
  downloaded again, because NASA keeps adding satellite passes to them.
  Stored SP days — including the whole archive — are never downloaded again.
* A whole-world day with zero detections is treated as "no data" (an instrument
  outage), not as a day without fires, and is not stored.
* Limits: requests per run, NASA quota reserve, response size, database size,
  free disk space. Reaching one stops the run with a clear reason; the next run
  continues where this one stopped.
"""

import argparse
import json
import shutil
import sys
import threading
import time
import traceback
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import numpy as np

import config
import store
from fires_data import FirmsClient, load_settings
from fires_data.errors import ConfigurationError, NetworkError, PipelineError, ProtocolError, QuotaError
from fires_data.parsing import parse_observations
from fires_data.types import Scope

try:  # one update at a time, also across processes (CLI + server)
    import fcntl
except ImportError:  # Windows
    fcntl = None

SOURCES = {"MODIS": {"SP": "MODIS_SP", "NRT": "MODIS_NRT"},
           "VIIRS": {"SP": "VIIRS_NOAA20_SP", "NRT": "VIIRS_NOAA20_NRT"}}
SATELLITE_INDEX = {name: i for i, name in enumerate(store.SATELLITES)}
REQUEST_TIMEOUT = 120


def today_utc():
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# What to download
# ---------------------------------------------------------------------------

def _available(availability, code, day):
    item = availability.get(code)
    return item is not None and item.min_date <= day <= item.max_date


def plan(conn, availability, today=None, max_backfill_days=None, refresh_recent_days=None):
    """
    The list of downloads, each {"day", "sensor", "product", "source", "reason"}.
    reason: "missing" | "final_data" (NRT → SP) | "refresh" (recent NRT again).
    """
    today = today or today_utc()
    max_backfill_days = max_backfill_days or config.UPDATE_MAX_BACKFILL_DAYS
    refresh_recent_days = config.UPDATE_REFRESH_RECENT_DAYS if refresh_recent_days is None else refresh_recent_days
    earliest = today - timedelta(days=max_backfill_days - 1)
    empty = json.loads(store.get_meta(conn, "empty_world_days") or "{}")
    tasks = []
    for sensor, codes in SOURCES.items():
        # Everything after the imported archive is the updater's job; days inside the
        # archive that have no data are instrument outages and are not asked again.
        archive_end = conn.execute("SELECT MAX(day) FROM days WHERE sensor = ? AND origin = 'archive'",
                                   (sensor,)).fetchone()[0]
        start = date.fromisoformat(archive_end) + timedelta(days=1) if archive_end else earliest
        start = max(start, earliest)
        stored = {r["day"]: dict(r) for r in conn.execute(
            "SELECT day, product, loaded_at FROM days WHERE sensor = ? AND day >= ?", (sensor, start.isoformat()))}
        day = start
        while day <= today:
            text = day.isoformat()
            product = "SP" if _available(availability, codes["SP"], day) else (
                "NRT" if _available(availability, codes["NRT"], day) else None)
            have = stored.get(text)
            reason = None
            if product is None:
                pass
            elif have is None:
                checked = empty.get(f"{sensor}:{text}:{product}")
                # Empty whole-world answers are asked again only while the day is recent.
                if checked is None or (today - day).days <= 7:
                    reason = "missing"
            elif have["product"] == "NRT" and product == "SP":
                reason = "final_data"
            elif have["product"] == "NRT" and (today - day).days < refresh_recent_days:
                reason = "refresh"
            if reason:
                tasks.append({"day": text, "sensor": sensor, "product": product,
                              "source": codes[product], "reason": reason})
            day += timedelta(days=1)
    # The last week first, newest day first (new fires appear quickly), then the rest oldest first.
    cutoff = (today - timedelta(days=7)).isoformat()
    recent = sorted((t for t in tasks if t["day"] >= cutoff), key=lambda t: t["day"], reverse=True)
    older = sorted((t for t in tasks if t["day"] < cutoff), key=lambda t: t["day"])
    return recent + older


# ---------------------------------------------------------------------------
# NASA rows → stored columns
# ---------------------------------------------------------------------------

def _scaled(value, factor, missing):
    return missing if value is None else int(round(value * factor))


def observations_to_columns(observations, sensor):
    """Validated partner Observation objects → the column arrays of store.write_day."""
    cols = {name: [] for name in store.COLUMNS}
    versions = []
    second = "bright_t31" if sensor == "MODIS" else "bright_ti5"
    for o in observations:
        raw = o.raw
        cols["lat"].append(int(round(o.latitude * 100000)))
        cols["lon"].append(int(round(o.longitude * 100000)))
        cols["time"].append(o.observed_at.hour * 100 + o.observed_at.minute)
        cols["frp"].append(_scaled(o.frp_mw, 100, 0xFFFFFFFF))
        cols["bright"].append(_scaled(o.brightness_k, 100, 0xFFFFFFFF))
        text = (raw.get(second) or "").strip()
        cols["bright2"].append(_scaled(float(text), 100, 0xFFFFFFFF) if text else 0xFFFFFFFF)
        cols["scan"].append(_scaled(o.scan_km, 100, 0xFFFF))
        cols["track"].append(_scaled(o.track_km, 100, 0xFFFF))
        conf = o.confidence_raw
        if conf is None:
            cols["confidence"].append(255)
        elif sensor == "MODIS":
            cols["confidence"].append(int(round(float(conf))))
        else:
            cols["confidence"].append(store.VIIRS_CONFIDENCE.get(conf.lower(), 255))
        cols["satellite"].append(SATELLITE_INDEX[o.satellite])
        cols["daynight"].append({"D": 1, "N": 2}.get(o.daynight, 0))
        cols["type"].append(255 if o.type_code is None else o.type_code)
        if o.product_version not in versions:
            versions.append(o.product_version)
        cols["version"].append(versions.index(o.product_version))
    columns = {name: np.array(values, dtype=store.COLUMNS[name][0]) if values
               else np.zeros(0, dtype=store.COLUMNS[name][0]) for name, values in cols.items()}
    if max((int(v) for v in columns["bright"] if v != 0xFFFFFFFF), default=0) > 0xFFFFFFF0:
        raise ProtocolError("A brightness value is out of range.")
    return columns, versions


# ---------------------------------------------------------------------------
# One update run
# ---------------------------------------------------------------------------

_status_lock = threading.Lock()
_status = {"state": "idle", "enabled": False, "started_at": None, "finished_at": None, "next_run_at": None,
           "requests": 0, "days_written": 0, "remaining": None, "message": "No update has run yet.",
           "error": None, "last_days": []}


def status():
    with _status_lock:
        result = dict(_status)
    try:
        with closing(store.connect()) as conn:
            saved = json.loads(store.get_meta(conn, "last_update") or "null")
    except store.StoreNotReady:
        saved = None
    result["last_completed_run"] = saved
    result["api_key_configured"] = bool(_api_key())
    return result


def _set_status(**values):
    with _status_lock:
        _status.update(values)


def _api_key():
    try:
        return load_settings().api_key
    except PipelineError:
        return ""


def _safe(error):
    """Fixed, key-free explanations for the status page."""
    if isinstance(error, QuotaError):
        return "NASA quota or rate limit reached. The next run continues after the quota resets."
    if isinstance(error, ConfigurationError):
        return "The NASA API key is missing or invalid (data_pipeline/.env, FIRMS_MAP_KEY)."
    if isinstance(error, NetworkError):
        return "NASA FIRMS could not be reached or refused the request. Stored data is unchanged; the next run retries."
    if isinstance(error, ProtocolError):
        return "NASA returned an unexpected answer for one day; it was skipped and will be retried."
    return "The update stopped unexpectedly. Stored data is unchanged; the next run retries."


class _RunLock:
    """One update at a time: a thread lock plus a file lock (CLI and server at once)."""

    def __init__(self):
        self.handle, self.acquired = None, False

    def acquire(self):
        if not _thread_lock.acquire(blocking=False):
            return False
        if fcntl is not None:
            path = store.db_path().with_name(store.db_path().name + ".update.lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(path, "w")
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.handle.close()
                self.handle = None
                _thread_lock.release()
                return False
        self.acquired = True
        return True

    def release(self):
        if self.handle:
            self.handle.close()     # closing the file releases the flock
            self.handle = None
        if self.acquired:
            self.acquired = False
            _thread_lock.release()


_thread_lock = threading.Lock()


def run_once(client_factory=FirmsClient, key=None, max_requests=None, sleep=time.sleep, today=None, log=None):
    """
    Download what is missing, within the limits. Returns a summary dict.
    Safe to call while the API serves requests (readers are never blocked).
    """
    log = log or (lambda *_: None)
    key = key if key is not None else _api_key()
    max_requests = max_requests or config.UPDATE_MAX_REQUESTS
    summary = {"started_at": store.utc_now_text(), "requests": 0, "days_written": 0, "upgraded_to_sp": 0,
               "refreshed": 0, "empty_world_days": 0, "skipped_days": 0, "stopped_because": None,
               "remaining": None, "transferred_mb": 0.0}
    if not key:
        summary["stopped_because"] = "The NASA API key is not configured (data_pipeline/.env, FIRMS_MAP_KEY)."
        _set_status(state="idle", message=summary["stopped_because"], error=summary["stopped_because"])
        return summary
    lock = _RunLock()
    if not lock.acquire():
        summary["stopped_because"] = "Another update is already running."
        return summary
    _set_status(state="running", started_at=summary["started_at"], requests=0, days_written=0, error=None,
                message="Asking NASA which dates are available.", last_days=[])
    conn = store.connect(create=True)
    touched = set()
    transferred = 0
    try:
        client = client_factory(key, timeout=REQUEST_TIMEOUT,
                                max_response_bytes=config.UPDATE_MAX_RESPONSE_MB * 1024 ** 2, retries=2)
        _check_quota(client)
        availability = client.availability()
        summary["requests"] += 1
        with conn:
            store.set_meta(conn, nasa_availability=json.dumps(
                {code: [a.min_date.isoformat(), a.max_date.isoformat()] for code, a in availability.items()
                 if code in {c for codes in SOURCES.values() for c in codes.values()}}),
                nasa_availability_checked_at=store.utc_now_text())
        tasks = plan(conn, availability, today=today)
        log(f"{len(tasks)} day downloads planned.")
        failures = 0
        for number, task in enumerate(tasks):
            if summary["requests"] >= max_requests:
                summary["stopped_because"] = (f"Request limit for one run reached ({max_requests}). "
                                              "The next run continues.")
                break
            reason = _limits_reached()
            if reason:
                summary["stopped_because"] = reason
                break
            if summary["requests"] and summary["requests"] % 25 == 0:
                _check_quota(client)
            if summary["requests"] and config.UPDATE_REQUEST_INTERVAL:
                sleep(config.UPDATE_REQUEST_INTERVAL)
            day = date.fromisoformat(task["day"])
            _set_status(message=f"Downloading {task['sensor']} {task['product']} for {task['day']} "
                                f"({number + 1} of {len(tasks)}).", remaining=len(tasks) - number)
            try:
                payload = client.fetch_area(Scope.world(), task["source"], day, day)
                summary["requests"] += 1
                transferred += len(payload.body)
                observations = list(parse_observations(payload.body, task["source"], Scope.world(), day, day))
                columns, versions = observations_to_columns(observations, task["sensor"])
            except ProtocolError:
                summary["skipped_days"] += 1
                failures += 1
                if failures >= 3:
                    summary["stopped_because"] = "NASA returned unexpected answers several times in a row."
                    break
                continue
            failures = 0
            if not len(columns["lat"]):
                summary["empty_world_days"] += 1
                empty = json.loads(store.get_meta(conn, "empty_world_days") or "{}")
                empty[f"{task['sensor']}:{task['day']}:{task['product']}"] = store.utc_now_text()
                with conn:
                    store.set_meta(conn, empty_world_days=json.dumps(empty))
                continue
            with store.writer_lock(), conn:
                existing = store.stored_day(conn, task["day"], task["sensor"])
                if existing and store.PRODUCT_RANK[existing["product"]] > store.PRODUCT_RANK[task["product"]]:
                    continue   # SP arrived meanwhile (e.g. from the archive): never replace it with NRT
                store.write_day(conn, task["day"], task["sensor"], task["product"], "api", columns, versions)
            summary["days_written"] += 1
            summary["upgraded_to_sp"] += task["reason"] == "final_data"
            summary["refreshed"] += task["reason"] == "refresh"
            touched.add(task["day"][:7])
            _set_status(requests=summary["requests"], days_written=summary["days_written"],
                        last_days=([f"{task['day']} {task['sensor']} {task['product']}"] + _status["last_days"])[:10])
            if len(touched) >= 3 or summary["days_written"] % 20 == 0:
                _publish(conn, touched)
        else:
            summary["remaining"] = 0
        if summary["remaining"] is None:
            done = summary["days_written"] + summary["skipped_days"] + summary["empty_world_days"]
            summary["remaining"] = max(0, len(tasks) - done)
    except Exception as error:   # the background thread must survive anything
        summary["stopped_because"] = _safe(error)
        summary["error"] = type(error).__name__
        if not isinstance(error, PipelineError):
            traceback.print_exc(limit=3)
    finally:
        try:
            _publish(conn, touched)
            summary["transferred_mb"] = round(transferred / 1024 ** 2, 1)
            summary["finished_at"] = store.utc_now_text()
            with conn:
                store.set_meta(conn, last_update=json.dumps(summary))
        finally:
            conn.close()
            lock.release()
        _set_status(state="idle", finished_at=summary.get("finished_at"), requests=summary["requests"],
                    days_written=summary["days_written"], remaining=summary["remaining"],
                    error=summary.get("error"),
                    message=summary["stopped_because"] or "Up to date with NASA FIRMS.")
    return summary


def _publish(conn, months):
    """Rebuild the region tables of changed months so the API shows the new days."""
    if months:
        with store.writer_lock():
            store.rebuild_months(conn, months)
        months.clear()


def _check_quota(client):
    quota = client.quota_status()
    if int(quota["transaction_limit"]) - int(quota["current_transactions"]) <= config.UPDATE_QUOTA_RESERVE:
        raise QuotaError("NASA transaction reserve reached.")


def _limits_reached():
    path = store.db_path()
    size = sum(p.stat().st_size for p in (path, path.with_name(path.name + "-wal")) if p.is_file())
    if size >= config.UPDATE_MAX_DB_GB * 1024 ** 3:
        return f"The database reached its size limit ({config.UPDATE_MAX_DB_GB} GB, FIRESYNC_MAX_DB_GB)."
    if shutil.disk_usage(path.parent).free < config.UPDATE_MIN_FREE_GB * 1024 ** 3:
        return f"Less than {config.UPDATE_MIN_FREE_GB} GB of free disk space (FIRESYNC_MIN_FREE_GB)."
    return None


# ---------------------------------------------------------------------------
# Background schedule (started by main.py)
# ---------------------------------------------------------------------------

_started = False


def start_background(first_delay_seconds=60):
    """
    Daemon threads; the API keeps serving meanwhile:
    region tables are rebuilt right away if config.REGIONS changed, then update follows update.
    """
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_region_check, name="region-tables", daemon=True).start()
    if not config.AUTO_UPDATE:
        _set_status(enabled=False, message="Automatic updates are off (FIRESYNC_AUTO_UPDATE=0).")
        return
    _set_status(enabled=True, next_run_at=_in(first_delay_seconds), message="The first update starts soon.")

    def loop():
        time.sleep(first_delay_seconds)
        while True:
            try:
                ensure_region_tables()
                result = run_once()
                # Work left over (request limit) → continue soon, otherwise wait the normal interval.
                pause = 600 if result.get("remaining") else config.UPDATE_EVERY_HOURS * 3600
            except Exception:
                traceback.print_exc(limit=3)
                pause = config.UPDATE_EVERY_HOURS * 3600
            _set_status(next_run_at=_in(pause))
            time.sleep(pause)

    threading.Thread(target=loop, name="nasa-firms-updater", daemon=True).start()


def _region_check():
    try:
        ensure_region_tables()
    except Exception:
        traceback.print_exc(limit=3)


def ensure_region_tables():
    """If config.REGIONS changed since the tables were built, rebuild them (a few minutes)."""
    try:
        conn = store.connect()
    except store.StoreNotReady:
        return
    with closing(conn), store.writer_lock():
        if store.get_meta(conn, "regions_signature") != store.regions_signature() and store.all_months(conn):
            _set_status(state="running", message="Rebuilding the region tables after a change of config.REGIONS.")
            store.rebuild_months(conn, store.all_months(conn))
            _set_status(state="idle", message="Region tables rebuilt.")


def _in(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download new NASA FIRMS data into the FireSync database.")
    parser.add_argument("--plan", action="store_true", help="show what would be downloaded")
    parser.add_argument("--status", action="store_true", help="show what is stored and the last update")
    parser.add_argument("--max-requests", type=int, default=None, help="NASA requests in this run")
    args = parser.parse_args(argv)
    if args.status:
        with closing(store.connect()) as conn:
            print(json.dumps({"stored": store.summary(conn), "update": status()}, indent=2))
        return 0
    if args.plan:
        key = _api_key()
        if not key:
            print("The NASA API key is not configured (data_pipeline/.env, FIRMS_MAP_KEY).")
            return 1
        client = FirmsClient(key, timeout=REQUEST_TIMEOUT)
        with closing(store.connect(create=True)) as conn:
            tasks = plan(conn, client.availability())
        print(f"{len(tasks)} downloads:")
        for t in tasks[:40]:
            print(f"  {t['day']}  {t['sensor']:5}  {t['product']:3}  {t['reason']}")
        if len(tasks) > 40:
            print(f"  … and {len(tasks) - 40} more")
        return 0
    ensure_region_tables()
    result = run_once(max_requests=args.max_requests, log=print)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
