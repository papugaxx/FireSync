"""
Общие заготовки для тестов.

Тестовая база собирается КОДОМ НАПАРНИКА (parse_observations + replace_batch)
из CSV в том же формате, что присылает NASA. Настоящая база не используется
и не меняется.
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
sys.path.insert(0, str(BACKEND / "data_pipeline"))  # модуль напарника лежит рядом

from fires_data.parsing import parse_observations  # noqa: E402
from fires_data.store import Store  # noqa: E402
from fires_data.types import FetchPayload, Scope  # noqa: E402

AUGUST = [date(2024, 8, 1) + timedelta(days=i) for i in range(31)]
NRT_ONLY_DAY = date(2024, 9, 1)     # только оперативные (NRT) данные
EMPTY_DAY = date(2024, 9, 2)        # MODIS загружен, но пожаров 0; VIIRS не загружен
SP_AND_NRT_DAY = date(2024, 8, 5)   # есть и SP, и NRT — должен победить SP
SNPP_DAY = date(2024, 8, 10)        # точки S-NPP — в календарь не входят
EDGE_DAY = date(2024, 8, 7)         # точки ровно на линиях сетки


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
    """Записать один дневной срез так же, как это делает загрузчик напарника."""
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
        # «Активность» меняется по дням, VIIRS видит примерно в 3 раза больше клеток
        activity = 25 + int(15 * math.sin(number / 3)) + rng.randint(0, 5)
        modis_points, viirs_points = [], []
        for _ in range(activity):
            lat, lon = rng.uniform(44.5, 52.5), rng.uniform(22.5, 40.5)      # Украина
            modis_points.append((lat, lon))
            modis_points.append((lat + 0.001, lon + 0.001))                   # та же клетка
            for _ in range(3):
                viirs_points.append((lat + rng.uniform(-0.3, 0.3), lon + rng.uniform(-0.3, 0.3)))
        for _ in range(activity * 2):                                         # Африка
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

    # Тот же день в NRT с другими точками: читаться должен SP
    save(store, "MODIS_NRT", SP_AND_NRT_DAY, [(10.0, 10.0), (11.0, 11.0)], "T")
    # Точки S-NPP не входят в ряд VIIRS (там только NOAA-20)
    save(store, "VIIRS_SNPP_SP", SNPP_DAY, [(47.0, 30.0), (47.5, 30.5)], "N")
    # День только с NRT
    save(store, "MODIS_NRT", NRT_ONLY_DAY, [(48.2, 31.3), (48.25, 31.35), (-5.0, 20.0)], "A")
    save(store, "VIIRS_NOAA20_NRT", NRT_ONLY_DAY, [(48.2, 31.3), (48.6, 31.9), (-5.0, 20.0)], "N20")
    # Загруженный пустой день
    save(store, "MODIS_SP", EMPTY_DAY, [], "T")
    return store


@pytest.fixture(scope="session")
def partner_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("partner") / "fires.sqlite3"
    build_partner_db(path)
    return path


@pytest.fixture(scope="session")
def app_env(partner_db, tmp_path_factory):
    """Настроить переменные окружения и заново импортировать модули API."""
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
