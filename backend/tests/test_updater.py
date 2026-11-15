"""Automatic NASA updates with a fake FIRMS client: never the real API, never a real key."""

import json
import shutil
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import pytest

from fires_data.errors import NetworkError
from fires_data.types import Availability, FetchPayload

TODAY = date(2024, 9, 10)          # "today" inside the test world: the archive ends on 2024-09-02
MODIS_HEADER = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight"
VIIRS_HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight"


class FakeFirms:
    """Answers like NASA FIRMS: SP until 2024-09-05, NRT afterwards."""
    sp_until = date(2024, 9, 5)
    empty_days = set()
    broken_days = set()
    quota_left = 5000
    instances = []

    def __init__(self, key, **kwargs):
        assert key == "test-key-not-real"
        self.calls = []
        FakeFirms.instances.append(self)

    def quota_status(self):
        return {"transaction_limit": 5000, "current_transactions": 5000 - self.quota_left, "transaction_interval": "10 minutes"}

    def availability(self):
        first = date(2000, 11, 1)
        nrt_from = self.sp_until + timedelta(days=1)
        return {"MODIS_SP": Availability("MODIS_SP", first, self.sp_until),
                "MODIS_NRT": Availability("MODIS_NRT", nrt_from, TODAY),
                "VIIRS_NOAA20_SP": Availability("VIIRS_NOAA20_SP", date(2018, 4, 1), self.sp_until),
                "VIIRS_NOAA20_NRT": Availability("VIIRS_NOAA20_NRT", nrt_from, TODAY)}

    def fetch_area(self, scope, source, start, end):
        assert scope.id == "world" and start == end
        self.calls.append((source, start))
        day = start.isoformat()
        nrt = source.endswith("NRT")
        if (source, start) in self.broken_days:
            return FetchPayload(b"<html>error</html>", source, "world", start, end, datetime.now(timezone.utc), "x")
        if source.startswith("MODIS"):
            lines = [MODIS_HEADER] + ([] if (source, start) in self.empty_days else [
                f"48.1234,30.5678,320.1,1.1,1.0,{day},1030,{'T' if nrt else 'Terra'},MODIS,80,"
                f"{'6.1NRT' if nrt else '6.1'},290.0,25.5,D",
                f"-10.5,20.25,330.0,1.0,1.0,{day},1100,{'A' if nrt else 'Aqua'},MODIS,90,"
                f"{'6.1NRT' if nrt else '6.1'},291.0,,D"])
        else:
            lines = [VIIRS_HEADER] + ([] if (source, start) in self.empty_days else [
                f"48.12345,30.56789,330.5,0.4,0.4,{day},1031,N20,VIIRS,n,{'2.0NRT' if nrt else '2'},290.5,3.75,D"])
        return FetchPayload(("\n".join(lines) + "\n").encode(), source, "world", start, end,
                            datetime.now(timezone.utc), "redacted")


@pytest.fixture
def fresh(app_env, tmp_path, monkeypatch):
    """A private copy of the test database, so updates do not change other tests."""
    db = tmp_path / "copy.sqlite3"
    shutil.copy(app_env["db"], db)
    monkeypatch.setattr(app_env["config"], "STORE_PATH", db)
    monkeypatch.setattr(app_env["config"], "UPDATE_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(app_env["config"], "UPDATE_MIN_FREE_GB", 0)
    FakeFirms.instances, FakeFirms.empty_days, FakeFirms.broken_days = [], set(), set()
    FakeFirms.sp_until, FakeFirms.quota_left = date(2024, 9, 5), 5000
    updater, store = app_env["updater"], app_env["store"]

    def run(**kwargs):
        return updater.run_once(client_factory=FakeFirms, key="test-key-not-real", sleep=lambda s: None,
                                today=TODAY, **kwargs)
    return updater, store, run, db


def _days(store, db, sensor):
    with closing(store.connect(db)) as conn:
        return {r["day"]: dict(r) for r in conn.execute(
            "SELECT day, product, origin, observations FROM days WHERE sensor = ? AND day > '2024-08-31'", (sensor,))}


def test_plan_starts_after_the_archive_and_picks_sp_or_nrt(fresh):
    updater, store, _, db = fresh
    with closing(store.connect(db)) as conn:
        tasks = updater.plan(conn, FakeFirms("test-key-not-real").availability(), today=TODAY)
    modis = {t["day"]: t for t in tasks if t["sensor"] == "MODIS"}
    viirs = {t["day"]: t for t in tasks if t["sensor"] == "VIIRS"}
    assert min(modis) == "2024-09-03" and max(modis) == TODAY.isoformat()   # MODIS archive ends 2024-09-02
    assert min(viirs) == "2024-09-01"                                          # VIIRS archive ends 2024-08-31
    assert modis["2024-09-05"]["product"] == "SP" and modis["2024-09-06"]["product"] == "NRT"
    assert "2024-08-15" not in modis                                           # archive days are never asked again
    assert tasks[0]["day"] == TODAY.isoformat()                                # newest week first


def test_update_stores_new_days_and_publishes_them(fresh):
    updater, store, run, db = fresh
    result = run()
    assert result["stopped_because"] is None and result["remaining"] == 0
    modis, viirs = _days(store, db, "MODIS"), _days(store, db, "VIIRS")
    assert modis["2024-09-05"]["product"] == "SP" and modis["2024-09-06"]["product"] == "NRT"
    assert modis["2024-09-06"]["origin"] == "api" and modis["2024-09-06"]["observations"] == 2
    assert set(viirs) == {(date(2024, 9, 1) + timedelta(days=i)).isoformat() for i in range(10)}
    with closing(store.connect(db)) as conn:
        point = [p for p in store.detections(conn, "2024-09-06", "MODIS") if p["frp_mw"] is None]
        assert point and point[0]["satellite"] == "Aqua" and point[0]["version"] == "6.1NRT"
        row = store.region_day_rows(conn, "ukraine", "2024-09-06", "2024-09-06")["2024-09-06"]
        assert row["modis_cells"] == 1 and row["viirs_cells"] == 1 and row["shared_cells"] == 1
        assert row["modis_product"] == "NRT"
    # nothing left: a second run downloads only the recent NRT days again
    FakeFirms.instances.clear()
    again = run()
    sources = FakeFirms.instances[0].calls
    assert again["days_written"] == len(sources) == 4                # 2 recent days × 2 sensors
    assert {d for _, d in sources} == {TODAY, TODAY - timedelta(days=1)}


def test_nrt_is_replaced_by_sp_but_sp_never_by_nrt(fresh):
    updater, store, run, db = fresh
    run()
    FakeFirms.sp_until = date(2024, 9, 8)          # NASA has published final data for three more days
    FakeFirms.instances.clear()
    result = run()
    assert result["upgraded_to_sp"] == 6
    modis = _days(store, db, "MODIS")
    assert modis["2024-09-08"]["product"] == "SP" and modis["2024-09-09"]["product"] == "NRT"
    calls = FakeFirms.instances[0].calls
    assert not [c for c in calls if c[0].endswith("_SP") and c[1] <= date(2024, 9, 5)]   # stored SP not asked again


def test_empty_world_day_is_not_a_zero(fresh):
    updater, store, run, db = fresh
    FakeFirms.empty_days = {("MODIS_SP", date(2024, 9, 4))}
    result = run()
    assert result["empty_world_days"] == 1
    assert "2024-09-04" not in _days(store, db, "MODIS")


def test_limits_stop_the_run_and_the_next_run_continues(fresh):
    updater, store, run, db = fresh
    first = run(max_requests=5)
    assert "Request limit" in first["stopped_because"] and first["remaining"] > 0
    stored = [d for s in ("MODIS", "VIIRS") for d in _days(store, db, s).values() if d["origin"] == "api"]
    assert len(stored) == 4                              # availability + 4 day downloads
    second = run()
    assert second["remaining"] == 0
    FakeFirms.quota_left = 10
    blocked = run()
    assert "quota" in blocked["stopped_because"].lower() and blocked["days_written"] == 0


def test_a_bad_answer_skips_one_day_only(fresh):
    updater, store, run, db = fresh
    FakeFirms.broken_days = {("MODIS_SP", date(2024, 9, 3))}
    result = run()
    assert result["skipped_days"] == 1 and "2024-09-03" not in _days(store, db, "MODIS")
    assert "2024-09-04" in _days(store, db, "MODIS")
    FakeFirms.broken_days = set()
    run()
    assert "2024-09-03" in _days(store, db, "MODIS")      # retried by the next run


def test_no_key_no_requests_and_no_secret_in_status(fresh, monkeypatch):
    updater, store, run, db = fresh
    result = updater.run_once(client_factory=FakeFirms, key="", today=TODAY)
    assert "not configured" in result["stopped_because"] and not FakeFirms.instances

    class Down(FakeFirms):
        def availability(self):
            raise NetworkError("NASA request failed with https://firms.example/api/test-key-not-real/")
    failed = updater.run_once(client_factory=Down, key="test-key-not-real", today=TODAY, sleep=lambda s: None)
    text = json.dumps(failed) + json.dumps(updater.status())
    assert "test-key-not-real" not in text and "https://" not in text
    assert "could not be reached" in failed["stopped_because"]


def test_only_one_update_at_a_time(fresh):
    updater, store, run, db = fresh
    lock = updater._RunLock()
    assert lock.acquire()
    try:
        assert run()["stopped_because"] == "Another update is already running."
    finally:
        lock.release()
    assert run()["stopped_because"] is None


def test_archive_import_replaces_api_nrt_with_sp(fresh, app_env, tmp_path):
    updater, store, run, db = fresh
    run()
    assert _days(store, db, "MODIS")["2024-09-07"]["product"] == "NRT"
    csv = tmp_path / "late.csv"
    csv.write_text("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,"
                   "version,bright_t31,frp,daynight,type,bright_ti4,bright_ti5,source_product\n"
                   "1.5,2.5,300.0,1.0,1.0,2024-09-07,0100,Terra,MODIS,50,6.1,280.0,4.0,D,0,,,MODIS\n")
    app_env["importer"].run(csv, workers=1, db=db, log=lambda *a, **k: None)
    day = _days(store, db, "MODIS")["2024-09-07"]
    assert day["product"] == "SP" and day["origin"] == "archive" and day["observations"] == 1


def test_new_region_in_config_gets_its_tables(fresh, app_env, monkeypatch):
    updater, store, run, db = fresh
    regions = dict(app_env["config"].REGIONS)
    regions["kyiv_area"] = {"name": "Kyiv area", "bbox": [29.0, 49.0, 32.0, 52.0]}
    monkeypatch.setattr(app_env["config"], "REGIONS", regions)
    updater.ensure_region_tables()
    with closing(store.connect(db)) as conn:
        rows = store.region_day_rows(conn, "kyiv_area", "2024-08-01", "2024-08-31")
        assert len(rows) == 31 and store.get_meta(conn, "regions_signature") == store.regions_signature()
