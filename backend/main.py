"""
main.py — FireSync API

Run:            `python -m uvicorn main:app --reload`

Interactive documentation: <http://localhost:8000/docs> (every request can be tried with the buttons).

Who is responsible for what:

* `main.py` — the app, the general endpoints (/calendar, /cells, ...), errors, CORS
* `frontend_api.py` — the /api/... endpoints that the fire-calendar frontend calls
* `store.py` — the database (data/firesync.sqlite3): all MODIS + VIIRS NOAA-20 detections
* `reports.py` — calendar, months, map cells and points computed from the database
* `importer.py` — loads the 2000–2025 archive CSV into the database (run once)
* `updater.py` — downloads new days from the NASA FIRMS API in the background
* `analytics.py` — math: coloring, MODIS/VIIRS harmonization, anomalies
* `config.py` — settings
"""

import csv
import io
import time
from contextlib import asynccontextmanager, closing
from datetime import date
from itertools import islice
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

import config  # first: adds the data_pipeline folder with the partner's module
import analytics
import frontend_api
import reports
import store
import updater
from fires_data.errors import PipelineError, StorageError

DESCRIPTION = """
**FireSync** — a fire-activity calendar from the NASA **MODIS** (Terra + Aqua) and **VIIRS NOAA-20**
satellites, placed on one common 0.1° grid. Data: the 2000–2025 archive plus automatic daily NASA FIRMS updates.

**Where to start**
1. `/api/...` — the endpoints the fire-calendar frontend uses (`/api/meta/`, `/api/calendar/`, ...).
2. `/regions` — ready-made regions; or give your own bounds `west, south, east, north`.
3. `/calendar` — activity per day, `/calendar/monthly` — per month, `/cells` — map layer (GeoJSON).
4. `/status` — what is stored and what the automatic NASA update is doing.

**Unit** — an "active cell": a 0.1° cell (~10 km) where a satellite detected at least one fire during a
UTC day. It is not the number of fires and not the burned area.
All dates are UTC. `null` means "no data for this day", not "no fires".
"""

TAGS = [
    {"name": "Frontend (fire-calendar)", "description": "What the website calls"},
    {"name": "System", "description": "Is the server alive, what data is stored"},
    {"name": "Regions", "description": "Ready-made areas"},
    {"name": "Calendar", "description": "Activity per day and month"},
    {"name": "Map", "description": "Cells and individual detections for a map"},
    {"name": "Science", "description": "MODIS ↔ VIIRS harmonization and anomalies"},
    {"name": "Export", "description": "Download data as a file"},
]


@asynccontextmanager
async def lifespan(app):
    """Startup: the background thread that downloads new NASA days (see updater.py)."""
    updater.start_background()
    yield


app = FastAPI(title="FireSync API", version="2.0.0", description=DESCRIPTION,
              openapi_tags=TAGS, lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1000)   # large responses are compressed 5–10 times
app.add_middleware(CORSMiddleware, allow_origins=config.FRONTEND_URLS, allow_methods=["GET"],
                   allow_headers=["*"], expose_headers=["X-Process-Time-Ms", "Content-Disposition", "X-Total-Rows"])
app.include_router(frontend_api.router)


@app.middleware("http")
async def process_time(request: Request, call_next):
    """Add to every response how many milliseconds it took to compute."""
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


# ---------- Errors always use one format: {"error": "text"} ----------

def _error(status, message, **extra):
    return JSONResponse(status_code=status, content={"error": message, **extra})


@app.exception_handler(ValueError)
async def bad_request(request: Request, exc: ValueError):
    """ValueError (a violated rule, such as reversed dates) → HTTP 400."""
    return _error(400, str(exc))


@app.exception_handler(RequestValidationError)
async def invalid_params(request: Request, exc: RequestValidationError):
    """Malformed parameter (not a date, out of range) → HTTP 422 with a `details` list of `{param, message}`."""
    details = [{"param": str(err["loc"][-1]), "message": err["msg"]} for err in exc.errors()]
    text = "; ".join(f"{d['param']}: {d['message']}" for d in details)
    return _error(422, f"Invalid request parameters: {text}", details=details)


@app.exception_handler(store.StoreNotReady)
async def store_not_ready(request: Request, exc: store.StoreNotReady):
    """The database has not been created yet → HTTP 503."""
    response = _error(503, str(exc))
    response.headers["Retry-After"] = "60"
    return response


@app.exception_handler(StorageError)
async def storage_error(request: Request, exc: StorageError):
    return _error(503, "The database is not available. Check FIRESYNC_DB_PATH and restart.")


@app.exception_handler(PipelineError)
async def pipeline_error(request: Request, exc: PipelineError):
    return _error(500, str(exc))


# ---------- Common request parameters ----------

class Period:
    """Period: date_from and date_to inclusive, in UTC."""

    def __init__(
        self,
        date_from: Annotated[date, Query(description="First day of the period (UTC), YYYY-MM-DD",
                                         openapi_examples={"aug": {"summary": "August 2024", "value": "2024-08-01"}})],
        date_to: Annotated[date, Query(description="Last day of the period, inclusive",
                                       openapi_examples={"aug": {"summary": "August 2024", "value": "2024-08-31"}})],
    ):
        if date_to < date_from:
            raise ValueError("date_to is earlier than date_from.")
        self.start, self.end = date_from, date_to
        self.days = (date_to - date_from).days + 1

    def limit(self, max_days):
        """Reject the period if it is longer than `max_days` (raises ValueError → HTTP 400). Returns self."""
        if self.days > max_days:
            raise ValueError(f"The period is too long: {self.days} days. This request allows at most {max_days}.")
        return self


class Area:
    """Area: a ready-made region OR four boundaries. Nothing given — the whole world."""

    def __init__(
        self,
        region: Annotated[str | None, Query(description="Ready-made region from `/regions`",
                                            openapi_examples={"ukraine": {"summary": "Ukraine",
                                                                          "value": "ukraine"}})] = None,
        west: Annotated[float | None, Query(ge=-180, le=180, description="Western boundary (longitude)")] = None,
        south: Annotated[float | None, Query(ge=-90, le=90, description="Southern boundary (latitude)")] = None,
        east: Annotated[float | None, Query(ge=-180, le=180, description="Eastern boundary (longitude)")] = None,
        north: Annotated[float | None, Query(ge=-90, le=90, description="Northern boundary (latitude)")] = None,
    ):
        corners = (west, south, east, north)
        given = [v is not None for v in corners]
        if region is not None and any(given):
            raise ValueError("Use either region or west/south/east/north, not both.")
        if any(given) and not all(given):
            raise ValueError("All four bounds are required: west, south, east, north (or none of them).")
        self.region = region if region is not None else (None if all(given) else "world")
        self.bbox = corners if all(given) else None
        self.where = reports.area(self.region, self.bbox)


def _area_info(area):
    return {"region": area.region, "requested_bbox": list(area.bbox) if area.bbox else None,
            "bbox": area.where["bbox"]}


def _db():
    return closing(store.connect())


# ---------- System ----------

@app.get("/", include_in_schema=False)
def root():
    """Redirect to the interactive documentation at `/docs`."""
    return RedirectResponse("/docs")


@app.get("/health", tags=["System"], summary="Is the server alive?")
def health():
    """Liveness check: returns `{"status": "ok"}` if the server is running. Does not touch the database."""
    return {"status": "ok"}


@app.get("/status", tags=["System"], summary="What data is stored and how fresh it is")
def status():
    """
    Stored days per sensor (first/last day, NRT days, detections), the archive import,
    and the state of the automatic NASA update.
    """
    try:
        with _db() as conn:
            stored = store.summary(conn)
    except store.StoreNotReady as exc:
        return {"status": "no_database", "message": str(exc), "update": updater.status(), "version": app.version}
    return {"status": "ok", "data": stored["coverage"], "database": stored,
            "update": updater.status(), "version": app.version}


# ---------- Regions ----------

@app.get("/regions", tags=["Regions"], summary="Ready-made regions")
def regions():
    """The ready-made regions from `config.REGIONS`: id, name, bbox `[west, south, east, north]` (null = world)."""
    return [{"id": key, "name": info["name"], "bbox": info["bbox"]} for key, info in config.REGIONS.items()]


# ---------- Calendar ----------

def _custom_limit(area, period, max_days):
    period.limit(max_days if area.region else min(max_days, config.MAX_CUSTOM_AREA_DAYS))


@app.get("/calendar", tags=["Calendar"], summary="Activity per day: MODIS and VIIRS")
def calendar(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    include_windows: Annotated[bool, Query(description="Add the list of stored NASA day blocks")] = False,
):
    """
    For each day: how many 0.1° cells were active according to MODIS (Terra+Aqua)
    and VIIRS NOAA-20, how many cells both saw, and a level 0–4 for coloring.
    """
    _custom_limit(area, period, config.MAX_CALENDAR_DAYS)
    with _db() as conn:
        report = reports.calendar(conn, area.where, period.start, period.end)
    if not include_windows:
        report.pop("input_windows", None)
    report["area"] = _area_info(area)
    return analytics.add_daily_levels(report)


@app.get("/calendar/monthly", tags=["Calendar"], summary="Activity per month (for a year × month calendar)")
def calendar_monthly(period: Annotated[Period, Depends()], area: Annotated[Area, Depends()]):
    """
    For each month: the sum of active cells over the days ("cell-days"), detections, the area of the distinct
    active cells, FRP and completeness: `complete` — all days stored, `partial` — some, `missing` — none.
    """
    _custom_limit(area, period, 40 * 366)
    with _db() as conn:
        result = reports.monthly(conn, area.where, period.start, period.end)
    result["area"] = _area_info(area)
    return analytics.add_monthly_levels(result)


# ---------- Map ----------

RESOLUTIONS = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0)


def _auto_resolution(bbox):
    width, height = (360, 180) if bbox is None else (bbox[2] - bbox[0], bbox[3] - bbox[1])
    span = max(width, height)
    return 0.1 if span <= 10 else 0.2 if span <= 30 else 0.5 if span <= 90 else 1.0


@app.get("/cells", tags=["Map"], summary="Active cells for a map (GeoJSON)")
def cells(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    resolution: Annotated[float | None, Query(
        description="Cell size in degrees: 0.1, 0.2, 0.5, 1, 2 or 5. Not given — chosen automatically")] = None,
):
    """
    Points at cell centers with the number of active days — a ready-made layer for MapLibre/Leaflet
    (e.g. a heatmap). The most active cells come first. Up to 92 days per request.
    """
    period.limit(config.MAX_MAP_DAYS)
    bbox = None if area.where["cells"] is None else area.where["bbox"]
    resolution = resolution or _auto_resolution(bbox)
    if not any(abs(resolution - r) < 1e-9 for r in RESOLUTIONS):
        raise ValueError(f"resolution must be one of {list(RESOLUTIONS)}.")
    with _db() as conn:
        found = reports.map_cells(conn, area.where, period.start, period.end,
                                  step=round(resolution * 10), limit=config.MAX_MAP_CELLS)
    breaks = analytics.color_breaks(c["active_days"] for c in found["cells"])
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
        "properties": {"active_days": c["active_days"],
                       "modis_cell_days": c["modis_cell_days"], "viirs_cell_days": c["viirs_cell_days"],
                       "modis_observations": c["modis_observations"], "viirs_observations": c["viirs_observations"],
                       "level": analytics.level(c["active_days"], breaks)},
    } for c in found["cells"]]
    return {
        "type": "FeatureCollection",
        "bbox": area.where["bbox"],
        "features": features,
        "meta": {"date_from": period.start.isoformat(), "date_to": period.end.isoformat(),
                 "resolution_degrees": resolution, "cells": len(features), "truncated": found["truncated"],
                 "color_scale": {"unit": "active_days", "levels": 5, "breaks": breaks},
                 "area": _area_info(area)},
    }


@app.get("/points", tags=["Map"], summary="Individual fire detections (up to 7 days)")
def points(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    sensor: Annotated[Literal["MODIS", "VIIRS"] | None, Query(description="Only one sensor")] = None,
    limit: Annotated[int, Query(ge=1, le=config.MAX_POINTS_PER_PAGE)] = 1000,
    offset: Annotated[int, Query(ge=0, description="How many points to skip (next page)")] = 0,
    format: Annotated[Literal["json", "geojson"], Query(description="json — a list, geojson — a map layer")] = "json",
):
    """Detections as NASA reported them: time, coordinates, satellite, power (FRP). Returned in pages."""
    period.limit(config.MAX_POINT_DAYS)
    with _db() as conn:
        rows = list(islice(reports.points(conn, area.where, period.start, period.end, sensor),
                           offset, offset + limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    page = {"limit": limit, "offset": offset, "count": len(rows), "has_more": more,
            "next_offset": offset + limit if more else None}
    if format == "geojson":
        return {"type": "FeatureCollection", "meta": page, "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
             "properties": r} for r in rows]}
    return {**page, "points": rows}


# ---------- Science ----------

@app.get("/harmonization", tags=["Science"], summary="Merging MODIS and VIIRS into one series")
def harmonization(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    split_date: Annotated[date | None, Query(
        description="First test day. The coefficient is fitted before it and checked after it. "
                    "Not given — the last third of the period")] = None,
):
    """
    The main task of the challenge. We fit a coefficient k (MODIS ≈ k × VIIRS) on one part of the
    days and honestly check it on other days that the model has not seen.
    `series` is a single series where it does not matter which satellite supplied the data.
    """
    _custom_limit(area, period, config.MAX_CALENDAR_DAYS)
    split = split_date or analytics.default_split(period.start, period.end)
    if not period.start < split <= period.end:
        raise ValueError("split_date must lie inside the period and not on its first day.")
    with _db() as conn:
        report = reports.calendar(conn, area.where, period.start, period.end)
    result = analytics.harmonize(report, split)
    result["area"] = _area_info(area)
    result["date_from"], result["date_to"] = period.start.isoformat(), period.end.isoformat()
    return result


@app.get("/anomaly", tags=["Science"], summary="A month against the norm of earlier years")
def anomaly(
    year: Annotated[int, Query(ge=2000, le=2100, openapi_examples={"y": {"summary": "2024", "value": 2024}})],
    month: Annotated[int, Query(ge=1, le=12, openapi_examples={"m": {"summary": "August", "value": 8}})],
    area: Annotated[Area, Depends()],
    series: Annotated[Literal["modis", "viirs"], Query(
        description="Which sensor to compare (MODIS has the longest history)")] = "modis",
):
    """
    Compares the chosen month with the median of the same month in other years:
    by how many percent it is above or below normal and what rank it has among all years.
    """
    if area.region is None:
        raise ValueError("The anomaly needs a ready-made region (many years of data).")
    with _db() as conn:
        coverage = store.coverage(conn)
        if not coverage:
            raise ValueError("Nothing is stored yet.")
        start, end = analytics.full_years(min(v["first_day"] for v in coverage.values()),
                                          max(v["last_day"] for v in coverage.values()))
        months = reports.monthly(conn, area.where, start, end)
    result = analytics.anomaly(months["months"], year, month, series)
    result["area"] = _area_info(area)
    return result


# ---------- Export ----------

POINT_FIELDS = ["observed_at", "acq_date", "acq_time", "sensor", "satellite", "latitude", "longitude",
                "frp_mw", "brightness_k", "brightness2_k", "scan_km", "track_km", "confidence",
                "daynight", "type", "version"]


@app.get("/export.csv", tags=["Export"], summary="Download fire detections as CSV (up to 31 days)")
def export_csv(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    sensor: Annotated[Literal["MODIS", "VIIRS"] | None, Query(description="Only one sensor")] = None,
):
    """The file is streamed: the download starts immediately, the server does not hold it in memory."""
    period.limit(config.MAX_EXPORT_DAYS)
    with _db() as conn:
        total = reports.detection_count(conn, area.where, period.start, period.end, sensor)
    if total > config.MAX_EXPORT_ROWS:
        raise ValueError(f"Too many detections ({total:,}; the limit is {config.MAX_EXPORT_ROWS:,}). "
                         "Choose a smaller area or a shorter period.")

    def generate():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=POINT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        with _db() as conn:
            for row in reports.points(conn, area.where, period.start, period.end, sensor):
                writer.writerow(row)
                if buffer.tell() > 64_000:      # send in chunks of roughly 64 KB
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
        yield buffer.getvalue()

    name = f"firesync_{area.region or 'area'}_{period.start}_{period.end}.csv"
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"',
                                      "X-Total-Rows": str(total)})
