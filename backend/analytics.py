"""
analytics.py — CALCULATIONS ON TOP OF THE CALENDAR

Only math lives here: no database, no HTTP. That makes every function easy
to cover with a test.

  * color levels  — levels 0..4 for coloring the calendar (like GitHub);
  * harmonize     — merging MODIS and VIIRS into one series (what the challenge asks for);
  * anomaly       — comparing a month with the median of previous years.
"""

import math
from datetime import date, timedelta
from statistics import median, quantiles

import config  # noqa: F401 — must come first: adds the data_pipeline folder with the partner's module
from fires_data import calibrate_calendar

MIN_HISTORY_YEARS = 3   # an anomaly needs at least 3 previous years


# ---------- Calendar coloring ----------

def color_breaks(values):
    """Level boundaries: quartiles among days that had fires (zeros are not counted)."""
    positive = sorted(v for v in values if v)
    if len(positive) < 2:
        return positive[:1]
    return [round(q, 2) for q in quantiles(positive, n=4)]


def level(value, breaks):
    """0 — no fires, 1..4 — from weak to strong activity, None — no data."""
    if value is None:
        return None
    if value == 0:
        return 0
    return 1 + sum(1 for b in breaks if value > b)


def add_daily_levels(report):
    """
    Add a `color_scale` and a 0–4 `level` to every day of a calendar report.

    Levels are computed separately for MODIS and VIIRS from the quartiles of the days in the report
    (see `color_breaks`). The report is modified in place and returned.
    """
    report["color_scale"] = {}
    for channel in ("modis", "viirs"):
        breaks = color_breaks(day[channel]["active_cells"] for day in report["daily"])
        report["color_scale"][channel] = {"unit": "active_cells", "levels": 5, "breaks": breaks}
        for day in report["daily"]:
            day[channel]["level"] = level(day[channel]["active_cells"], breaks)
    return report


def add_monthly_levels(result):
    """
    Add a `color_scale` and a 0–4 `level` to every month of a monthly report.

    Works like `add_daily_levels`, but on `active_cell_days` per month. The result is modified in place
    and returned.
    """
    result["color_scale"] = {}
    for channel in ("modis", "viirs"):
        breaks = color_breaks(m[channel]["active_cell_days"] for m in result["months"])
        result["color_scale"][channel] = {"unit": "active_cell_days", "levels": 5, "breaks": breaks}
        for month in result["months"]:
            month[channel]["level"] = level(month[channel]["active_cell_days"], breaks)
    return result


# ---------- MODIS ↔ VIIRS harmonization ----------

def default_split(start, end):
    """First 2/3 of the period is for training, the last third is for testing."""
    days = (end - start).days + 1
    return start + timedelta(days=math.ceil(days * 2 / 3))


def harmonize(report, split_date):
    """
    1) The partner's experiment: on days BEFORE split_date a coefficient k is fitted
       such that MODIS ≈ k × VIIRS; on days AFTER it, we check how accurate it is.
    2) From it we build a single series "in MODIS units": where MODIS exists we use MODIS,
       where only VIIRS exists we use k × VIIRS. The source of each value is labeled.
    """
    experiment = calibrate_calendar(report, split_date)
    k = experiment.get("coefficient")
    split_text = split_date.isoformat()

    series = []
    for day in report["daily"]:
        modis = day["modis"]["active_cells"]
        viirs = day["viirs"]["active_cells"]
        scaled = round(k * viirs, 2) if k is not None and viirs is not None else None
        if modis is not None:
            value, source = modis, "MODIS"
        elif scaled is not None:
            value, source = scaled, "VIIRS_NOAA20 x k"
        else:
            value, source = None, None
        series.append({"date": day["date"], "split": "train" if day["date"] < split_text else "test",
                       "modis": modis, "viirs": viirs, "viirs_scaled": scaled,
                       "harmonized": value, "harmonized_source": source})

    summary = {"status": experiment["status"], "coefficient": k,
               "formula": "MODIS ≈ k × VIIRS NOAA-20 (active 0.1° cells per day)",
               "split_date": split_text, "pairs": experiment["pairs"], "reasons": experiment["reasons"]}
    metrics = experiment.get("metrics")
    if metrics:
        raw, calibrated = metrics["test"]["raw"], metrics["test"]["calibrated"]
        summary.update({
            "test_mae_raw": round(raw["mae"], 2),
            "test_mae_harmonized": round(calibrated["mae"], 2),
            "error_reduction_percent": round((1 - calibrated["mae"] / raw["mae"]) * 100, 1) if raw["mae"] else None,
            "test_r2_harmonized": None if calibrated["r2"] is None else round(calibrated["r2"], 3),
        })
    # The frontend does not need the bulky internal fields of the experiment
    for key in ("input_windows", "input_method", "daily"):
        experiment.pop(key, None)
    return {"summary": summary, "series": series, "experiment": experiment}


# ---------- Anomaly: a month versus previous years ----------

def anomaly(months, year, month, series):
    """
    months — the `months` list of reports.monthly() over several years.
    We take only fully loaded months so that incomplete data is not compared.
    """
    values = {m["year"]: m[series]["active_cell_days"] for m in months
              if m["month_number"] == month and m[series]["status"] == "complete"}
    current = values.get(year)
    history = {y: v for y, v in values.items() if y < year}   # the norm uses earlier years only
    result = {"year": year, "month": month, "series": series, "unit": "active_cell_days",
              "value": current, "years_available": sorted(values),
              "history": [{"year": y, "value": v} for y, v in sorted(history.items())]}

    if current is None:
        result.update(status="month_not_loaded",
                      message="This month is not fully stored, so there is nothing to compare.")
        return result
    if len(history) < MIN_HISTORY_YEARS:
        result.update(status="insufficient_history",
                      message=f"A norm needs at least {MIN_HISTORY_YEARS} other years with complete data for "
                              f"this month; there are {len(history)}.")
        return result

    normal = median(history.values())
    percent = round((current - normal) / normal * 100, 1) if normal else None
    rank = 1 + sum(1 for v in history.values() if v > current)   # among this year and the earlier ones
    if percent is None:
        verdict = "above_normal" if current > 0 else "normal"
    elif percent >= 25:
        verdict = "above_normal"
    elif percent <= -25:
        verdict = "below_normal"
    else:
        verdict = "normal"
    result.update(status="ok", median=normal, anomaly_percent=percent, verdict=verdict,
                  rank=rank, rank_of=len(history) + 1,
                  message=f"Rank {rank} of {len(history) + 1} years by activity in this month.")
    return result


def full_years(first_day, last_day):
    """Range from January 1 of the first year to December 31 of the last year."""
    first, last = date.fromisoformat(first_day), date.fromisoformat(last_day)
    return date(first.year, 1, 1), date(last.year, 12, 31)
