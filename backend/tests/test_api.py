"""
API tests. Run from the backend folder:   python -m pytest -q

The database is built by the partner's code in a temporary folder (see conftest.py),
the real database is not used.
"""

import csv
import io
from datetime import date

from conftest import AUGUST, EDGE_DAY, EMPTY_DAY, NRT_ONLY_DAY, SP_AND_NRT_DAY

AUG = "date_from=2024-08-01&date_to=2024-08-31"


# ---------- Fast index = the partner's reference ----------

def test_fast_index_matches_partner_for_whole_world(app_env):
    grid_index, db = app_env["grid_index"], app_env["db"]
    start, end = date(2024, 8, 1), date(2024, 9, 3)
    fast = grid_index.calendar("world", start, end)
    reference = db.reference_calendar("world", start, end)
    assert fast["daily"] == reference["daily"]
    assert fast["totals"] == reference["totals"]
    assert fast["coverage"] == reference["coverage"]


def test_fast_index_matches_partner_inside_region(app_env):
    grid_index, db = app_env["grid_index"], app_env["db"]
    bbox = (20.0, 40.0, 45.0, 55.0)  # no points on the borders — the calculations must match
    start, end = date(2024, 8, 1), date(2024, 8, 31)
    assert grid_index.calendar("world", start, end, bbox)["daily"] == \
        db.reference_calendar("world", start, end, bbox)["daily"]


def test_point_on_border_is_counted_once(app_env):
    """A point exactly on the 41° line belongs to one cell, not to both neighboring regions."""
    grid_index = app_env["grid_index"]
    day = EDGE_DAY
    west = grid_index.calendar("world", day, day, (22.0, 44.0, 41.0, 53.0))["daily"][0]["modis"]
    east = grid_index.calendar("world", day, day, (41.0, 44.0, 60.0, 53.0))["daily"][0]["modis"]
    whole = grid_index.calendar("world", day, day, (22.0, 44.0, 60.0, 53.0))["daily"][0]["modis"]
    assert west["observations"] + east["observations"] == whole["observations"]


def test_incremental_refresh_does_nothing_without_changes(app_env):
    result = app_env["grid_index"].refresh()
    assert result["status"] == "ok" and result["rebuilt_days"] == 0


# ---------- System ----------

def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307) and response.headers["location"] == "/docs"


def test_health_and_status(client):
    assert client.get("/health").json() == {"status": "ok"}
    body = client.get("/status").json()
    assert body["status"] == "ok"
    assert body["data"]["world"]["modis"]["loaded_days"] == 33
    assert body["data"]["world"]["viirs"]["first_day"] == "2024-08-01"
    assert body["partner_database"]["found"] is True
    assert "path" not in str(body["partner_database"])  # we do not expose the file path


def test_process_time_header(client):
    assert float(client.get("/health").headers["X-Process-Time-Ms"]) >= 0


def test_regions(client):
    regions = {r["id"]: r for r in client.get("/regions").json()}
    assert regions["ukraine"]["bbox"] == [22.0, 44.0, 41.0, 53.0]
    assert regions["world"]["bbox"] is None


# ---------- Calendar ----------

def test_calendar_by_region(client):
    body = client.get(f"/calendar?{AUG}&region=ukraine").json()
    assert body["engine"] == "fast"
    assert len(body["daily"]) == 31
    assert body["area"]["region"] == "ukraine" and body["bbox"] == [22.0, 44.0, 41.0, 53.0]
    day = body["daily"][0]
    assert day["modis"]["status"] == "loaded" and day["modis"]["active_cells"] > 0
    assert day["viirs"]["active_cells"] > day["modis"]["active_cells"]   # VIIRS sees more
    assert day["modis"]["level"] in (1, 2, 3, 4)
    assert len(body["color_scale"]["viirs"]["breaks"]) == 3
    assert "input_windows" not in body


def test_calendar_marks_missing_and_empty_days(client):
    body = client.get("/calendar?date_from=2024-09-01&date_to=2024-09-03").json()
    nrt, empty, missing = body["daily"]
    assert nrt["modis"]["status"] == nrt["viirs"]["status"] == "loaded"        # NRT only — that is data too
    assert empty["modis"] == {"status": "loaded", "observations": 0, "active_cells": 0, "level": 0}
    assert empty["viirs"]["active_cells"] is None and empty["viirs"]["level"] is None
    assert missing["modis"]["status"] == "missing"


def test_sp_is_preferred_over_nrt(client):
    day = SP_AND_NRT_DAY.isoformat()
    body = client.get(f"/calendar?date_from={day}&date_to={day}&west=5&south=5&east=15&north=15").json()
    assert body["daily"][0]["modis"]["observations"] == 0   # NRT points at (10,10) are not visible: SP is read


def test_custom_bbox_is_snapped_to_grid(client):
    body = client.get(f"/calendar?{AUG}&west=22.04&south=44.01&east=40.96&north=52.99").json()
    assert body["bbox"] == [22.0, 44.0, 41.0, 53.0]
    assert body["area"]["requested_bbox"] == [22.04, 44.01, 40.96, 52.99]


def test_reference_engine_gives_same_numbers(client):
    fast = client.get(f"/calendar?{AUG}&west=20&south=40&east=45&north=55").json()
    reference = client.get(f"/calendar?{AUG}&west=20&south=40&east=45&north=55&engine=reference").json()
    assert [d["modis"]["active_cells"] for d in fast["daily"]] == \
        [d["modis"]["active_cells"] for d in reference["daily"]]


def test_monthly(client):
    body = client.get("/calendar/monthly?date_from=2024-07-01&date_to=2024-09-30&region=ukraine").json()
    july, august, september = body["months"]
    assert july["modis"]["status"] == "missing" and july["modis"]["active_cell_days"] is None
    assert august["modis"]["status"] == "complete" and august["days"] == 31
    assert september["modis"]["status"] == "partial"
    daily = client.get(f"/calendar?{AUG}&region=ukraine").json()
    assert august["modis"]["active_cell_days"] == sum(d["modis"]["active_cells"] for d in daily["daily"])


# ---------- Map ----------

def test_cells_geojson(client):
    body = client.get(f"/cells?{AUG}&resolution=1").json()
    assert body["type"] == "FeatureCollection" and body["features"]
    first = body["features"][0]
    assert first["geometry"]["type"] == "Point"
    lon, lat = first["geometry"]["coordinates"]
    assert -180 <= lon <= 180 and -90 <= lat <= 90
    assert first["properties"]["active_days"] >= body["features"][-1]["properties"]["active_days"]
    assert body["meta"]["resolution_degrees"] == 1.0


def test_cells_auto_resolution(client):
    assert client.get(f"/cells?{AUG}").json()["meta"]["resolution_degrees"] == 1.0
    assert client.get(f"/cells?{AUG}&west=30&south=45&east=35&north=50").json()["meta"]["resolution_degrees"] == 0.1


def test_points_pages(client):
    q = "date_from=2024-08-01&date_to=2024-08-01&region=ukraine"
    first = client.get(f"/points?{q}&limit=5").json()
    second = client.get(f"/points?{q}&limit=5&offset=5").json()
    assert first["count"] == 5 and first["has_more"] and first["next_offset"] == 5
    assert {p["id"] for p in first["points"]}.isdisjoint(p["id"] for p in second["points"])
    point = first["points"][0]
    assert 22 <= point["longitude"] <= 41 and 44 <= point["latitude"] <= 53
    geo = client.get(f"/points?{q}&limit=2&format=geojson").json()
    assert geo["type"] == "FeatureCollection" and len(geo["features"]) == 2


# ---------- Science ----------

def test_harmonization(client):
    body = client.get(f"/harmonization?{AUG}&region=ukraine&split_date=2024-08-22").json()
    summary = body["summary"]
    assert summary["status"] == "improved_on_holdout"
    assert 0 < summary["coefficient"] < 1                 # VIIRS sees more → k < 1
    assert summary["test_mae_harmonized"] < summary["test_mae_raw"]
    assert summary["error_reduction_percent"] > 50
    assert len(body["series"]) == 31
    assert body["series"][0]["split"] == "train" and body["series"][-1]["split"] == "test"
    assert body["series"][0]["harmonized_source"] == "MODIS"


def test_harmonization_fills_gap_with_scaled_viirs(app_env):
    analytics = app_env["analytics"]
    report = app_env["grid_index"].calendar("world", date(2024, 8, 1), date(2024, 8, 31), (22, 44, 41, 53))
    report["daily"][-1]["modis"] = {"status": "missing", "observations": None, "active_cells": None}
    report["daily"][-1]["shared_active_cells"] = None
    result = analytics.harmonize(report, date(2024, 8, 22))
    last = result["series"][-1]
    assert last["harmonized_source"] == "VIIRS_NOAA20 x k"
    assert last["harmonized"] == last["viirs_scaled"]


def test_anomaly_needs_history(client):
    body = client.get("/anomaly?year=2024&month=8&region=ukraine").json()
    assert body["status"] == "insufficient_history"
    assert body["years_available"] == [2024]


def test_anomaly_math(app_env):
    analytics = app_env["analytics"]

    def month(year, value):
        return {"year": year, "month_number": 8,
                "modis": {"status": "complete", "active_cell_days": value}}

    months = [month(2020, 100), month(2021, 120), month(2022, 80), month(2023, 110), month(2024, 210)]
    result = analytics.anomaly(months, 2024, 8, "modis")
    assert result["status"] == "ok"
    assert result["median"] == 105
    assert result["anomaly_percent"] == 100.0
    assert result["verdict"] == "above_normal" and result["rank"] == 1


# ---------- Export ----------

def test_export_csv(client):
    response = client.get("/export.csv?date_from=2024-08-01&date_to=2024-08-02&region=ukraine&sensor=MODIS")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == int(response.headers["X-Total-Rows"]) > 0
    assert {r["sensor"] for r in rows} == {"MODIS"}
    assert rows == sorted(rows, key=lambda r: r["observed_at"])


# ---------- Errors are clear to the frontend ----------

def test_errors_are_json(client):
    cases = {
        "/calendar?date_from=2024-08-31&date_to=2024-08-01": 400,           # dates reversed
        f"/calendar?{AUG}&west=22": 400,                                     # not all boundaries
        f"/calendar?{AUG}&west=41&south=44&east=22&north=53": 400,           # west > east
        f"/calendar?{AUG}&region=atlantis": 400,                             # no such region
        f"/calendar?{AUG}&region=ukraine&west=1&south=1&east=2&north=2": 400,
        "/calendar?date_from=2000-01-01&date_to=2024-12-31": 400,            # too long
        "/points?date_from=2024-08-01&date_to=2024-08-31": 400,              # points — up to 7 days
        f"/cells?{AUG}&resolution=0.3": 400,
        "/calendar?date_from=вчера&date_to=2024-08-01": 422,                 # not a date
        f"/calendar?{AUG}&west=500&south=1&east=600&north=2": 422,           # outside the Earth
    }
    for url, status in cases.items():
        response = client.get(url)
        assert response.status_code == status, url
        assert isinstance(response.json()["error"], str) and response.json()["error"], url


def test_cors_for_frontend(client):
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_large_responses_are_compressed(client):
    response = client.get(f"/calendar?{AUG}", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("content-encoding") == "gzip"


def test_august_is_fully_covered(client):
    body = client.get(f"/calendar?{AUG}").json()
    assert body["coverage"]["modis"] == {"loaded_days": len(AUGUST), "requested_days": 31}
    assert body["totals"]["modis"]["active_cell_days"] > 0
    assert NRT_ONLY_DAY > AUGUST[-1] and EMPTY_DAY > NRT_ONLY_DAY
