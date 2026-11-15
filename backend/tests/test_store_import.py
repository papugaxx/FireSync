"""The archive import and the database: nothing lost, nothing invented, same grid as the partner."""

from collections import defaultdict
from contextlib import closing
from datetime import date, timedelta

import pytest

from conftest import AUGUST, EDGE_DAY, MODIS_ONLY_DAY, QUIET_UKRAINE_DAY, SP_AND_NRT_DAY, UKRAINE, partner_cell


def _expected(rows, cells=None):
    """Per (day, sensor): distinct cells, detections, FRP — computed directly from the CSV rows."""
    result = defaultdict(lambda: {"cells": set(), "obs": 0, "frp": []})
    for r in rows:
        y, x = partner_cell(r["lat"], r["lon"])
        if cells and not (cells[0] <= y <= cells[1] and cells[2] <= x <= cells[3]):
            continue
        item = result[(r["day"], r["sensor"])]
        item["cells"].add((y, x))
        item["obs"] += 1
        if r["frp"] is not None:
            item["frp"].append(r["frp"])
    return result


def test_import_report(app_env, archive):
    report = app_env["report"]
    assert report["detections_stored"] == len(archive["rows"])
    assert report["rows_read"] == len(archive["rows"]) + 5          # + the NRT rows of an SP day
    assert report["skipped_other_sources"] == {"VIIRS_SNPP": 5}
    assert report["nrt_rows_replaced_by_sp"] == 5
    assert report.get("days_merged", 0) > 0          # shuffled days were joined, not duplicated
    with closing(app_env["store"].connect()) as conn:
        total = conn.execute("SELECT SUM(observations) FROM days").fetchone()[0]
        coverage = app_env["store"].coverage(conn)
    assert total == len(archive["rows"])
    assert coverage["modis"]["first_day"] == "2021-08-01" and coverage["modis"]["last_day"] == "2024-09-02"
    assert coverage["viirs"]["days"] == 31


def test_every_day_has_exactly_its_rows(app_env, archive):
    expected = _expected(archive["rows"])
    store = app_env["store"]
    with closing(store.connect()) as conn:
        stored = {(r["day"], r["sensor"]): dict(r) for r in conn.execute("SELECT * FROM days")}
        assert set(stored) == set(expected)
        for key, item in expected.items():
            assert stored[key]["observations"] == item["obs"], key
            assert stored[key]["cells"] == len(item["cells"]), key
            assert stored[key]["product"] == "SP" and stored[key]["origin"] == "archive"


def test_values_round_trip_exactly(app_env, archive):
    store = app_env["store"]
    with closing(store.connect()) as conn:
        got = store.detections(conn, EDGE_DAY.isoformat(), "VIIRS")
    edge = [p for p in got if (p["latitude"], p["longitude"]) == (48.0, 30.0)]
    assert len(edge) == 1
    assert edge[0]["frp_mw"] == 3.25 and edge[0]["brightness_k"] == 330.12 and edge[0]["brightness2_k"] == 291.07
    assert edge[0]["satellite"] == "NOAA-20" and edge[0]["confidence"] == "n" and edge[0]["version"] == "2"
    assert edge[0]["scan_km"] == 0.45 and edge[0]["daynight"] == "N" and edge[0]["type"] == 0
    sample = [r for r in archive["rows"] if r["day"] == "2024-08-03" and r["sensor"] == "VIIRS"]
    with closing(store.connect()) as conn:
        stored = store.detections(conn, "2024-08-03", "VIIRS")
    key = lambda p: (p[0], p[1], p[2])  # noqa: E731
    assert sorted(key((r["lat"], r["lon"], r["frp"])) for r in sample) == \
        sorted(key((p["latitude"], p["longitude"], p["frp_mw"])) for p in stored)


def test_nrt_rows_never_added_to_sp_day(app_env):
    store = app_env["store"]
    with closing(store.connect()) as conn:
        rows = store.detections(conn, SP_AND_NRT_DAY.isoformat(), "MODIS")
    assert not [p for p in rows if (p["latitude"], p["longitude"]) == (10.0, 10.0)]


def test_region_tables_match_the_raw_rows(app_env, archive):
    store = app_env["store"]
    cells = store.cell_range(UKRAINE)
    expected = _expected(archive["rows"], cells)
    with closing(store.connect()) as conn:
        rows = store.region_day_rows(conn, "ukraine", "2021-01-01", "2024-12-31")
    for day in AUGUST:
        row, d = rows[day.isoformat()], day.isoformat()
        for sensor, ch in (("MODIS", "modis"), ("VIIRS", "viirs")):
            item = expected.get((d, sensor), {"cells": set(), "obs": 0, "frp": []})
            assert row[f"{ch}_cells"] == len(item["cells"]), (d, sensor)
            assert row[f"{ch}_obs"] == item["obs"]
            assert row[f"{ch}_frp_n"] == len(item["frp"])            # missing FRP is not a zero
            assert row[f"{ch}_frp_sum"] == pytest.approx(sum(item["frp"]))
            assert row[f"{ch}_frp_max"] == (max(item["frp"]) if item["frp"] else None)
        shared = expected.get((d, "MODIS"), {"cells": set()})["cells"] & expected.get((d, "VIIRS"), {"cells": set()})["cells"]
        assert row["shared_cells"] == len(shared)
    quiet = rows[QUIET_UKRAINE_DAY.isoformat()]
    assert quiet["modis_cells"] == 0 and quiet["viirs_cells"] == 0     # stored day, no fire: a real zero
    only = rows[MODIS_ONLY_DAY.isoformat()]
    assert only["modis_cells"] > 0 and only["viirs_cells"] is None and only["shared_cells"] is None


def test_month_area_counts_distinct_cells_with_latitude(app_env, archive):
    store = app_env["store"]
    cells = store.cell_range(UKRAINE)
    distinct = {partner_cell(r["lat"], r["lon"]) for r in archive["rows"]
                if r["sensor"] == "MODIS" and r["day"].startswith("2024-08")}
    distinct = {c for c in distinct if cells[0] <= c[0] <= cells[1] and cells[2] <= c[1] <= cells[3]}
    with closing(store.connect()) as conn:
        month = store.region_month_rows(conn, "ukraine", "2024-08", "2024-08")[("2024-08", "MODIS")]
    assert month["cells"] == len(distinct) and month["loaded_days"] == 31
    # a 0.1° cell near 48°N is about 82.7 km²; the area is not 100 km² per cell
    assert 75 < month["area_km2"] / month["cells"] < 90
    assert month["cell_day_area_km2"] > month["area_km2"]


def test_grid_matches_the_partner_calculation(app_env, archive, tmp_path):
    """Load the same rows with the partner's own code and compare its grid_calendar with ours."""
    from datetime import datetime, timezone
    from fires_data import grid_calendar
    from fires_data.parsing import parse_observations
    from fires_data.store import Store
    from fires_data.types import FetchPayload, Scope
    partner = Store(tmp_path / "partner.sqlite3")
    partner.initialize()
    partner.save_scope(Scope.world())
    lines = archive["path"].read_text().splitlines()
    header = lines[0]
    by_key = defaultdict(list)
    for line in lines[1:]:
        f = line.split(",")
        if f[-1] == "MODIS" and not f[10].endswith("NRT"):
            by_key[(f[5], "MODIS_SP")].append(line)
        elif f[-1] == "VIIRS_NOAA20":
            by_key[(f[5], "VIIRS_NOAA20_SP")].append(line)
    for (day, source), rows in by_key.items():
        if not day.startswith("2024-08"):
            continue
        body = (header + "\n" + "\n".join(rows) + "\n").encode()
        d = date.fromisoformat(day)
        payload = FetchPayload(body, source, "world", d, d, datetime(2024, 10, 1, tzinfo=timezone.utc), "test")
        partner.replace_batch(Scope.world(), payload, parse_observations(body, source, Scope.world(), d, d))
    reference = grid_calendar(partner, "world", AUGUST[0], AUGUST[-1])
    reports = app_env["reports"]
    with closing(app_env["store"].connect()) as conn:
        ours = reports.calendar(conn, reports.area("world"), AUGUST[0], AUGUST[-1])
    for a, b in zip(reference["daily"], ours["daily"]):
        assert a["date"] == b["date"]
        for ch in ("modis", "viirs"):
            assert a[ch]["active_cells"] == b[ch]["active_cells"], (a["date"], ch)
            assert a[ch]["observations"] == b[ch]["observations"], (a["date"], ch)


def test_import_can_stop_and_continue(app_env, archive, tmp_path):
    importer, store = app_env["importer"], app_env["store"]
    db = tmp_path / "resumed.sqlite3"
    runs = 0
    while True:
        runs += 1
        result = importer.run(archive["path"], workers=1, db=db, log=lambda *a, **k: None,
                              chunk_bytes=4096, segment_bytes=8192, max_seconds=1e-9)
        if result["status"] == "completed":
            break
        assert runs < 500
    assert runs > 2
    with closing(store.connect(db)) as a, closing(store.connect(app_env["db"])) as b:
        query = "SELECT day, sensor, observations, cells FROM days ORDER BY day, sensor"
        assert a.execute(query).fetchall() == b.execute(query).fetchall()
        query = "SELECT * FROM region_days ORDER BY region, day"
        assert [tuple(r) for r in a.execute(query)] == [tuple(r) for r in b.execute(query)]
    again = importer.run(archive["path"], workers=1, db=db, log=lambda *a, **k: None)
    assert again["status"] == "completed"      # already imported: nothing is added twice
    with closing(store.connect(db)) as a:
        assert a.execute("SELECT SUM(observations) FROM days").fetchone()[0] == len(archive["rows"])


def test_block_codec_keeps_missing_values_missing(app_env):
    store = app_env["store"]
    import numpy as np
    cols = {name: np.array(values, dtype=store.COLUMNS[name][0]) for name, values in {
        "lat": [5000000, -100], "lon": [1, 2], "time": [0, 2359], "frp": [0xFFFFFFFF, 0],
        "bright": [0xFFFFFFFF, 30000], "bright2": [0xFFFFFFFF, 1], "scan": [0xFFFF, 1], "track": [1, 0xFFFF],
        "confidence": [255, 100], "satellite": [0, 1], "daynight": [0, 1], "type": [255, 3], "version": [0, 1],
    }.items()}
    decoded, versions = store.decode_block(store.encode_block(cols, ["6.1", "6.1NRT"]))
    order = np.lexsort((cols["time"], cols["lon"], cols["lat"]))
    for name in cols:
        assert decoded[name].tolist() == cols[name][order].tolist(), name
    assert versions == ["6.1", "6.1NRT"]
    empty, _ = store.decode_block(store.encode_block(store.empty_columns(), []))
    assert all(len(v) == 0 for v in empty.values())


def test_custom_rectangle_equals_region_with_the_same_bounds(app_env):
    reports = app_env["reports"]
    with closing(app_env["store"].connect()) as conn:
        a = reports.calendar(conn, reports.area("ukraine"), AUGUST[0], AUGUST[-1] + timedelta(days=2))
        b = reports.calendar(conn, reports.area(None, UKRAINE), AUGUST[0], AUGUST[-1] + timedelta(days=2))
    assert a["daily"] == b["daily"]
