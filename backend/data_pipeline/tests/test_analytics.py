"""Common-grid behavior in temporary databases; no real data or network."""

import csv
from datetime import date, datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fires_data.analytics import grid_calendar
from fires_data.parsing import parse_observations
from fires_data.store import Store
from fires_data.types import FetchPayload, Scope


DAY = date(2024, 8, 1)


class CommonGridContracts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / "observations.sqlite3")
        self.store.initialize()
        self.scope = Scope.world()
        self.store.save_scope(self.scope)

    def save(self, source, records, *, start=DAY, end=DAY, scope=None):
        scope = scope or self.scope
        modis = source.startswith("MODIS_")
        version = "6.1" if modis else "2.0"
        if source.endswith("_NRT"):
            version += "NRT"
        satellite = "T" if modis else ("N21" if "NOAA21" in source else "N20")
        brightness = "brightness" if modis else "bright_ti4"
        base = {"latitude": "1.01", "longitude": "1.01", brightness: "321.2",
                "scan": "1.0", "track": "1.0", "acq_date": DAY.isoformat(),
                "acq_time": "0100", "satellite": satellite,
                "confidence": "86" if modis else "nominal", "version": version,
                "frp": "12.5", "daynight": "N"}
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=base.keys())
        writer.writeheader()
        writer.writerows({**base, **record} for record in records)
        body = buffer.getvalue().encode("utf-8")
        payload = FetchPayload(body, source, scope.id, start, end,
                               datetime(2024, 8, 3, tzinfo=timezone.utc), "redacted")
        self.store.replace_batch(scope, payload,
                                 parse_observations(body, source, scope, start, end))

    def test_union_of_terra_aqua_and_repeated_detections_with_shared_cells(self):
        self.save("MODIS_SP", [{}, {"satellite": "A", "acq_time": "0200"},
                               {"acq_time": "0300"}])
        self.save("VIIRS_NOAA20_SP", [{}, {"latitude": "1.21", "longitude": "1.21"}])
        result = grid_calendar(self.store, "world", DAY, DAY)
        day = result["daily"][0]
        self.assertEqual(day["modis"], {"status": "loaded", "observations": 3, "active_cells": 1})
        self.assertEqual(day["viirs"], {"status": "loaded", "observations": 2, "active_cells": 2})
        self.assertEqual(day["shared_active_cells"], 1)
        self.assertFalse(result["method"]["harmonized"])
        self.assertEqual(result["method"]["harmonization_status"], "not_calibrated")
        self.assertIsNone(result["method"]["r2"])

    def test_same_cell_on_two_days_counts_as_two_cell_days(self):
        tomorrow = DAY + timedelta(days=1)
        records = [{}, {"acq_date": tomorrow.isoformat()}]
        self.save("MODIS_SP", records, end=tomorrow)
        self.save("VIIRS_NOAA20_SP", records, end=tomorrow)
        result = grid_calendar(self.store, "world", DAY, tomorrow)
        self.assertEqual(result["totals"]["modis"], {"observations": 2, "active_cell_days": 2})
        self.assertEqual(result["totals"]["viirs"], {"observations": 2, "active_cell_days": 2})

    def test_missing_is_not_a_loaded_empty_day(self):
        self.save("MODIS_SP", [])
        result = grid_calendar(self.store, "world", DAY, DAY)
        day = result["daily"][0]
        self.assertEqual(day["modis"], {"status": "loaded", "observations": 0, "active_cells": 0})
        self.assertEqual(day["viirs"], {"status": "missing", "observations": None, "active_cells": None})
        self.assertIsNone(day["shared_active_cells"])
        self.assertEqual(result["totals"]["modis"]["active_cell_days"], 0)
        self.assertIsNone(result["totals"]["viirs"]["active_cell_days"])
        self.assertEqual(result["coverage"]["viirs"], {"loaded_days": 0, "requested_days": 1})

    def test_partial_period_totals_remain_unknown(self):
        self.save("MODIS_SP", [{}])
        result = grid_calendar(self.store, "world", DAY, DAY + timedelta(days=1))
        self.assertEqual(result["coverage"]["modis"], {"loaded_days": 1, "requested_days": 2})
        self.assertIsNone(result["totals"]["modis"]["observations"])
        self.assertIsNone(result["totals"]["modis"]["active_cell_days"])

    def test_negative_coordinates_and_inclusive_world_boundaries(self):
        coordinates = [(-180, -90), (-179.95, -89.95), (180, 90), (179.95, 89.95),
                       (-0.1, -0.1), (-0.1000001, -0.1), (-0.10000000000001, -0.1)]
        self.save("MODIS_SP", [{"longitude": str(lon), "latitude": str(lat), "acq_time": str(i + 1)}
                               for i, (lon, lat) in enumerate(coordinates)])
        self.save("VIIRS_NOAA20_SP", [])
        day = grid_calendar(self.store, "world", DAY, DAY)["daily"][0]
        self.assertEqual(day["modis"]["observations"], 7)
        self.assertEqual(day["modis"]["active_cells"], 4)
        self.assertEqual(day["shared_active_cells"], 0)

    def test_empty_standard_window_suppresses_older_nrt(self):
        self.save("MODIS_NRT", [{}])
        self.save("MODIS_SP", [])
        self.save("VIIRS_NOAA20_SP", [{}])
        result = grid_calendar(self.store, "world", DAY, DAY)
        self.assertEqual(result["daily"][0]["modis"]["active_cells"], 0)
        self.assertEqual(result["daily"][0]["shared_active_cells"], 0)
        self.assertEqual({row["source_code"] for row in result["input_windows"]},
                         {"MODIS_SP", "VIIRS_NOAA20_SP"})

    def test_bbox_filters_points_before_counting_cells(self):
        records = [{"longitude": "12.5", "latitude": "45.5"},
                   {"longitude": "13.5", "latitude": "46.5"}]
        self.save("MODIS_SP", records)
        self.save("VIIRS_NOAA20_SP", records)
        result = grid_calendar(self.store, "world", DAY, DAY, bbox=(12, 45, 13, 46))
        self.assertEqual(result["bbox"], [12, 45, 13, 46])
        self.assertEqual(result["daily"][0]["modis"]["observations"], 1)
        self.assertEqual(result["daily"][0]["viirs"]["active_cells"], 1)
        self.assertEqual(result["daily"][0]["shared_active_cells"], 1)

    def test_other_viirs_platform_does_not_become_noaa20_coverage(self):
        self.save("MODIS_SP", [{}])
        self.save("VIIRS_NOAA21_SP", [{}])
        result = grid_calendar(self.store, "world", DAY, DAY)
        self.assertEqual(result["daily"][0]["viirs"]["status"], "missing")
        self.assertIsNone(result["daily"][0]["shared_active_cells"])

    def test_new_raw_snapshot_is_visible_without_persistent_aggregate_cache(self):
        self.save("MODIS_SP", [{}, {"acq_time": "0200"}])
        self.assertEqual(grid_calendar(self.store, "world", DAY, DAY)["daily"][0]["modis"]["active_cells"], 1)
        self.save("MODIS_SP", [{}, {"longitude": "1.21", "latitude": "1.21", "acq_time": "0200"}])
        self.assertEqual(grid_calendar(self.store, "world", DAY, DAY)["daily"][0]["modis"]["active_cells"], 2)

    def test_invalid_period_and_bbox_are_rejected(self):
        for start, end in ((DAY + timedelta(days=1), DAY), (DAY, DAY + timedelta(days=366))):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                grid_calendar(self.store, "world", start, end)
        with self.assertRaises(ValueError):
            grid_calendar(self.store, "world", DAY, DAY, bbox=(13, 45, 12, 46))
        narrow = Scope("narrow", "Narrow area", 10, 40, 15, 50)
        self.store.save_scope(narrow)
        with self.assertRaises(ValueError):
            grid_calendar(self.store, "narrow", DAY, DAY, bbox=(9, 41, 12, 45))


if __name__ == "__main__":
    unittest.main()
