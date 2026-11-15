"""
frontend_api.py — THE /api/... ENDPOINTS OF THE fire-calendar FRONTEND

The frontend (fire-calendar/lib/api.ts) calls exactly these addresses, and the
answers follow fire-calendar/types/api.ts. Extra fields are allowed (the frontend
ignores them); they carry details such as coverage, units and raw values.

    GET /api/meta/                            regions and years
    GET /api/calendar/?region=                year × month heatmap
    GET /api/month/?region=&year=&month=      the days of one month
    GET /api/monthly/?region=&year=           the 12 months of a year for the charts
    GET /api/hotspots/?region=&year=&month=   active 0.1° cells per day for the map
    GET /api/export/?region=&year=&month=     CSV with the individual detections
    GET /api/updates/                         state of the automatic NASA updates

Units (all dates UTC):
  * a day value is the number of 0.1° cells where the sensor detected fire that day;
  * a month value is the sum over its days ("cell-days");
  * `harmonized` / calendar months are on the MODIS scale: MODIS where it observed,
    otherwise VIIRS NOAA-20 × k, but only if k was validated on held-out days;
  * `null` means no data, 0 means data without fires; incomplete months are null.

To show real data, the frontend needs NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
in fire-calendar/.env.local (without it, it shows its built-in demo data).
"""

import csv
import io
import json
from calendar import monthrange
import threading
from collections import OrderedDict
from contextlib import closing
from datetime import date, datetime, timezone
from statistics import median
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse
import numpy as np

import analytics
import config
import reports
import store
import updater
from fires_data import calibrate_calendar

router = APIRouter(prefix="/api", tags=["Frontend (fire-calendar)"])
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
WORLD_VIEW = [-60.0, -180.0, 80.0, 180.0]     # [south, west, north, east] the map shows for "World"

# ---------- Small cache: answers are kept until the data changes (new revision) ----------

_cache, _cache_lock = OrderedDict(), threading.Lock()


def _cached(conn, name, args, build):
    key = (store.revision(conn), name, args)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    value = build()
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > 200:
            _cache.popitem(last=False)
    return value


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _conn():
    return closing(store.connect())


def _today():
    return datetime.now(timezone.utc).date()


def _check_month(year, month):
    if not 2000 <= year <= _today().year:
        raise ValueError(f"Choose a year between 2000 and {_today().year}.")
    if not 1 <= month <= 12:
        raise ValueError("Choose a month between 1 and 12.")


def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


# ---------- MODIS ↔ VIIRS factor per region ----------

def calibration(conn, region):
    """
    The partner's experiment on all days where both sensors have data: k is fitted on
    the first two thirds (MODIS ≈ k × VIIRS NOAA-20) and checked on the last third.
    """
    def build():
        paired = conn.execute("""SELECT MIN(v.day), MAX(v.day) FROM days v JOIN days m
                                 ON m.day = v.day AND m.sensor = 'MODIS' WHERE v.sensor = 'VIIRS'""").fetchone()
        result = {"status": "insufficient_data", "coefficient": None, "r2": None, "validated": False,
                  "train_from": None, "train_to": None, "test_from": None, "test_to": None,
                  "raw_mae": None, "calibrated_mae": None, "baseline_mae": None, "pairs": None}
        if not paired[0] or paired[0] >= paired[1]:
            return result
        start, end = date.fromisoformat(paired[0]), date.fromisoformat(paired[1])
        report = reports.calendar(conn, reports.area(region), start, end)
        experiment = calibrate_calendar(report, analytics.default_split(start, end))
        test = (experiment.get("metrics") or {}).get("test", {})
        domain = experiment["domain"]
        result.update(status=experiment["status"], coefficient=experiment["coefficient"],
                      validated=experiment["status"] == "improved_on_holdout",
                      r2=test.get("calibrated", {}).get("r2"),
                      raw_mae=test.get("raw", {}).get("mae"), calibrated_mae=test.get("calibrated", {}).get("mae"),
                      baseline_mae=test.get("training_mean", {}).get("mae"), pairs=experiment["pairs"],
                      train_from=domain["train_paired_from"], train_to=domain["train_paired_to"],
                      test_from=domain["test_paired_from"], test_to=domain["test_paired_to"])
        for key in ("r2", "raw_mae", "calibrated_mae", "baseline_mae", "coefficient"):
            if result[key] is not None:
                result[key] = round(result[key], 4)
        return result
    return _cached(conn, "calibration", (region,), build)


def _harmonized(row, k):
    """A day on the MODIS scale: MODIS, else k × VIIRS (validated k only), else None."""
    if row is None:
        return None, None
    if row["modis_cells"] is not None:
        return row["modis_cells"], "MODIS"
    if k is not None and row["viirs_cells"] is not None:
        return round(k * row["viirs_cells"]), "VIIRS_NOAA20 x k"
    return None, None


def _harmonization_info(cal):
    return {"method": "MODIS Terra+Aqua active 0.1° cells; days without MODIS use k × VIIRS NOAA-20 "
                      "only when k was validated on held-out days",
            "status": "validated" if cal["validated"] else "draft",
            "r2": cal["r2"], "coefficient": cal["coefficient"], "experiment_status": cal["status"],
            "fit_period": [cal["train_from"], cal["train_to"]],
            "holdout_period": [cal["test_from"], cal["test_to"]],
            "holdout_mae": {"raw_viirs": cal["raw_mae"], "scaled_viirs": cal["calibrated_mae"],
                            "training_mean_baseline": cal["baseline_mae"]}}


# ---------- Endpoints ----------

@router.get("/meta/", summary="Regions and years")
@router.get("/meta", include_in_schema=False)
def meta():
    regions = []
    for key, info in config.REGIONS.items():
        if info["bbox"] is None:
            bbox = WORLD_VIEW
        else:
            west, south, east, north = info["bbox"]
            bbox = [south, west, north, east]          # the frontend's order: [south, west, north, east]
        regions.append({"id": key, "name": info["name"], "bbox": bbox})
    with _conn() as conn:
        coverage = store.coverage(conn)
    first = min((v["first_day"] for v in coverage.values()), default=None)
    last = max((v["last_day"] for v in coverage.values()), default=None)
    years = list(range(int(first[:4]), int(last[:4]) + 1)) if first else []
    return {"regions": regions, "years": years, "data": coverage, "time_basis": "UTC",
            "sensors": {"modis": "MODIS Terra + Aqua", "viirs": "VIIRS NOAA-20"}}


@router.get("/calendar/", summary="Year × month heatmap")
@router.get("/calendar", include_in_schema=False)
def calendar(region: str = "world"):
    reports.area(region)
    with _conn() as conn:
        def build():
            cal = calibration(conn, region)
            k = cal["coefficient"] if cal["validated"] else None
            rows = store.region_day_rows(conn, region, "2000-01-01", "2999-12-31")
            stored_months = store.region_month_rows(conn, region, "2000-01", "2999-12")
            coverage = store.coverage(conn)
            if not coverage:
                return {"region": region, "years": [], "median": [None] * 12,
                        "harmonization": _harmonization_info(cal)}
            first_year = int(min(v["first_day"] for v in coverage.values())[:4])
            last_year = int(max(v["last_day"] for v in coverage.values())[:4])
            today = _today().isoformat()
            years = []
            for year in range(first_year, last_year + 1):
                item = {"year": year, "months": [], "complete": [], "modis": [], "viirs": []}
                for month in range(1, 13):
                    key = f"{year}-{month:02d}"
                    days = store.month_days(key)
                    values = [_harmonized(rows.get(d), k)[0] for d in days]
                    complete = days[-1] < today and all(v is not None for v in values)
                    item["months"].append(sum(values) if complete else None)
                    item["complete"].append(complete)
                    for sensor in store.SENSORS:
                        m = stored_months.get((key, sensor))
                        full = m is not None and m["loaded_days"] == len(days)
                        item[store.CHANNEL[sensor]].append(m["cell_days"] if full else None)
                years.append(item)
            medians = []
            for month in range(12):
                values = [y["months"][month] for y in years if y["months"][month] is not None]
                medians.append(round(median(values)) if len(values) >= 3 else None)
            return {"region": region, "years": years, "median": medians,
                    "harmonization": _harmonization_info(cal),
                    "unit": "active cell-days per month on the MODIS scale",
                    "note": "Only complete months have a value; null means missing or incomplete data. "
                            "The median needs at least 3 complete years of that month."}
        return _cached(conn, "calendar", (region,), build)


@router.get("/month/", summary="The days of one month")
@router.get("/month", include_in_schema=False)
def month(region: str = "world", year: int = 2024, month: int = 8):
    _check_month(year, month)
    where = reports.area(region)
    with _conn() as conn:
        def build():
            first, last = _month_bounds(year, month)
            cal = calibration(conn, region)
            k = cal["coefficient"] if cal["validated"] else None
            rows = store.region_day_rows(conn, region, first, last)
            days = []
            for d in store.month_days(f"{year}-{month:02d}"):
                row = rows.get(d)
                value, source = _harmonized(row, k)
                days.append({"date": d,
                             "modis": None if row is None else row["modis_cells"],
                             "viirs": None if row is None else row["viirs_cells"],
                             "harmonized": value, "harmonized_source": source,
                             "modis_observations": None if row is None else row["modis_obs"],
                             "viirs_observations": None if row is None else row["viirs_obs"],
                             "modis_product": None if row is None else row["modis_product"],
                             "viirs_product": None if row is None else row["viirs_product"]})
            coverage = {ch: {"loaded_days": sum(1 for x in days if x[ch] is not None), "requested_days": len(days)}
                        for ch in ("modis", "viirs")}
            return {"region": region, "year": year, "month": month, "days": days, "coverage": coverage,
                    "bbox": where["bbox"], "unit": "active 0.1° cells per UTC day",
                    "note": "modis and viirs are observed values (VIIRS = NOAA-20, not scaled); "
                            "harmonized is on the MODIS scale. null = no data."}
        return _cached(conn, "month", (region, year, month), build)


@router.get("/monthly/", summary="The 12 months of a year for the charts")
@router.get("/monthly", include_in_schema=False)
def monthly(region: str = "world", year: int = 2024):
    _check_month(year, 1)
    where = reports.area(region)
    with _conn() as conn:
        def build():
            cal = calibration(conn, region)
            k = cal["coefficient"]
            report = reports.monthly(conn, where, date(year, 1, 1), date(year, 12, 31))
            months = []
            for m in report["months"]:
                mo, vi = m["modis"], m["viirs"]
                mo_ok, vi_ok = mo["status"] == "complete", vi["status"] == "complete"
                months.append({
                    "month": m["month_number"],
                    "modis": mo["active_cell_days"] if mo_ok else None,
                    "viirs": round(k * vi["active_cell_days"]) if vi_ok and k is not None else None,
                    "areaKm2": mo["area_km2"] if mo_ok else None,
                    "frpMean": mo["frp_mean"] if mo_ok else None,
                    "frpMax": mo["frp_max"] if mo_ok else None,
                    # extras
                    "viirs_raw": vi["active_cell_days"] if vi_ok else None,
                    "areaViirsKm2": vi["area_km2"] if vi_ok else None,
                    "areaCellDaysKm2": mo["cell_day_area_km2"] if mo_ok else None,
                    "frpViirsMean": vi["frp_mean"] if vi_ok else None,
                    "frpViirsMax": vi["frp_max"] if vi_ok else None,
                    "modis_partial": mo["active_cell_days"] if mo["status"] == "partial" else None,
                    "viirs_raw_partial": vi["active_cell_days"] if vi["status"] == "partial" else None,
                    "coverage": {"modis": {"status": mo["status"], "loaded_days": mo["loaded_days"], "days": m["days"]},
                                 "viirs": {"status": vi["status"], "loaded_days": vi["loaded_days"], "days": m["days"]}},
                })
            return {"region": region, "year": year, "months": months,
                    "viirs_scale": {"coefficient": k, "status": cal["status"],
                                    "note": "viirs = VIIRS NOAA-20 cell-days × k (MODIS scale); viirs_raw is unscaled"},
                    "units": {"modis": "active cell-days", "areaKm2": "km² of distinct 0.1° cells active at least "
                              "once in the month (MODIS); not burned area", "frpMean": "MW, mean over MODIS "
                              "detections with FRP", "frpMax": "MW, strongest MODIS detection"},
                    "note": "Only complete months have values; partial months are in *_partial fields."}
        return _cached(conn, "monthly", (region, year), build)


@router.get("/hotspots/", summary="Active 0.1° cells per day for the map")
@router.get("/hotspots", include_in_schema=False)
def hotspots(region: str = "world", year: int = 2024, month: int = 8, day: date | None = None,
             sensor: Literal["MODIS", "VIIRS"] | None = None,
             limit: Annotated[int, Query(ge=1, le=config.MAX_HOTSPOTS)] = config.MAX_HOTSPOTS):
    """
    One point per active 0.1° cell and day (at the cell centre). seenBy says which sensor
    detected fire there that day; frp is the strongest detection in the cell (MW).
    Large selections are thinned per day to the strongest cells: `total` and `truncated` say so.
    """
    _check_month(year, month)
    where = reports.area(region)
    first, last = _month_bounds(year, month)
    if day is not None and not first <= day <= last:
        raise ValueError("The day must belong to the selected month.")
    with _conn() as conn:
        def build():
            days = [day.isoformat()] if day else store.month_days(f"{year}-{month:02d}")
            per_day = {}
            for d in days:
                cells = reports.day_cells(conn, d, where["cells"])
                if cells is None:
                    continue
                if sensor:
                    keep = cells[f"{sensor.lower()}_obs"] > 0
                    cells = {k: v[keep] for k, v in cells.items()}
                if len(cells["cell"]):
                    per_day[d] = cells
            total = sum(len(c["cell"]) for c in per_day.values())
            share = max(1, limit // max(1, len(per_day))) if total > limit else None
            points = []
            for d, c in per_day.items():
                if share and share < len(c["cell"]):
                    top = np.argpartition(-c["frp_max"], share - 1)[:share]       # the strongest cells of the day
                    order = top[np.argsort(-c["frp_max"][top])]
                else:
                    order = range(len(c["cell"]))
                for i in order:
                    cell, mo, vi = int(c["cell"][i]), int(c["modis_obs"][i]), int(c["viirs_obs"][i])
                    fmax, fn = int(c["frp_max"][i]), int(c["frp_n"][i])
                    lat, lon = reports.cell_center(cell)
                    points.append({"id": f"{d}-{cell}", "lat": lat, "lon": lon, "date": d,
                                   "seenBy": "BOTH" if mo and vi else ("MODIS" if mo else "VIIRS"),
                                   "frp": fmax / 100 if fmax >= 0 else None,
                                   "frp_mean": round(int(c["frp_sum"][i]) / fn / 100, 2) if fn else None,
                                   "modis_observations": mo, "viirs_observations": vi})
            return {"region": region, "from": first.isoformat(), "to": last.isoformat(), "hotspots": points,
                    "total": total, "truncated": len(points) < total, "limit": limit,
                    "unit": "active 0.1° cell per UTC day (cell centre); not individual fires",
                    "note": (f"Showing the {len(points):,} strongest of {total:,} active cell-days."
                             if len(points) < total else "All active cell-days are included.")}
        def encoded():
            return json.dumps(build(), separators=(",", ":")).encode()
        return Response(_cached(conn, "hotspots", (region, year, month, day, sensor, limit), encoded),
                        media_type="application/json")


EXPORT_FIELDS = ["acq_date", "acq_time", "sensor", "satellite", "latitude", "longitude", "frp_mw",
                 "brightness_k", "brightness2_k", "scan_km", "track_km", "confidence", "daynight",
                 "type", "version", "product"]


@router.get("/export/", summary="CSV with the individual detections")
@router.get("/export", include_in_schema=False)
def export(region: str = "world", year: int = 2024, month: int = 8, day: date | None = None,
           sensor: Literal["MODIS", "VIIRS"] | None = None):
    """
    Every detection of the region and month (or one day), as NASA reported it.
    brightness_k is MODIS `brightness` / VIIRS `bright_ti4`; brightness2_k is `bright_t31` / `bright_ti5`.
    """
    _check_month(year, month)
    where = reports.area(region)
    first, last = _month_bounds(year, month)
    if day is not None:
        if not first <= day <= last:
            raise ValueError("The day must belong to the selected month.")
        first = last = day
    with _conn() as conn:
        total = reports.detection_count(conn, where, first, last, sensor)
        products = store.stored_days(conn, first, last)
    if total > config.MAX_EXPORT_ROWS:
        raise ValueError(f"This selection has {total:,} detections; the limit is {config.MAX_EXPORT_ROWS:,}. "
                         "Choose a smaller region, one day or one sensor.")

    def generate():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        with _conn() as conn:
            for row in reports.points(conn, where, first, last, sensor):
                row["product"] = products.get((row["acq_date"], row["sensor"]))
                writer.writerow(row)
                if buffer.tell() > 64_000:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
        yield buffer.getvalue()

    tag = day.isoformat() if day else f"{year}-{month:02d}"
    name = f"firesync_{region}_{tag}{'_' + sensor.lower() if sensor else ''}.csv"
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"',
                                      "X-Total-Rows": str(total)})


@router.get("/updates/", summary="State of the automatic NASA updates")
@router.get("/updates", include_in_schema=False)
def updates():
    with _conn() as conn:
        stored = store.summary(conn)
    return {"stored": stored, "update": updater.status()}
