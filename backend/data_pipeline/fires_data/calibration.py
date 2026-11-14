"""Chronological exploratory calibration of two fixed common-grid series.

MODIS is a comparison reference, not ground truth. The fitted value is an
index, not an observed number of cells. This module never updates the database
or automatically replaces a served time series.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta
import math
from statistics import fmean

from .types import Scope


PROFILE_ID = "common-grid-0p1deg-v1"
MIN_TRAIN_PAIRS = 14
MIN_TEST_PAIRS = 7
_SOURCES = {"MODIS_SP", "MODIS_NRT", "VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"}


def _iso_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must use YYYY-MM-DD.") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD.")
    return parsed


def _count(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer count.")
    return value


def _validate_method(method):
    if not isinstance(method, dict) or method.get("id") != PROFILE_ID:
        raise ValueError("Calibration requires the known common-grid-0p1deg-v1 profile.")
    expected = {
        "grid_degrees": 0.1,
        "coordinate_quantization_degrees": 1e-7,
        "daily_unit": "active_cells_per_UTC_day",
        "confidence_filter": "all",
        "type_filter": "all",
    }
    for field, value in expected.items():
        if method.get(field) != value:
            raise ValueError(f"Input method has an incompatible {field}.")
    if method.get("harmonized") is not False:
        raise ValueError("Input must contain uncalibrated observed common-grid values.")
    if method.get("origin") != {"longitude": -180, "latitude": -90}:
        raise ValueError("Input grid origin must be longitude -180, latitude -90.")
    platforms = method.get("modis_platforms")
    if (not isinstance(platforms, list) or len(platforms) != 2
            or not all(isinstance(item, str) for item in platforms)
            or set(platforms) != {"Terra", "Aqua"}):
        raise ValueError("The reference must use the Terra and Aqua cell union.")
    if method.get("modis_combination") != "union of occupied cells per UTC day":
        raise ValueError("The MODIS series must be a daily cell union.")
    if method.get("viirs_platforms") != ["NOAA-20"]:
        raise ValueError("The predictor must use NOAA-20 only.")
    # Reports produced before these explicit labels used the same known profile.
    if method.get("grid_crs", "EPSG:4326") != "EPSG:4326":
        raise ValueError("Input grid CRS must be EPSG:4326.")
    if method.get("time_basis", "UTC") != "UTC" or method.get("timezone", "UTC") != "UTC":
        raise ValueError("Input daily series must use UTC days.")


def _validate_series(value, field):
    if not isinstance(value, dict) or value.get("status") not in {"loaded", "missing"}:
        raise ValueError(f"{field} must have a loaded or missing status.")
    if "active_cells" not in value or "observations" not in value:
        raise ValueError(f"{field} must specify active_cells and observations.")
    if value["status"] == "missing":
        if value["active_cells"] is not None or value["observations"] is not None:
            raise ValueError(f"Missing {field} values must be null, not zero.")
        return None
    cells = _count(value["active_cells"], f"{field}.active_cells")
    observations = _count(value["observations"], f"{field}.observations")
    if cells > observations:
        raise ValueError(f"{field} cannot have more active cells than observations.")
    return cells


def _metrics(reference, predicted):
    errors = [pred - ref for ref, pred in zip(reference, predicted)]
    mae = fmean(abs(error) for error in errors)
    bias = fmean(errors)
    mse = fmean(error * error for error in errors)
    mean = fmean(reference)
    sst = math.fsum((ref - mean) ** 2 for ref in reference)
    sse = math.fsum(error * error for error in errors)
    r2 = None if sst == 0 else 1 - sse / sst
    result = {"mae": mae, "bias": bias, "rmse": math.sqrt(mse), "r2": r2}
    if any(value is not None and not math.isfinite(value) for value in result.values()):
        raise ValueError("Counts exceed the finite numeric range supported by calibration.")
    return result


def _improves(candidate_mae, baseline_mae):
    tolerance = max(1e-9, abs(baseline_mae) * 1e-9)
    return candidate_mae < baseline_mae - tolerance


def calibrate_calendar(report, split_date: date):
    """Fit one non-negative scale on train days and evaluate untouched test days.

    split_date is the first test day. Operational sample-size guards are fixed
    at 14 paired training days and seven paired test days. They are not a
    statistical guarantee. Missing observations are excluded, not imputed.
    """
    if not isinstance(report, dict):
        raise ValueError("Expected a grid_calendar report.")
    if not isinstance(split_date, date) or isinstance(split_date, datetime):
        raise ValueError("split_date must be a datetime.date value.")
    start = _iso_date(report.get("date_from"), "date_from")
    end = _iso_date(report.get("date_to"), "date_to")
    if end < start or not start <= split_date <= end:
        raise ValueError("The split must lie within a valid report date interval.")
    _validate_method(report.get("method"))
    try:
        domain_scope = Scope.from_bbox(report.get("bbox"), scope_id=report.get("scope_id"),
                                       name="Calibration domain")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Report must specify a valid scope_id and bounding rectangle.") from None
    if not isinstance(report.get("scope_id"), str) or domain_scope.id != report["scope_id"]:
        raise ValueError("Report must specify its existing scope_id.")
    daily = report.get("daily")
    if not isinstance(daily, list):
        raise ValueError("Report daily must be a list.")
    requested_days = (end - start).days + 1
    if len(daily) != requested_days:
        raise ValueError("Daily rows must cover the declared interval; express missing days explicitly.")

    pairs, skipped = [], []
    seen = set()
    for index, row in enumerate(daily):
        if not isinstance(row, dict):
            raise ValueError("Each daily row must be an object.")
        current = _iso_date(row.get("date"), "daily.date")
        if current in seen:
            raise ValueError("Daily dates must be unique.")
        seen.add(current)
        if not start <= current <= end:
            raise ValueError("A daily date lies outside the declared interval.")
        if current != start + timedelta(days=index):
            raise ValueError("Daily rows must be chronologically sorted without omitted dates.")
        reference = _validate_series(row.get("modis"), "modis")
        original = _validate_series(row.get("viirs"), "viirs")
        shared = row.get("shared_active_cells")
        if reference is not None and original is not None:
            if shared is not None and _count(shared, "shared_active_cells") > min(reference, original):
                raise ValueError("Shared cells exceed one of the observed cell counts.")
        elif shared is not None:
            raise ValueError("Shared cells must be null when either series is missing.")
        split = "train" if current < split_date else "test"
        if reference is None or original is None:
            missing = [name for name, value in (("modis", reference), ("viirs", original)) if value is None]
            skipped.append({"date": current.isoformat(), "split": split, "missing": missing})
        else:
            pairs.append({"date": current.isoformat(), "split": split,
                          "reference": reference, "original": original, "calibrated": None})

    input_windows = report.get("input_windows", [])
    if not isinstance(input_windows, list):
        raise ValueError("input_windows must be a list.")
    window_keys = set()
    for window in input_windows:
        if not isinstance(window, dict) or window.get("source_code") not in _SOURCES:
            raise ValueError("input_windows contains an incompatible source.")
        day = _iso_date(window.get("day"), "input_windows.day")
        if not start <= day <= end:
            raise ValueError("Input window lies outside the report interval.")
        family = "modis" if window["source_code"].startswith("MODIS_") else "viirs"
        key = (day, family)
        if key in window_keys:
            raise ValueError("input_windows duplicates a canonical family/day.")
        window_keys.add(key)

    train = [row for row in pairs if row["split"] == "train"]
    test = [row for row in pairs if row["split"] == "test"]
    reasons = []
    if len(train) < MIN_TRAIN_PAIRS:
        reasons.append("fewer_than_14_training_pairs")
    if len(test) < MIN_TEST_PAIRS:
        reasons.append("fewer_than_7_test_pairs")
    x = [row["original"] for row in train]
    y = [row["reference"] for row in train]
    if train and len(set(x)) < 2:
        reasons.append("training_predictor_is_constant")
    if train and len(set(y)) < 2:
        reasons.append("training_reference_is_constant")
    sum_xx = sum(value * value for value in x)
    if train and sum_xx == 0:
        reasons.append("training_predictor_has_zero_energy")

    result = {
        "status": "insufficient_data" if reasons else "not_improved",
        "exploratory": True,
        "apply_automatically": False,
        "coefficient": None,
        "training_mean_reference": None,
        "model": {
            "candidate": "nonnegative_scale_without_intercept",
            "formula": "MODIS_reference_index = a * NOAA20_active_cells",
            "fit": "a = max(0, sum(train_x * train_y) / sum(train_x ** 2))",
            "model_selected_on_test": False,
            "min_train_pairs": MIN_TRAIN_PAIRS,
            "min_test_pairs": MIN_TEST_PAIRS,
            "thresholds_are_operational_not_statistical_guarantees": True,
            "improvement_rule": "test MAE must beat raw and training-mean benchmarks with numeric tolerance",
        },
        "domain": {
            "scope_id": report["scope_id"], "bbox": list(domain_scope.bbox),
            "date_from": start.isoformat(), "date_to": end.isoformat(),
            "split_date": split_date.isoformat(), "profile_id": PROFILE_ID,
            "reference": "MODIS Terra+Aqua common-grid cell union",
            "predictor": "VIIRS NOAA-20 common-grid active cells",
            "train_paired_from": train[0]["date"] if train else None,
            "train_paired_to": train[-1]["date"] if train else None,
            "test_paired_from": test[0]["date"] if test else None,
            "test_paired_to": test[-1]["date"] if test else None,
        },
        "pairs": {"train": len(train), "test": len(test), "skipped_missing": len(skipped),
                  "requested_days": requested_days},
        "metrics": None,
        "daily": pairs,
        "skipped_days": skipped,
        "reasons": reasons,
        "input_method": deepcopy(report["method"]),
        "input_windows": deepcopy(input_windows),
        "limitations": [
            "MODIS is a comparison reference, not ground truth.",
            "Calibrated values are an index and need not be integer observed cell counts.",
            "A short chronological holdout cannot establish worldwide or cross-season validity.",
            "Shared degree grids do not remove different sensor sensitivities or observation schedules.",
            "Neither observed cells nor this index measure burned area or distinct fires.",
            "No automatic substitution of the observed or global series is performed.",
        ],
    }
    if reasons:
        return result

    try:
        coefficient = max(0.0, sum(a * b for a, b in zip(x, y)) / sum_xx)
        training_mean = fmean(y)
        if not math.isfinite(coefficient) or not math.isfinite(training_mean):
            raise ValueError("Counts exceed the finite numeric range supported by calibration.")
        metrics = {}
        for name, rows in (("train", train), ("test", test)):
            reference = [row["reference"] for row in rows]
            original = [float(row["original"]) for row in rows]
            calibrated = [coefficient * row["original"] for row in rows]
            metrics[name] = {
                "raw": _metrics(reference, original),
                "calibrated": _metrics(reference, calibrated),
                "training_mean": _metrics(reference, [training_mean] * len(rows)),
            }
        for row in pairs:
            row["calibrated"] = coefficient * row["original"]
    except (OverflowError, ZeroDivisionError):
        raise ValueError("Counts exceed the finite numeric range supported by calibration.") from None
    result["coefficient"] = coefficient
    result["training_mean_reference"] = training_mean
    result["metrics"] = metrics
    test_metrics = metrics["test"]
    if (_improves(test_metrics["calibrated"]["mae"], test_metrics["raw"]["mae"])
            and _improves(test_metrics["calibrated"]["mae"], test_metrics["training_mean"]["mae"])):
        result["status"] = "improved_on_holdout"
    return result
