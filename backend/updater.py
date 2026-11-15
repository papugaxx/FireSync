"""
updater.py — AUTOMATIC NASA FIRMS UPDATES

The API starts this in the background (unless FIRESYNC_AUTO_UPDATE=0): about a
minute after start and then every FIRESYNC_UPDATE_HOURS hours (3 by default)
it asks NASA which dates exist and downloads only what the database lacks.

    python updater.py              # run one update now
    python updater.py --plan       # show what would be downloaded, download nothing
    python updater.py --status     # what is stored, what is still missing, the last update

Who is responsible for which dates
----------------------------------
* 2000–2025: the archive (importer.py). The API is never asked for these years.
* From FIRESYNC_UPDATE_START_DATE (2026-01-01) on — or from the day after the archive, if the
  archive reaches further: this updater. The first day is fixed, there is no moving window,
  so nothing is dropped when a new year begins and no code changes in 2027.

Rules
-----
* The NASA key is read from data_pipeline/.env (FIRMS_MAP_KEY). It never
  leaves the backend: it is not logged, stored or returned by the API.
* One request = one UTC day of one sensor (MODIS or VIIRS NOAA-20) for the
  whole world. The last week is downloaded first (newest day first), then every
  other missing day, oldest first — until no day is missing.
* Final science data (SP) is preferred. Where NASA only has near-real-time data
  (NRT, the last weeks/months), NRT is stored and later replaced by SP once
  NASA publishes it. NRT days younger than FIRESYNC_REFRESH_RECENT_DAYS are
  downloaded again, because NASA keeps adding satellite passes to them.
  Stored SP days — including the whole archive — are never downloaded again.
  A day and sensor is always one block that is replaced as a whole, so repeating
  a download or replacing NRT by SP can never count a detection twice.
* A whole-world day with zero detections is treated as "no data" (an instrument
  outage), not as a day without fires, and is not stored.
* Limits: requests per run, NASA quota reserve, response size, database size,
  free disk space. Reaching one — or a NASA / network failure — stops the run with a
  clear reason; everything stored so far is kept and the next run continues there
  after FIRESYNC_UPDATE_RETRY_MINUTES (10), not after the full interval.
* sync_state() / day_states() say for every day whether it is complete, partial,
  waiting for download or not offered by NASA yet — from the database alone,
  without asking NASA (the website calls them on every click).
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
from fires_data.types import Availability, Scope

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


def archive_end(conn, sensor):
    """Last day the imported archive holds for a sensor, or None without an archive."""
    row = conn.execute("SELECT MAX(day) FROM days WHERE sensor = ? AND origin = 'archive'", (sensor,)).fetchone()
    return date.fromisoformat(row[0]) if row[0] else None


def sync_start(conn, sensor):
    """
    First day this updater is responsible for: FIRESYNC_UPDATE_START_DATE, or the day after the
    archive if the archive reaches further. Never earlier — 2000–2025 is the archive's job, also
    when the archive is missing or only partly imported.
    """
    end = archive_end(conn, sensor)
    return max(config.UPDATE_START_DATE, end + timedelta(days=1)) if end else config.UPDATE_START_DATE


def _nasa_product(availability, sensor, day):
    """'SP' or 'NRT' — what NASA offers for that day — or None."""
    codes = SOURCES[sensor]
    return "SP" if _available(availability, codes["SP"], day) else (
        "NRT" if _available(availability, codes["NRT"], day) else None)


def plan(conn, availability, today=None, refresh_recent_days=None):
    """
    The list of downloads, each {"day", "sensor", "product", "source", "reason"}.
    reason: "missing" | "final_data" (NRT → SP) | "refresh" (recent NRT again).
    """
    today = today or today_utc()
    refresh_recent_days = config.UPDATE_REFRESH_RECENT_DAYS if refresh_recent_days is None else refresh_recent_days
    empty = json.loads(store.get_meta(conn, "empty_world_days") or "{}")
    tasks = []
    for sensor, codes in SOURCES.items():
        start = sync_start(conn, sensor)
        stored = {r["day"]: dict(r) for r in conn.execute(
            "SELECT day, product, loaded_at FROM days WHERE sensor = ? AND day >= ?", (sensor, start.isoformat()))}
        day = start
        while day <= today:
            text = day.isoformat()
            product = _nasa_product(availability, sensor, day)
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
# Synchronisation state (from the database only — NASA is not asked)
# ---------------------------------------------------------------------------
# State of one sensor on one day:
#   final        stored, final science data (SP)
#   preliminary  stored, near-real-time data (NRT); will be replaced by SP when NASA publishes it
#   updating     stored NRT of the last days: NASA is still adding satellite passes → partial
#   pending      NASA offers the day, it is not downloaded yet
#   unavailable  NASA does not offer the day (yet), or answered with an empty world
#   future       the day has not happened yet
#   no_data      a day of the archive years without data (instrument outage / before launch)
#   not_imported a day of the archive years while the archive has not been imported
# State of the day as a whole (DAY_STATUS):
#   complete | partial | pending | unavailable | no_data | not_imported | future

LOADED = ("final", "preliminary", "updating")


def _stored_availability(conn):
    """NASA's date ranges as saved by the last successful update: {code: (first, last)} or None."""
    raw = json.loads(store.get_meta(conn, "nasa_availability") or "null")
    if not raw:
        return None
    return {code: Availability(code, date.fromisoformat(a), date.fromisoformat(b)) for code, (a, b) in raw.items()}


def sensor_states(conn, start, end, today=None):
    """{sensor: {day text: state}} for every day of a period."""
    today = today or today_utc()
    availability = _stored_availability(conn)
    empty = json.loads(store.get_meta(conn, "empty_world_days") or "{}")
    stored = store.stored_days(conn, start, end)
    result = {}
    for sensor in store.SENSORS:
        first_api_day = sync_start(conn, sensor)
        has_archive = archive_end(conn, sensor) is not None
        states = result[sensor] = {}
        day = start
        while day <= end:
            text = day.isoformat()
            product = stored.get((text, sensor))
            if product == "SP":
                state = "final"
            elif product == "NRT":
                state = "updating" if (today - day).days < config.UPDATE_REFRESH_RECENT_DAYS else "preliminary"
            elif day > today:
                state = "future"
            elif day < first_api_day:
                state = "no_data" if has_archive else "not_imported"
            elif availability is None:
                state = "pending"                    # NASA has not been asked yet
            else:
                offered = _nasa_product(availability, sensor, day)
                answered_empty = offered and f"{sensor}:{text}:{offered}" in empty and (today - day).days > 7
                state = "pending" if offered and not answered_empty else "unavailable"
            states[text] = state
            day += timedelta(days=1)
    return result


def day_status(states):
    """The state of a whole day from the states of its sensors."""
    values = list(states)
    loaded = [v for v in values if v in LOADED]
    if loaded:
        # one sensor still to come (or NASA still adding passes) → partial;
        # a sensor without data in the archive years (outage) does not make a day partial
        if any(v in ("pending", "updating", "unavailable", "not_imported") for v in values):
            return "partial"
        return "complete"
    for name in ("pending", "unavailable", "not_imported", "future"):
        if name in values:
            return name
    return "no_data"


def day_states(conn, start, end, today=None):
    """{day text: {"status", "modis", "viirs"}} for every day of a period."""
    per_sensor = sensor_states(conn, start, end, today)
    return {day: {"status": day_status(per_sensor[s][day] for s in store.SENSORS),
                  **{store.CHANNEL[s]: per_sensor[s][day] for s in store.SENSORS}}
            for day in per_sensor[store.SENSORS[0]]}


def _ranges(days):
    """Sorted day texts → [[first, last], …] of consecutive runs."""
    result = []
    for text in days:
        day = date.fromisoformat(text)
        if result and date.fromisoformat(result[-1][1]) + timedelta(days=1) == day:
            result[-1][1] = text
        else:
            result.append([text, text])
    return result


def sync_state(conn, today=None):
    """
    Where the synchronisation with NASA stands, for the status endpoints: per sensor the first
    day the API is responsible for, how many days are in which state, and the missing date ranges.
    """
    today = today or today_utc()
    availability = _stored_availability(conn)
    sensors, first = {}, None
    for sensor in store.SENSORS:
        start = sync_start(conn, sensor)
        first = start if first is None else min(first, start)
        states = sensor_states(conn, start, today, today)[sensor] if start <= today else {}
        counts = {name: 0 for name in ("final", "preliminary", "updating", "pending", "unavailable")}
        for state in states.values():
            counts[state] += 1
        end = archive_end(conn, sensor)
        sensors[store.CHANNEL[sensor]] = {
            "archive_last_day": end.isoformat() if end else None,
            "api_first_day": start.isoformat(), "days": len(states), **counts,
            "pending_ranges": _ranges([d for d, v in states.items() if v == "pending"]),
            "unavailable_ranges": _ranges([d for d, v in states.items() if v == "unavailable"]),
            "nasa": None if availability is None else {
                kind: [availability[code].min_date.isoformat(), availability[code].max_date.isoformat()]
                for kind, code in SOURCES[sensor].items() if code in availability}}
    pending = sum(v["pending"] for v in sensors.values())
    days = day_states(conn, first, today, today) if first and first <= today else {}
    totals = {name: 0 for name in ("complete", "partial", "pending", "unavailable")}
    for item in days.values():
        totals[item["status"]] = totals.get(item["status"], 0) + 1
    last = json.loads(store.get_meta(conn, "last_update") or "null")
    return {"today": today.isoformat(), "from": first.isoformat() if first else None,
            "status": "never_synced" if availability is None else ("catching_up" if pending else "up_to_date"),
            "days": totals, "sensors": sensors, "pending_downloads": pending,
            "archive_imported": any(v["archive_last_day"] for v in sensors.values()),
            "nasa_availability_checked_at": store.get_meta(conn, "nasa_availability_checked_at"),
            "last_success_at": store.get_meta(conn, "last_success_at"),
            "last_complete_at": store.get_meta(conn, "last_complete_at"),
            "last_error": json.loads(store.get_meta(conn, "last_error") or "null"),
            "last_run": last}


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
    tasks = None
    summary["error"] = None
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
            except (ProtocolError, NetworkError) as error:
                # One bad or timed-out day is skipped (retried by the next run); several in a row
                # mean NASA or the network is down, so the run stops and resumes in a few minutes.
                summary["skipped_days"] += 1
                failures += 1
                if failures >= 3:
                    summary["stopped_because"] = ("NASA returned unexpected answers several times in a row."
                                                  if isinstance(error, ProtocolError) else _safe(error))
                    summary["error"] = type(error).__name__
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
            summary["remaining"] = summary["skipped_days"]      # skipped days are still to do
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
            if summary["remaining"] is None and tasks is not None:
                done = summary["days_written"] + summary["empty_world_days"]
                summary["remaining"] = max(0, len(tasks) - done)
            with conn:
                store.set_meta(conn, last_update=json.dumps(summary))
                if summary["error"]:
                    store.set_meta(conn, last_error=json.dumps({"at": summary["finished_at"],
                                                                "message": summary["stopped_because"]}))
                else:
                    store.set_meta(conn, last_success_at=summary["finished_at"], last_error="null")
                    if summary["remaining"] == 0:
                        store.set_meta(conn, last_complete_at=summary["finished_at"])
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
                # Work left over (request limit) or a failed run (NASA down, quota) → continue soon;
                # otherwise wait the normal interval. Nothing is lost either way: only stored days count.
                unfinished = result.get("remaining") != 0 or result.get("error")
                pause = config.UPDATE_RETRY_MINUTES * 60 if unfinished else config.UPDATE_EVERY_HOURS * 3600
            except Exception:
                traceback.print_exc(limit=3)
                pause = config.UPDATE_RETRY_MINUTES * 60
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
    parser.add_argument("--status", action="store_true", help="show what is stored, missing and the last update")
    parser.add_argument("--max-requests", type=int, default=None, help="NASA requests in this run")
    parser.add_argument("--until-done", action="store_true",
                        help="repeat runs (pausing FIRESYNC_UPDATE_RETRY_MINUTES after a failure) until nothing is missing")
    args = parser.parse_args(argv)
    print(f"Database: {store.db_path()}")
    if args.status:
        with closing(store.connect()) as conn:
            print(json.dumps({"stored": store.summary(conn), "sync": sync_state(conn), "update": status()}, indent=2))
        return 0
    if args.plan:
        key = _api_key()
        if not key:
            print("The NASA API key is not configured (data_pipeline/.env, FIRMS_MAP_KEY).")
            return 1
        client = FirmsClient(key, timeout=REQUEST_TIMEOUT)
        with closing(store.connect(create=True)) as conn:
            availability = client.availability()
            tasks = plan(conn, availability)
            for sensor, codes in SOURCES.items():
                end = archive_end(conn, sensor)
                nasa = ", ".join(f"{k} {availability[c].min_date}…{availability[c].max_date}"
                                 for k, c in codes.items() if c in availability)
                print(f"{sensor:5}  archive until {end or 'NOT IMPORTED'} · API from {sync_start(conn, sensor)}"
                      f" · NASA: {nasa}")
            if not any(archive_end(conn, s) for s in SOURCES):
                print("Note: this database has no archive days. 2000–2025 comes only from importer.py; "
                      "check FIRESYNC_DB_PATH if the archive was imported elsewhere.")
        print(f"{len(tasks)} downloads:")
        for t in tasks[:40]:
            print(f"  {t['day']}  {t['sensor']:5}  {t['product']:3}  {t['reason']}")
        if len(tasks) > 40:
            print(f"  … and {len(tasks) - 40} more")
        return 0
    ensure_region_tables()
    while True:
        result = run_once(max_requests=args.max_requests, log=print)
        print(json.dumps(result, indent=2))
        if not args.until_done or (result.get("remaining") == 0 and not result.get("error")):
            break
        if result.get("stopped_because") in ("Another update is already running.",) or not _api_key():
            break
        wait = config.UPDATE_RETRY_MINUTES * 60 if result.get("error") else 0
        print(f"{result.get('remaining')} downloads left; next run in {wait // 60:.0f} min.")
        time.sleep(wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
