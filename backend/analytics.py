"""
analytics.py — РАСЧЁТЫ ПОВЕРХ КАЛЕНДАРЯ

Здесь только математика: ни базы, ни HTTP. Поэтому каждую функцию легко
проверить тестом.

  * color levels  — уровни 0..4 для раскраски календаря (как у GitHub);
  * harmonize     — сведение MODIS и VIIRS в один ряд (то, что просит челлендж);
  * anomaly       — сравнение месяца с медианой прошлых лет.
"""

import math
from datetime import date, timedelta
from statistics import median, quantiles

import config  # noqa: F401 — первым: подключает папку data_pipeline с модулем напарника
from fires_data import calibrate_calendar

MIN_HISTORY_YEARS = 3   # для аномалии нужно минимум 3 прошлых года


# ---------- Раскраска календаря ----------

def color_breaks(values):
    """Границы уровней: квартили среди дней, где пожары были (нули не считаем)."""
    positive = sorted(v for v in values if v)
    if len(positive) < 2:
        return positive[:1]
    return [round(q, 2) for q in quantiles(positive, n=4)]


def level(value, breaks):
    """0 — пожаров нет, 1..4 — от слабой активности к сильной, None — нет данных."""
    if value is None:
        return None
    if value == 0:
        return 0
    return 1 + sum(1 for b in breaks if value > b)


def add_daily_levels(report):
    report["color_scale"] = {}
    for channel in ("modis", "viirs"):
        breaks = color_breaks(day[channel]["active_cells"] for day in report["daily"])
        report["color_scale"][channel] = {"unit": "active_cells", "levels": 5, "breaks": breaks}
        for day in report["daily"]:
            day[channel]["level"] = level(day[channel]["active_cells"], breaks)
    return report


def add_monthly_levels(result):
    result["color_scale"] = {}
    for channel in ("modis", "viirs"):
        breaks = color_breaks(m[channel]["active_cell_days"] for m in result["months"])
        result["color_scale"][channel] = {"unit": "active_cell_days", "levels": 5, "breaks": breaks}
        for month in result["months"]:
            month[channel]["level"] = level(month[channel]["active_cell_days"], breaks)
    return result


# ---------- Гармонизация MODIS ↔ VIIRS ----------

def default_split(start, end):
    """Первые 2/3 периода — обучение, последняя треть — проверка."""
    days = (end - start).days + 1
    return start + timedelta(days=math.ceil(days * 2 / 3))


def harmonize(report, split_date):
    """
    1) Эксперимент напарника: на днях ДО split_date подбирается коэффициент k
       такой, что MODIS ≈ k × VIIRS; на днях ПОСЛЕ проверяется, насколько он точен.
    2) Из него строим единый ряд «в единицах MODIS»: где есть MODIS — берём MODIS,
       где есть только VIIRS — берём k × VIIRS. Источник каждого значения подписан.
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
    # Объёмные служебные поля эксперимента фронту не нужны
    for key in ("input_windows", "input_method", "daily"):
        experiment.pop(key, None)
    return {"summary": summary, "series": series, "experiment": experiment}


# ---------- Аномалия: месяц против прошлых лет ----------

def anomaly(months, year, month, series):
    """
    months — результат grid_index.monthly() за несколько лет.
    Берём только полностью загруженные месяцы, чтобы не сравнивать неполные данные.
    """
    values = {m["year"]: m[series]["active_cell_days"] for m in months
              if m["month_number"] == month and m[series]["status"] == "complete"}
    current = values.get(year)
    history = {y: v for y, v in values.items() if y != year}
    result = {"year": year, "month": month, "series": series, "unit": "active_cell_days",
              "value": current, "years_available": sorted(values),
              "history": [{"year": y, "value": v} for y, v in sorted(history.items())]}

    if current is None:
        result.update(status="month_not_loaded",
                      message="Этот месяц загружен не полностью — сравнивать нечего.")
        return result
    if len(history) < MIN_HISTORY_YEARS:
        result.update(status="insufficient_history",
                      message=f"Для нормы нужно минимум {MIN_HISTORY_YEARS} прошлых года с полными данными, "
                              f"а есть {len(history)}. Нужно догрузить историю.")
        return result

    normal = median(history.values())
    percent = round((current - normal) / normal * 100, 1) if normal else None
    rank = 1 + sum(1 for v in history.values() if v > current)
    if percent is None:
        verdict = "above_normal" if current > 0 else "normal"
    elif percent >= 25:
        verdict = "above_normal"
    elif percent <= -25:
        verdict = "below_normal"
    else:
        verdict = "normal"
    result.update(status="ok", median=normal, anomaly_percent=percent, verdict=verdict,
                  rank=rank, rank_of=len(values),
                  message=f"{rank}-е место из {len(values)} лет по активности в этом месяце.")
    return result


def full_years(first_day, last_day):
    """Диапазон с 1 января первого года по 31 декабря последнего."""
    first, last = date.fromisoformat(first_day), date.fromisoformat(last_day)
    return date(first.year, 1, 1), date(last.year, 12, 31)
