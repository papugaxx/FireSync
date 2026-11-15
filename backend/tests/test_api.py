"""The general endpoints (/calendar, /cells, ...) on the new database. Run from backend: python -m pytest -q"""

import csv
import io

from conftest import AUGUST, MODIS_ONLY_DAY, SNPP_DAY

AUG = "date_from=2024-08-01&date_to=2024-08-31"


def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307) and response.headers["location"] == "/docs"


def test_health_status_and_timing_header(client):
    assert client.get("/health").json() == {"status": "ok"}
    status = client.get("/status")
    body = status.json()
    assert body["status"] == "ok" and body["data"]["modis"]["first_day"] == "2021-08-01"
    assert body["database"]["archive"]["status"] == "completed"
    assert float(status.headers["x-process-time-ms"]) >= 0


def test_regions(client):
    regions = {r["id"]: r for r in client.get("/regions").json()}
    assert regions["world"]["bbox"] is None and regions["ukraine"]["bbox"] == [22.1, 44.3, 40.2, 52.4]


def test_calendar_by_region(client):
    body = client.get(f"/calendar?{AUG}&region=ukraine").json()
    assert len(body["daily"]) == 31 and body["coverage"]["modis"] == {"loaded_days": 31, "requested_days": 31}
    day = body["daily"][0]
    assert day["modis"]["status"] == "loaded" and day["viirs"]["active_cells"] >= day["shared_active_cells"]
    assert day["modis"]["level"] in range(5)
    assert body["totals"]["modis"]["active_cell_days"] == sum(d["modis"]["active_cells"] for d in body["daily"])


def test_calendar_missing_days_are_null(client):
    body = client.get("/calendar?date_from=2024-09-01&date_to=2024-09-03&region=ukraine").json()
    first, second = body["daily"][0], body["daily"][1]
    assert first["modis"] == {"status": "missing", "product": None, "observations": None, "active_cells": None,
                              "level": None}
    assert second["date"] == MODIS_ONLY_DAY.isoformat() and second["modis"]["status"] == "loaded"
    assert second["viirs"]["active_cells"] is None and second["shared_active_cells"] is None
    assert body["totals"]["modis"]["active_cell_days"] is None


def test_custom_bbox_is_snapped_and_limited(client):
    body = client.get(f"/calendar?{AUG}&west=22.13&south=44.31&east=40.2&north=52.4").json()
    assert body["area"]["bbox"] == [22.1, 44.3, 40.2, 52.4]
    long = client.get("/calendar?date_from=2021-01-01&date_to=2024-12-31&west=22&south=44&east=41&north=53")
    assert long.status_code == 400


def test_monthly(client):
    body = client.get("/calendar/monthly?date_from=2024-01-01&date_to=2024-12-31&region=ukraine").json()
    months = {m["month"]: m for m in body["months"]}
    assert months["2024-08"]["modis"]["status"] == "complete"
    assert months["2024-09"]["modis"]["status"] == "partial" and months["2024-09"]["viirs"]["status"] == "missing"
    assert months["2024-01"]["modis"]["active_cell_days"] is None
    assert months["2024-08"]["modis"]["area_km2"] > 0 and months["2024-08"]["modis"]["level"] in range(5)


def test_cells_geojson(client):
    body = client.get(f"/cells?{AUG}&region=ukraine&resolution=0.5").json()
    assert body["type"] == "FeatureCollection" and body["features"]
    days = [f["properties"]["active_days"] for f in body["features"]]
    assert days == sorted(days, reverse=True) and max(days) <= 31
    assert client.get("/cells?date_from=2024-01-01&date_to=2024-12-31&region=ukraine").status_code == 400


def test_points_pages_and_no_snpp(client):
    first = client.get("/points?date_from=2024-08-10&date_to=2024-08-10&region=ukraine&limit=5").json()
    assert first["count"] == 5 and first["has_more"]
    second = client.get("/points?date_from=2024-08-10&date_to=2024-08-10&region=ukraine&limit=5&offset=5").json()
    assert not {(p["latitude"], p["longitude"], p["acq_time"]) for p in first["points"]} & \
        {(p["latitude"], p["longitude"], p["acq_time"]) for p in second["points"]}
    every = client.get(f"/points?date_from={SNPP_DAY}&date_to={SNPP_DAY}&limit=5000").json()["points"]
    assert {p["satellite"] for p in every} <= {"Terra", "Aqua", "NOAA-20"}
    assert client.get("/points?date_from=2024-08-01&date_to=2024-08-31").status_code == 400


def test_harmonization_and_anomaly(client):
    body = client.get(f"/harmonization?{AUG}&region=ukraine").json()
    assert body["summary"]["pairs"]["train"] + body["summary"]["pairs"]["test"] == 31
    assert all(s["harmonized_source"] == "MODIS" for s in body["series"])
    anomaly = client.get("/anomaly?year=2024&month=8&region=ukraine").json()
    assert anomaly["status"] == "ok" and anomaly["years_available"] == [2021, 2022, 2023, 2024]
    short = client.get("/anomaly?year=2024&month=9&region=ukraine").json()
    assert short["status"] == "month_not_loaded"


def test_export_csv(client):
    response = client.get("/export.csv?date_from=2024-08-01&date_to=2024-08-02&region=ukraine&sensor=MODIS")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == int(response.headers["x-total-rows"]) > 0
    assert {r["sensor"] for r in rows} == {"MODIS"} and {r["acq_date"] for r in rows} <= {"2024-08-01", "2024-08-02"}


def test_errors_are_json(client):
    cases = {
        "/calendar?date_from=2024-08-31&date_to=2024-08-01": 400,
        f"/calendar?{AUG}&west=22": 400,
        f"/calendar?{AUG}&west=41&south=44&east=22&north=53": 400,
        f"/calendar?{AUG}&region=atlantis": 400,
        f"/calendar?{AUG}&region=ukraine&west=1&south=1&east=2&north=2": 400,
        "/calendar?date_from=yesterday&date_to=2024-08-01": 422,
        f"/calendar?{AUG}&west=500&south=1&east=600&north=2": 422,
    }
    for path, code in cases.items():
        response = client.get(path)
        assert response.status_code == code, path
        assert isinstance(response.json()["error"], str)


def test_large_responses_are_compressed(client):
    response = client.get(f"/calendar?{AUG}&region=world", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("content-encoding") == "gzip"


def test_august_is_fully_covered(client):
    body = client.get(f"/calendar?{AUG}").json()
    assert all(d["modis"]["status"] == "loaded" and d["viirs"]["status"] == "loaded" for d in body["daily"])
    assert [d["date"] for d in body["daily"]] == [d.isoformat() for d in AUGUST]
