"""Calibration behavior on independent, new report fixtures, not live data."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fires_data.calibration import calibrate_calendar


START = date(2024, 8, 1)


def report(pairs, *, missing_modis=(), missing_viirs=()):
    daily = []
    for index, (x, y) in enumerate(pairs):
        def series(value, missing):
            return ({"status": "missing", "observations": None, "active_cells": None} if missing else
                    {"status": "loaded", "observations": value * 2, "active_cells": value})
        modis_missing = index in missing_modis
        viirs_missing = index in missing_viirs
        daily.append({"date": (START + timedelta(days=index)).isoformat(),
                      "modis": series(y, modis_missing), "viirs": series(x, viirs_missing),
                      "shared_active_cells": None if modis_missing or viirs_missing else min(x, y)})
    return {
        "scope_id": "world", "bbox": [-180, -90, 180, 90],
        "date_from": START.isoformat(), "date_to": (START + timedelta(days=len(pairs) - 1)).isoformat(),
        "method": {"id": "common-grid-0p1deg-v1", "harmonized": False,
                   "grid_degrees": .1, "coordinate_quantization_degrees": 1e-7,
                   "daily_unit": "active_cells_per_UTC_day", "origin": {"longitude": -180, "latitude": -90},
                   "modis_platforms": ["Terra", "Aqua"], "viirs_platforms": ["NOAA-20"],
                   "modis_combination": "union of occupied cells per UTC day",
                   "confidence_filter": "all", "type_filter": "all",
                   "grid_crs": "EPSG:4326", "time_basis": "UTC"},
        "daily": daily, "input_windows": [],
    }


class ExploratoryCalibrationContracts(unittest.TestCase):
    def setUp(self):
        self.pairs = [(i, 2 * i) for i in range(1, 22)]
        self.split = START + timedelta(days=14)

    def test_perfect_scale_is_fitted_on_train_and_improves_holdout(self):
        result = calibrate_calendar(report(self.pairs), self.split)
        self.assertEqual(result["coefficient"], 2)
        self.assertEqual(result["status"], "improved_on_holdout")
        self.assertEqual(result["pairs"]["train"], 14)
        self.assertEqual(result["pairs"]["test"], 7)
        self.assertEqual(result["metrics"]["test"]["calibrated"]["mae"], 0)
        self.assertEqual(result["metrics"]["test"]["calibrated"]["r2"], 1)
        self.assertFalse(result["apply_automatically"])
        self.assertTrue(result["exploratory"])

    def test_test_values_do_not_change_fit_or_training_mean(self):
        first = calibrate_calendar(report(self.pairs), self.split)
        changed = self.pairs[:14] + [(x, 5 * x) for x, _ in self.pairs[14:]]
        second = calibrate_calendar(report(changed), self.split)
        self.assertEqual(first["coefficient"], second["coefficient"])
        self.assertEqual(first["training_mean_reference"], second["training_mean_reference"])
        self.assertEqual([row["calibrated"] for row in first["daily"]],
                         [row["calibrated"] for row in second["daily"]])

    def test_loaded_zero_is_a_pair_and_missing_days_are_skipped_and_reported(self):
        pairs = [(i, 2 * i) for i in range(23)]
        result = calibrate_calendar(report(pairs, missing_modis=(5,), missing_viirs=(18,)),
                                    START + timedelta(days=15))
        self.assertEqual(result["pairs"], {"train": 14, "test": 7, "skipped_missing": 2, "requested_days": 23})
        self.assertEqual(result["daily"][0]["original"], 0)
        self.assertEqual(result["daily"][0]["reference"], 0)
        self.assertEqual(result["daily"][0]["calibrated"], 0)
        self.assertEqual(len(result["skipped_days"]), 2)
        self.assertEqual(result["coefficient"], 2)

    def test_insufficient_counts_do_not_invent_a_model_or_metrics(self):
        result = calibrate_calendar(report(self.pairs), START + timedelta(days=10))
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn("fewer_than_14_training_pairs", result["reasons"])
        self.assertIsNone(result["coefficient"])
        self.assertIsNone(result["metrics"])
        self.assertTrue(all(row["calibrated"] is None for row in result["daily"]))

    def test_constant_training_predictor_or_reference_is_insufficient(self):
        for pairs, reason in (([(1, i) for i in range(21)], "training_predictor_is_constant"),
                              ([(i, 10) for i in range(21)], "training_reference_is_constant")):
            with self.subTest(reason=reason):
                result = calibrate_calendar(report(pairs), self.split)
                self.assertEqual(result["status"], "insufficient_data")
                self.assertIn(reason, result["reasons"])
                self.assertIsNone(result["metrics"])

    def test_constant_test_reference_has_no_r2_and_training_mean_can_win(self):
        pairs = [(i, 100 if i % 2 == 0 else 0) for i in range(1, 15)]
        pairs += [(i, 50) for i in range(15, 22)]
        result = calibrate_calendar(report(pairs), self.split)
        self.assertEqual(result["status"], "not_improved")
        for name in ("raw", "calibrated", "training_mean"):
            self.assertIsNone(result["metrics"]["test"][name]["r2"])
        self.assertEqual(result["metrics"]["test"]["training_mean"]["mae"], 0)

    def test_tying_an_already_perfect_raw_series_is_not_improvement(self):
        result = calibrate_calendar(report([(i, i) for i in range(1, 22)]), self.split)
        self.assertEqual(result["coefficient"], 1)
        self.assertEqual(result["status"], "not_improved")

    def test_duplicate_unsorted_out_of_range_and_omitted_dates_are_rejected(self):
        base = report(self.pairs)
        duplicate = deepcopy(base); duplicate["daily"][1]["date"] = duplicate["daily"][0]["date"]
        unsorted = deepcopy(base); unsorted["daily"][1], unsorted["daily"][2] = unsorted["daily"][2], unsorted["daily"][1]
        outside = deepcopy(base); outside["daily"][0]["date"] = (START - timedelta(days=1)).isoformat()
        omitted = deepcopy(base); omitted["daily"].pop(2)
        for value in (duplicate, unsorted, outside, omitted):
            with self.subTest(value=value["daily"][0]["date"]), self.assertRaises(ValueError):
                calibrate_calendar(value, self.split)

    def test_negative_boolean_and_inconsistent_missing_counts_are_rejected(self):
        for field, value in (("active_cells", -1), ("active_cells", True), ("observations", False)):
            bad = report(self.pairs); bad["daily"][0]["modis"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                calibrate_calendar(bad, self.split)
        bad = report(self.pairs); bad["daily"][0]["modis"]["status"] = "missing"
        with self.assertRaises(ValueError):
            calibrate_calendar(bad, self.split)

    def test_profile_platform_crs_time_and_filters_are_checked(self):
        for field, value in (("id", "another-profile"), ("modis_platforms", ["Aqua"]),
                             ("viirs_platforms", ["NOAA-21"]), ("grid_crs", "EPSG:3857"),
                             ("time_basis", "local"), ("confidence_filter", "high"),
                             ("type_filter", "wildfire_only")):
            bad = report(self.pairs); bad["method"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                calibrate_calendar(bad, self.split)

    def test_input_is_not_mutated_and_snapshot_metadata_is_preserved(self):
        value = report(self.pairs)
        value["method"]["extra_note"] = "retained metadata"
        value["input_windows"] = [{"source_code": "MODIS_SP", "day": START.isoformat(),
                                    "checksum": "abc", "fetched_at": "2026-11-14T00:00:00Z"}]
        before = deepcopy(value)
        result = calibrate_calendar(value, self.split)
        self.assertEqual(value, before)
        self.assertEqual(result["input_windows"], value["input_windows"])
        self.assertEqual(result["input_method"]["extra_note"], "retained metadata")


if __name__ == "__main__":
    unittest.main()
