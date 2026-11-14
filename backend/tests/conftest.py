"""
Shared fixtures for the tests.

The test database is built BY THE PARTNER'S CODE (parse_observations + replace_batch)
from CSV in the same format that NASA sends. The real database is not used
and is not modified.
"""

import csv
import importlib
import io
import math
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "data_pipeline"))  # the partner's module lives next to us

from fires_data.parsing import parse_observations  # noqa: E402
from fires_data.store import Store  # noqa: E402
from fires_data.types import FetchPayload, Scope  # noqa: E402

AUGUST = [date(2024, 8, 1) + timedelta(days=i) for i in range(31)]
NRT_ONLY_DAY = date(2024, 9, 1)     # near-real-time (NRT) data only
EMPTY_DAY = date(2024, 9, 2)        # MODIS loaded but 0 fires; VIIRS not loaded
SP_AND_NRT_DAY = date(2024, 8, 5)   # both SP and NRT exist — SP must win
SNPP_DAY = date(2024, 8, 10)        # S-NPP points — not part of the calendar
EDGE_DAY = date(2024, 8, 7)         # points exactly on grid lines


def _csv(rows, sensor):
    brightness = "brightness" if sensor == "MODIS" else "bright_ti4"
    fields = ["latitude", "longitude", brightness, "scan", "track", "acq_date", "acq_time",
              "satellite", "confidence", "version", "frp", "daynight"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({brightness: "321.5", "scan": "1.0", "track": "1.0",
                         "frp": "12.5", "daynight": "D", **row})
    return out.getvalue().encode("utf-8")


def save(store, source, day, points, satellite):
    """Write one daily slice the same way the partner's loader does it."""
    modis = source.startswith("MODIS")
    version = ("6.1" if modis else "2.0") + ("NRT" if source.endswith("_NRT") else "")
    rows = []
    for i, (lat, lon) in enumerate(points):
        rows.append({"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}",
                     "acq_date": day.isoformat(), "acq_time": f"{(i // 60) % 24:02d}{i % 60:02d}",
                     "satellite": satellite(i) if callable(satellite) else satellite,
                     "confidence": "80" if modis else "nominal", "version": version})
    body = _csv(rows, "MODIS" if modis else "VIIRS")
    scope = Scope.world()
    payload = FetchPayload(body, source, scope.id, day, day,
                           datetime(2024, 10, 1, tzinfo=timezone.utc), "redacted")
    store.replace_batch(scope, payload, parse_observations(body, source, scope, day, day))


def build_partner_db(path):
    rng = random.Random(42)
    store = Store(path)
    store.initialize()
    store.save_scope(Scope.world())

    for number, day in enumerate(AUGUST):
        # "Activity" varies by day, VIIRS sees roughly 3 times more cells
        activity = 25 + int(15 * math.sin(number / 3)) + rng.randint(0, 5)
        modis_points, viirs_points = [], []
        for _ in range(activity):
            lat, lon = rng.uniform(44.5, 52.5), rng.uniform(22.5, 40.5)      # Ukraine
            modis_points.append((lat, lon))
            modis_points.append((lat + 0.001, lon + 0.001))                   # the same cell
            for _ in range(3):
                viirs_points.append((lat + rng.uniform(-0.3, 0.3), lon + rng.uniform(-0.3, 0.3)))
        for _ in range(activity * 2):                                         # Africa
            lat, lon = rng.uniform(-15, -2), rng.uniform(14, 33)
            modis_points.append((lat, lon))
            viirs_points.append((lat, lon))
            viirs_points.append((lat + 0.2, lon - 0.2))
        if day == EDGE_DAY:
            edge = [(48.0, 22.0), (48.0, 41.0), (44.0, 30.0), (53.0, 30.0)]
            modis_points += edge
            viirs_points += edge
        save(store, "MODIS_SP", day, modis_points, lambda i: "T" if i % 2 else "A")
        save(store, "VIIRS_NOAA20_SP", day, viirs_points, "N20")

    # The same day in NRT with different points: SP must be the one that is read
    save(store, "MODIS_NRT", SP_AND_NRT_DAY, [(10.0, 10.0), (11.0, 11.0)], "T")
    # S-NPP points are not part of the VIIRS series (only NOAA-20 is)
    save(store, "VIIRS_SNPP_SP", SNPP_DAY, [(47.0, 30.0), (47.5, 30.5)], "N")
    # A day with NRT only
    save(store, "MODIS_NRT", NRT_ONLY_DAY, [(48.2, 31.3), (48.25, 31.35), (-5.0, 20.0)], "A")
    save(store, "VIIRS_NOAA20_NRT", NRT_ONLY_DAY, [(48.2, 31.3), (48.6, 31.9), (-5.0, 20.0)], "N20")
    # A loaded empty day
    save(store, "MODIS_SP", EMPTY_DAY, [], "T")
    return store


@pytest.fixture(scope="session")
def partner_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("partner") / "fires.sqlite3"
    build_partner_db(path)
    return path


@pytest.fixture(scope="session")
def app_env(partner_db, tmp_path_factory):
    """Set the environment variables and re-import the API modules."""
    os.environ["FIRMS_DB_PATH"] = str(partner_db)
    os.environ["FIRESYNC_INDEX_PATH"] = str(tmp_path_factory.mktemp("cache") / "grid_index.sqlite3")
    os.environ["FIRESYNC_AUTO_REFRESH"] = "0"
    modules = {}
    for name in ("config", "grid_index", "db", "analytics", "main"):
        if name in sys.modules:
            modules[name] = importlib.reload(sys.modules[name])
        else:
            modules[name] = importlib.import_module(name)
    result = modules["grid_index"].refresh()
    assert result["status"] == "ok", result
    return modules


@pytest.fixture(scope="session")
def client(app_env):
    from fastapi.testclient import TestClient
    with TestClient(app_env["main"].app) as test_client:
        yield test_client
