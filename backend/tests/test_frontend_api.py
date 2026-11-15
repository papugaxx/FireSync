"""The /api/... contract of fire-calendar (types/api.ts) on real-format data."""

import csv
import io

from conftest import EDGE_DAY, MODIS_ONLY_DAY, QUIET_UKRAINE_DAY

FRONTEND_REGIONS = ("world", "ukraine", "argentina", "california", "amazonas")   # fire-calendar/lib/mock.ts


def test_meta_has_frontend_regions_and_years(client):
    result = client.get("/api/meta/").json()
    regions = {r["id"]: r for r in result["regions"]}
    assert set(FRONTEND_REGIONS) <= set(regions)
    assert regions["ukraine"]["bbox"] == [44.3, 22.1, 52.4, 40.2]            # [south, west, north, east]
    assert regions["ukraine"]["boundary"]["kind"] == "border" and regions["world"]["boundary"]["kind"] == "world"
    assert all(len(r["bbox"]) == 4 and isinstance(r["name"], str) for r in regions.values())
    assert result["years"] == [2021, 2022, 2023, 2024]
    assert client.get("/api/meta").status_code == 200                       # with and without the slash


def test_every_frontend_call_answers(client):
    for region in FRONTEND_REGIONS:
        for path in (f"/api/calendar/?region={region}", f"/api/month/?region={region}&year=2024&month=8",
                     f"/api/monthly/?region={region}&year=2024", f"/api/hotspots/?region={region}&year=2024&month=8"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)


def test_month_days_keep_missing_and_zero_apart(client):
    result = client.get("/api/month/?region=ukraine&year=2024&month=8").json()
    days = {d["date"]: d for d in result["days"]}
    assert len(result["days"]) == 31
    assert set(result["days"][0]) >= {"date", "modis", "viirs", "harmonized"}
    quiet = days[QUIET_UKRAINE_DAY.isoformat()]
    assert quiet["modis"] == 0 and quiet["viirs"] == 0 and quiet["harmonized"] == 0
    assert all(d["harmonized"] == d["modis"] and d["harmonized_source"] == "MODIS" for d in result["days"])
    september = client.get("/api/month/?region=ukraine&year=2024&month=9").json()["days"]
    assert september[0]["modis"] is None and september[0]["harmonized"] is None      # 1 Sep: no data
    only = september[MODIS_ONLY_DAY.day - 1]
    assert only["modis"] > 0 and only["viirs"] is None


def test_calendar_heatmap_complete_months_and_median(client):
    result = client.get("/api/calendar/?region=ukraine").json()
    years = {y["year"]: y for y in result["years"]}
    assert len(result["median"]) == 12 and all(len(y["months"]) == 12 for y in result["years"])
    assert years[2024]["months"][7] is not None              # August 2024 complete
    assert years[2024]["months"][8] is None                  # September: one day only → incomplete
    assert years[2022]["months"][0] is None                  # January: never stored
    augusts = sorted(years[y]["months"][7] for y in (2021, 2022, 2023, 2024))
    assert result["median"][7] == round((augusts[1] + augusts[2]) / 2)
    assert result["median"][0] is None                       # fewer than 3 complete years
    assert result["harmonization"]["status"] in ("validated", "draft")
    month = client.get("/api/month/?region=ukraine&year=2024&month=8").json()
    assert years[2024]["months"][7] == sum(d["harmonized"] for d in month["days"])


def test_monthly_chart_values(client):
    result = client.get("/api/monthly/?region=ukraine&year=2024").json()
    assert [m["month"] for m in result["months"]] == list(range(1, 13))
    august, september = result["months"][7], result["months"][8]
    for key in ("modis", "viirs", "areaKm2", "frpMean", "frpMax"):
        assert key in august
    assert august["modis"] > 0 and august["areaKm2"] > 0 and august["frpMax"] >= august["frpMean"] > 0
    assert august["viirs_raw"] > 0
    k = result["viirs_scale"]["coefficient"]
    assert august["viirs"] == (round(k * august["viirs_raw"]) if k is not None else None)
    assert september["modis"] is None and september["modis_partial"] > 0      # partial month marked
    assert result["months"][0]["modis"] is None


def test_hotspots_are_cell_days_with_dates(client):
    result = client.get("/api/hotspots/?region=ukraine&year=2024&month=8").json()
    spots = result["hotspots"]
    assert spots and result["truncated"] is False and result["total"] == len(spots)
    assert {h["seenBy"] for h in spots} <= {"MODIS", "VIIRS", "BOTH"}
    assert all(h["date"].startswith("2024-08-") and set(h) >= {"id", "lat", "lon", "date", "seenBy", "frp"}
               for h in spots)
    assert len({h["id"] for h in spots}) == len(spots)
    assert all(44.3 <= h["lat"] <= 52.5 and 22.0 <= h["lon"] <= 40.3 for h in spots)
    month = client.get("/api/month/?region=ukraine&year=2024&month=8").json()["days"]
    edge = [h for h in spots if h["date"] == EDGE_DAY.isoformat()]
    # every active cell of the day is a point: MODIS-only + VIIRS-only + shared cells
    day = next(d for d in month if d["date"] == EDGE_DAY.isoformat())
    both = sum(1 for h in edge if h["seenBy"] == "BOTH")
    assert len(edge) == day["modis"] + day["viirs"] - both


def test_hotspots_limit_is_reported(client):
    result = client.get("/api/hotspots/?region=world&year=2024&month=8&limit=62").json()
    assert result["truncated"] is True and len(result["hotspots"]) <= 62 < result["total"]
    assert len({h["date"] for h in result["hotspots"]}) == 31           # every day keeps its strongest cells
    one_day = client.get("/api/hotspots/?region=world&year=2024&month=8&day=2024-08-03").json()
    assert {h["date"] for h in one_day["hotspots"]} == {"2024-08-03"}


def test_export_has_the_real_detections(client):
    response = client.get("/api/export/?region=ukraine&year=2024&month=8&day=2024-08-07&sensor=VIIRS")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == int(response.headers["x-total-rows"]) > 0
    assert {r["sensor"] for r in rows} == {"VIIRS"} and {r["product"] for r in rows} == {"SP"}
    edge = [r for r in rows if (r["latitude"], r["longitude"]) == ("48.0", "30.0")]
    assert edge and edge[0]["frp_mw"] == "3.25"
    month = client.get("/api/export/?region=ukraine&year=2024&month=8")
    assert len(list(csv.DictReader(io.StringIO(month.text)))) == int(month.headers["x-total-rows"])


def test_errors_are_readable(client):
    for path, status in (("/api/month/?region=atlantis&year=2024&month=8", 400),
                         ("/api/month/?year=1999&month=8", 400), ("/api/month/?month=13", 400),
                         ("/api/hotspots/?year=2024&month=8&day=2024-09-01", 400),
                         ("/api/hotspots/?limit=0", 422), ("/api/monthly/?year=abc", 422)):
        response = client.get(path)
        assert response.status_code == status, path
        assert isinstance(response.json()["error"], str)


def test_cors_lets_the_frontend_read(client):
    response = client.get("/api/meta/", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_updates_status_never_shows_the_key(client):
    result = client.get("/api/updates/")
    assert result.status_code == 200
    assert "FIRMS_MAP_KEY=" not in result.text
    assert result.json()["stored"]["coverage"]["modis"]["days"] > 0


def test_month_days_carry_a_state(client):
    days = client.get("/api/month/?region=ukraine&year=2024&month=9").json()["days"]
    by_date = {d["date"]: d for d in days}
    assert by_date["2024-09-02"]["status"] == "complete"                # MODIS; VIIRS has no archive day (outage)
    assert by_date["2024-09-02"]["viirs_state"] == "no_data" and by_date["2024-09-02"]["viirs"] is None
    assert by_date["2024-09-02"]["modis_state"] == "final"
    assert by_date["2024-09-20"]["status"] == "no_data"                  # archive years, nothing stored
    assert by_date["2024-09-20"]["harmonized"] is None
    aug = client.get("/api/month/?region=ukraine&year=2024&month=8").json()["days"]
    quiet = next(d for d in aug if d["date"] == "2024-08-20")
    assert quiet["status"] == "complete" and quiet["modis"] == 0         # a measured zero, not missing data


def test_calendar_months_carry_a_state(client):
    years = {y["year"]: y for y in client.get("/api/calendar/?region=ukraine").json()["years"]}
    assert years[2024]["status"][7] == "complete" and years[2024]["status"][8] == "partial"
    assert years[2024]["status"][0] == "no_data"


def test_sync_endpoint(client):
    body = client.get("/api/sync/?date_from=2024-08-30&date_to=2024-09-03").json()
    assert body["status"] in ("never_synced", "catching_up", "up_to_date")
    assert [d["date"] for d in body["daily"]] == ["2024-08-30", "2024-08-31", "2024-09-01", "2024-09-02", "2024-09-03"]
    assert body["daily"][0]["status"] == "complete" and body["sensors"]["modis"]["archive_last_day"] == "2024-09-02"
    assert "last_error" in body and "last_success_at" in body
    assert client.get("/api/sync/?date_from=2024-09-03&date_to=2024-08-01").status_code == 400


def test_boundary_is_the_real_border(client):
    body = client.get("/api/boundary/?region=ukraine").json()
    assert body["properties"]["kind"] == "border" and body["properties"]["id"] == "country:UKR"
    assert len(body["geometry"]["coordinates"]) >= 1 and len(body["geometry"]["coordinates"][0][0]) > 50
    rect = client.get("/api/boundary/?region=central_africa").json()
    assert rect["properties"]["kind"] == "rectangle" and len(rect["geometry"]["coordinates"][0][0]) == 5


def test_hotspots_are_cells_and_detections_are_real_points(client):
    from conftest import border_rings, inside_border
    body = client.get("/api/hotspots/?region=ukraine&year=2024&month=8").json()
    spot = body["hotspots"][0]
    assert spot["kind"] == "cell" and spot["cell_size_degrees"] == 0.1 and "cell centre" in body["unit"]
    found = client.get(f"/api/detections/?region=ukraine&date={spot['date']}&cell={spot['cell']}").json()
    assert found["count"] == spot["modis_observations"] + spot["viirs_observations"]
    rings = border_rings("country:UKR")
    for p in found["points"]:
        assert p["cell"] == spot["cell"] and inside_border(rings, p["latitude"], p["longitude"])
        assert abs(p["latitude"] - spot["lat"]) <= 0.05 and abs(p["longitude"] - spot["lon"]) <= 0.05
    # every detection of a border region's day lies inside the border
    day = client.get("/api/detections/?region=ukraine&date=2024-08-03&limit=5000").json()["points"]
    assert day and all(inside_border(rings, p["latitude"], p["longitude"]) for p in day)
    assert client.get("/api/detections/?region=ukraine").status_code == 400


def test_map_calendar_and_statistics_agree_for_a_border_region(client):
    month = {d["date"]: d for d in client.get("/api/month/?region=ukraine&year=2024&month=8").json()["days"]}
    spots = client.get("/api/hotspots/?region=ukraine&year=2024&month=8&sensor=MODIS").json()["hotspots"]
    per_day = {}
    for s in spots:
        per_day[s["date"]] = per_day.get(s["date"], 0) + 1
    for d, item in month.items():
        assert per_day.get(d, 0) == item["modis"], d                    # map cells = calendar cells
    monthly = client.get("/api/monthly/?region=ukraine&year=2024").json()["months"][7]
    assert monthly["modis"] == sum(item["modis"] for item in month.values())
