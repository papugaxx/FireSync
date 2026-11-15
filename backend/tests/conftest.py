"""
Shared fixtures for the tests.

A small archive CSV in exactly the format of NASA_FIRMS_2000_2025.csv is generated
(rows of one year deliberately shuffled, like the real export), imported with
importer.py into a temporary database, and served by the real FastAPI app.
The real database and the real CSV are never used or changed.
"""

import importlib
import math
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "data_pipeline"))  # the partner's module lives next to us

HEADER = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,"
          "version,bright_t31,frp,daynight,type,bright_ti4,bright_ti5,source_product")
AUGUST = [date(2024, 8, 1) + timedelta(days=i) for i in range(31)]
HISTORY_YEARS = (2021, 2022, 2023)       # complete MODIS Augusts for the median / anomaly
MODIS_ONLY_DAY = date(2024, 9, 2)        # MODIS stored, VIIRS missing
QUIET_UKRAINE_DAY = date(2024, 8, 20)    # data worldwide, but no fire inside Ukraine → measured zero
SP_AND_NRT_DAY = date(2024, 8, 5)        # extra NRT rows for an SP day — must be dropped
SNPP_DAY = date(2024, 8, 10)             # S-NPP rows — not part of FireSync
EDGE_DAY = date(2024, 8, 7)              # points exactly on grid lines
UKRAINE = (22.1, 44.3, 40.2, 52.4)       # config.REGIONS["ukraine"]


def _row(lat, lon, day, hhmm, sensor, satellite, frp, version=None, confidence=None, kind="0"):
    if sensor == "MODIS":
        return (f"{lat:.4f},{lon:.4f},321.5,1.2,1.1,{day},{hhmm:04d},{satellite},MODIS,"
                f"{confidence or 70},{version or '6.1'},298.4,{frp},D,{kind},,,MODIS")
    source = "VIIRS_SNPP" if satellite == "N" else "VIIRS_NOAA20"
    return (f"{lat:.5f},{lon:.5f},,0.45,0.39,{day},{hhmm:04d},{satellite},VIIRS,{confidence or 'n'},"
            f"{version or '2'},,{frp},N,{kind},330.12,291.07,{source}")


def make_archive(path):
    """Write the test archive. Returns the list of kept rows as dicts (the expected content)."""
    rng = random.Random(7)
    modis, viirs, snpp, kept = [], [], [], []

    def add(target, lat, lon, day, sensor, satellite, frp, **extra):
        hhmm = rng.randint(0, 23) * 100 + rng.randint(0, 59)
        target.append(_row(lat, lon, day, hhmm, sensor, satellite, frp, **extra))
        if extra.get("version", "").endswith("NRT") or satellite == "N":
            return
        kept.append({"day": day.isoformat(), "sensor": sensor, "lat": lat, "lon": lon,
                     "frp": None if frp == "" else float(frp)})

    def frp_value():
        return "" if rng.random() < 0.05 else f"{rng.uniform(1, 400):.1f}"

    for day in AUGUST + [MODIS_ONLY_DAY] + [date(y, 8, d) for y in HISTORY_YEARS for d in range(1, 32)]:
        quiet = day == QUIET_UKRAINE_DAY
        burst = 1 + math.sin(day.toordinal() / 3) ** 2
        for _ in range(int(12 * burst)):
            if not quiet:
                lat, lon = round(rng.uniform(44.8, 52.0), 4), round(rng.uniform(22.6, 39.8), 4)
                add(modis, lat, lon, day, "MODIS", rng.choice(["Terra", "Aqua"]), frp_value())
                add(modis, round(lat + 0.0007, 4), round(lon + 0.0007, 4), day, "MODIS", "Aqua", frp_value())
                if day.year == 2024 and day != MODIS_ONLY_DAY:
                    for _ in range(3):
                        add(viirs, round(lat + rng.uniform(-0.3, 0.3), 5), round(lon + rng.uniform(-0.3, 0.3), 5),
                            day, "VIIRS", "N20", frp_value())
            lat, lon = round(rng.uniform(-15, -2), 4), round(rng.uniform(14, 33), 4)   # Africa
            add(modis, lat, lon, day, "MODIS", "Terra", frp_value())
            if day.year == 2024 and day != MODIS_ONLY_DAY:
                add(viirs, round(lat + 0.2, 5), round(lon - 0.2, 5), day, "VIIRS", "N20", frp_value())
        if day == EDGE_DAY:
            for lat, lon in ((48.0, 30.0), (46.0, 35.0)):
                add(modis, lat, lon, day, "MODIS", "Terra", "12.5")
                add(viirs, lat, lon, day, "VIIRS", "N20", "3.25")
    # NRT duplicates of an SP day and S-NPP rows: present in the file, never stored
    for _ in range(5):
        add(modis, 10.0, 10.0, SP_AND_NRT_DAY, "MODIS", "T", "50.0", version="6.1NRT")
        add(snpp, 47.0, 30.0, SNPP_DAY, "VIIRS", "N", "9.9")
    # the real export: blocks by source and year, rows inside a year in no particular order
    lines = []
    for block in (modis, snpp, viirs):
        years = {}
        for line in block:
            years.setdefault(line.split(",")[5][:4], []).append(line)
        for year in sorted(years):
            rng.shuffle(years[year])
            lines += years[year]
    Path(path).write_text(HEADER + "\n" + "\n".join(lines) + "\n")
    return kept


def partner_cell(lat, lon):
    """The partner's cell formula (GRID_METHOD.md), written independently of store.py."""
    y = min(1799, (round(lat * 10_000_000) + 900_000_000) // 1_000_000)
    x = min(3599, (round(lon * 10_000_000) + 1_800_000_000) // 1_000_000)
    return y, x


@pytest.fixture(scope="session")
def archive(tmp_path_factory):
    folder = tmp_path_factory.mktemp("archive")
    path = folder / "NASA_FIRMS_test.csv"
    rows = make_archive(path)
    return {"path": path, "rows": rows, "folder": folder}


@pytest.fixture(scope="session")
def app_env(archive, tmp_path_factory):
    """Import the test archive into a temporary database and (re)load the API modules against it."""
    db = tmp_path_factory.mktemp("db") / "firesync.sqlite3"
    os.environ["FIRESYNC_DB_PATH"] = str(db)
    os.environ["FIRESYNC_AUTO_UPDATE"] = "0"
    modules = {}
    for name in ("config", "store", "reports", "analytics", "importer", "updater", "frontend_api", "main"):
        modules[name] = importlib.reload(sys.modules[name]) if name in sys.modules else importlib.import_module(name)
    report = modules["importer"].run(archive["path"], workers=2, db=db, log=lambda *a, **k: None,
                                     chunk_bytes=4096, segment_bytes=16384)
    assert report["status"] == "completed", report
    modules["report"] = report
    modules["db"] = db
    return modules


@pytest.fixture(scope="session")
def client(app_env):
    from fastapi.testclient import TestClient
    with TestClient(app_env["main"].app) as test_client:
        yield test_client
