"""
main.py — API FireSync

Запуск:        uvicorn main:app --reload
Документация:  http://localhost:8000/docs   (любой запрос можно попробовать кнопками)

Кто за что отвечает:
  main.py        — адреса API: принимают параметры, проверяют, отдают JSON
  grid_index.py  — быстрый индекс календаря (доли секунды вместо ~25 секунд)
  db.py          — точки пожаров и эталонный расчёт прямо из базы напарника
  analytics.py   — математика: раскраска, гармонизация MODIS/VIIRS, аномалии
  config.py      — настройки
"""

import csv
import io
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

import config  # первым: подключает папку data_pipeline с модулем напарника
import analytics
import db
import grid_index
from fires_data.errors import PipelineError, StorageError

DESCRIPTION = """
**FireSync** — календарь пожарной активности по спутникам NASA **MODIS** и **VIIRS**,
сведённым на общую сетку 0.1°.

**С чего начать**
1. `/regions` — готовые регионы; или задайте свои границы `west, south, east, north`.
2. `/calendar` — активность по дням, `/calendar/monthly` — по месяцам.
3. `/cells` — данные для карты (GeoJSON), `/harmonization` — сведение MODIS и VIIRS в один ряд.

**Единица измерения** — «активная клетка»: клетка 0.1° (~10 км), где за сутки спутник
заметил хотя бы один очаг. Это не число пожаров и не площадь гари.
Все даты — UTC. `null` значит «данные за этот день не загружены», а не «пожаров не было».
"""

TAGS = [
    {"name": "Система", "description": "Проверка, что сервер и данные в порядке"},
    {"name": "Регионы", "description": "Готовые области для демо"},
    {"name": "Календарь", "description": "Активность по дням и месяцам"},
    {"name": "Карта", "description": "Клетки и точки пожаров для карты"},
    {"name": "Наука", "description": "Гармонизация MODIS ↔ VIIRS и аномалии"},
    {"name": "Выгрузка", "description": "Скачать данные файлом"},
]


@asynccontextmanager
async def lifespan(app):
    # Фоновый поток: сам замечает новые загрузки из NASA и обновляет индекс
    grid_index.start_auto_refresh(config.AUTO_REFRESH_SECONDS)
    yield


app = FastAPI(title="FireSync API", version="1.0.0", description=DESCRIPTION,
              openapi_tags=TAGS, lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1000)   # большие ответы сжимаются в 5–10 раз
app.add_middleware(CORSMiddleware, allow_origins=config.FRONTEND_URLS, allow_methods=["GET"],
                   allow_headers=["*"], expose_headers=["X-Process-Time-Ms", "Content-Disposition", "X-Total-Rows"])


@app.middleware("http")
async def process_time(request: Request, call_next):
    """В каждый ответ дописываем, сколько миллисекунд он считался."""
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


# ---------- Ошибки всегда в одном формате: {"error": "текст"} ----------

def _error(status, message, **extra):
    return JSONResponse(status_code=status, content={"error": message, **extra})


@app.exception_handler(ValueError)
async def bad_request(request: Request, exc: ValueError):
    return _error(400, str(exc))


@app.exception_handler(RequestValidationError)
async def invalid_params(request: Request, exc: RequestValidationError):
    details = [{"param": str(err["loc"][-1]), "message": err["msg"]} for err in exc.errors()]
    text = "; ".join(f"{d['param']}: {d['message']}" for d in details)
    return _error(422, f"Неверные параметры запроса — {text}", details=details)


@app.exception_handler(grid_index.IndexNotReady)
async def index_not_ready(request: Request, exc: grid_index.IndexNotReady):
    response = _error(503, str(exc))
    response.headers["Retry-After"] = "30"
    return response


@app.exception_handler(StorageError)
async def storage_error(request: Request, exc: StorageError):
    return _error(503, f"База данных недоступна: {exc}")


@app.exception_handler(PipelineError)
async def pipeline_error(request: Request, exc: PipelineError):
    return _error(500, str(exc))


# ---------- Общие параметры запросов ----------

class Period:
    """Период: date_from и date_to включительно, в UTC."""

    def __init__(
        self,
        date_from: Annotated[date, Query(description="Первый день периода (UTC), ГГГГ-ММ-ДД",
                                         openapi_examples={"aug": {"summary": "Август 2024 — загружен целиком",
                                                                   "value": "2024-08-01"}})],
        date_to: Annotated[date, Query(description="Последний день периода включительно",
                                       openapi_examples={"aug": {"summary": "Август 2024",
                                                                 "value": "2024-08-31"}})],
    ):
        if date_to < date_from:
            raise ValueError("date_to раньше, чем date_from.")
        self.start, self.end = date_from, date_to
        self.days = (date_to - date_from).days + 1

    def limit(self, max_days):
        if self.days > max_days:
            raise ValueError(f"Слишком длинный период: {self.days} дн. Для этого запроса максимум {max_days}.")
        return self


class Area:
    """Область: готовый регион ИЛИ четыре границы. Ничего не задано — весь мир."""

    def __init__(
        self,
        region: Annotated[str | None, Query(description="Готовый регион из `/regions`",
                                            openapi_examples={"ukraine": {"summary": "Украина",
                                                                          "value": "ukraine"}})] = None,
        west: Annotated[float | None, Query(ge=-180, le=180, description="Западная граница (долгота)")] = None,
        south: Annotated[float | None, Query(ge=-90, le=90, description="Южная граница (широта)")] = None,
        east: Annotated[float | None, Query(ge=-180, le=180, description="Восточная граница (долгота)")] = None,
        north: Annotated[float | None, Query(ge=-90, le=90, description="Северная граница (широта)")] = None,
    ):
        corners = (west, south, east, north)
        given = [v is not None for v in corners]
        if region is not None:
            if any(given):
                raise ValueError("Укажите либо region, либо west/south/east/north — не одновременно.")
            if region not in config.REGIONS:
                raise ValueError(f"Неизвестный регион '{region}'. Список регионов: /regions")
            info = config.REGIONS[region]
            self.region, self.scope_id = region, info["scope"]
            self.bbox = tuple(info["bbox"]) if info["bbox"] else None
            return
        if any(given) and not all(given):
            raise ValueError("Нужны все четыре границы: west, south, east, north (или ни одной).")
        if all(given) and not (west < east and south < north):
            raise ValueError("Должно быть west < east и south < north (сначала долгота, потом широта).")
        self.region, self.scope_id = None, config.SCOPE_ID
        self.bbox = corners if all(given) else None


def _area_info(area, computed_bbox):
    return {"region": area.region, "scope_id": area.scope_id,
            "requested_bbox": list(area.bbox) if area.bbox else None, "bbox": computed_bbox}


# ---------- Система ----------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health", tags=["Система"], summary="Сервер жив?")
def health():
    return {"status": "ok"}


@app.get("/status", tags=["Система"], summary="Какие данные загружены и насколько они свежие")
def status():
    ready = grid_index.is_ready()
    summary = grid_index.loaded_summary() if ready else None
    return {
        "status": "ok" if ready else "building_index",
        "data": summary["scopes"] if summary else {},
        "index": {"ready": ready,
                  "last_refresh": summary["last_refresh"] if summary else None,
                  "cell_rows": summary["cell_rows"] if summary else None,
                  "size_mb": summary["size_mb"] if summary else None,
                  "auto_refresh": grid_index.auto_refresh_state()},
        "partner_database": db.database_info(),
        "version": app.version,
    }


# ---------- Регионы ----------

@app.get("/regions", tags=["Регионы"], summary="Готовые регионы для демо")
def regions():
    return [{"id": key, "name": info["name"], "bbox": info["bbox"], "scope": info["scope"]}
            for key, info in config.REGIONS.items()]


# ---------- Календарь ----------

@app.get("/calendar", tags=["Календарь"], summary="Активность по дням: MODIS и VIIRS")
def calendar(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    engine: Annotated[Literal["fast", "reference"], Query(
        description="`fast` — наш индекс (мгновенно). `reference` — оригинальный расчёт напарника "
                    "(~25 с, для сверки)")] = "fast",
    include_windows: Annotated[bool, Query(description="Добавить список исходных срезов NASA")] = False,
):
    """
    Для каждого дня: сколько клеток 0.1° было активно по MODIS (Terra+Aqua)
    и по VIIRS NOAA-20, сколько клеток видели оба, и уровень 0–4 для раскраски.
    """
    if engine == "reference":
        period.limit(config.MAX_REFERENCE_DAYS)
        report = db.reference_calendar(area.scope_id, period.start, period.end, area.bbox)
    else:
        period.limit(config.MAX_CALENDAR_DAYS)
        report = grid_index.calendar(area.scope_id, period.start, period.end, area.bbox)
    if not include_windows:
        report.pop("input_windows", None)
    report["engine"] = engine
    report["area"] = _area_info(area, report["bbox"])
    return analytics.add_daily_levels(report)


@app.get("/calendar/monthly", tags=["Календарь"], summary="Активность по месяцам (для календаря год × месяц)")
def calendar_monthly(period: Annotated[Period, Depends()], area: Annotated[Area, Depends()]):
    """
    Для каждого месяца: сумма активных клеток по дням («ячейко-дни») и полнота данных:
    `complete` — загружены все дни, `partial` — часть, `missing` — ничего.
    """
    period.limit(40 * 366)
    result = grid_index.monthly(area.scope_id, period.start, period.end, area.bbox)
    result["area"] = _area_info(area, result["bbox"])
    return analytics.add_monthly_levels(result)


# ---------- Карта ----------

RESOLUTIONS = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0)


def _auto_resolution(bbox):
    width, height = (360, 180) if bbox is None else (bbox[2] - bbox[0], bbox[3] - bbox[1])
    span = max(width, height)
    return 0.1 if span <= 10 else 0.2 if span <= 30 else 0.5 if span <= 90 else 1.0


@app.get("/cells", tags=["Карта"], summary="Активные клетки для карты (GeoJSON)")
def cells(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    resolution: Annotated[float | None, Query(
        description="Размер клетки в градусах: 0.1, 0.2, 0.5, 1, 2 или 5. Не задан — подберётся сам")] = None,
):
    """
    Точки в центрах клеток с числом активных дней — готовый слой для MapLibre/Leaflet
    (например heatmap). Самые активные клетки идут первыми.
    """
    period.limit(config.MAX_CALENDAR_DAYS)
    resolution = resolution or _auto_resolution(area.bbox)
    if not any(abs(resolution - r) < 1e-9 for r in RESOLUTIONS):
        raise ValueError(f"resolution должен быть одним из {list(RESOLUTIONS)}.")
    found = grid_index.map_cells(area.scope_id, period.start, period.end, area.bbox,
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
        "bbox": found["area"]["bbox"],
        "features": features,
        "meta": {"date_from": period.start.isoformat(), "date_to": period.end.isoformat(),
                 "resolution_degrees": resolution, "cells": len(features), "truncated": found["truncated"],
                 "color_scale": {"unit": "active_days", "levels": 5, "breaks": breaks},
                 "area": _area_info(area, found["area"]["bbox"])},
    }


@app.get("/points", tags=["Карта"], summary="Отдельные обнаружения пожаров (до 7 дней)")
def points(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    sensor: Annotated[Literal["MODIS", "VIIRS"] | None, Query(description="Только один прибор")] = None,
    limit: Annotated[int, Query(ge=1, le=config.MAX_POINTS_PER_PAGE)] = 1000,
    offset: Annotated[int, Query(ge=0, description="Сколько точек пропустить (следующая страница)")] = 0,
    format: Annotated[Literal["json", "geojson"], Query(description="json — список, geojson — слой карты")] = "json",
):
    """Точки как их прислала NASA: время, координаты, спутник, мощность (FRP). Отдаются страницами."""
    period.limit(config.MAX_POINT_DAYS)
    rows = db.get_points(area.scope_id, period.start, period.end, area.bbox, sensor, limit, offset)
    page = {"limit": limit, "offset": offset, "count": len(rows), "has_more": len(rows) == limit,
            "next_offset": offset + limit if len(rows) == limit else None}
    if format == "geojson":
        return {"type": "FeatureCollection", "meta": page, "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
             "properties": r} for r in rows]}
    return {**page, "points": rows}


# ---------- Наука ----------

@app.get("/harmonization", tags=["Наука"], summary="Сведение MODIS и VIIRS в единый ряд")
def harmonization(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    split_date: Annotated[date | None, Query(
        description="Первый день проверки. До него подбирается коэффициент, после — проверяется. "
                    "Не задан — последняя треть периода")] = None,
):
    """
    Главная задача челленджа. Подбираем коэффициент k (MODIS ≈ k × VIIRS) на одной части
    дней и честно проверяем его на других днях, которые модель не видела.
    В `series` — единый ряд, где неважно, какой спутник дал данные.
    """
    period.limit(config.MAX_CALENDAR_DAYS)
    split = split_date or analytics.default_split(period.start, period.end)
    if not period.start < split <= period.end:
        raise ValueError("split_date должен лежать внутри периода (и не в первый день).")
    report = grid_index.calendar(area.scope_id, period.start, period.end, area.bbox)
    result = analytics.harmonize(report, split)
    result["area"] = _area_info(area, report["bbox"])
    result["date_from"], result["date_to"] = period.start.isoformat(), period.end.isoformat()
    return result


@app.get("/anomaly", tags=["Наука"], summary="Месяц против нормы прошлых лет")
def anomaly(
    year: Annotated[int, Query(ge=2000, le=2100, openapi_examples={"y": {"summary": "2024", "value": 2024}})],
    month: Annotated[int, Query(ge=1, le=12, openapi_examples={"m": {"summary": "Август", "value": 8}})],
    area: Annotated[Area, Depends()],
    series: Annotated[Literal["modis", "viirs"], Query(
        description="По какому прибору сравнивать (у MODIS самая длинная история)")] = "modis",
):
    """
    Сравнивает выбранный месяц с медианой этого же месяца в другие годы:
    на сколько процентов больше или меньше нормы и какое место среди всех лет.
    """
    loaded = grid_index.loaded_summary()["scopes"].get(area.scope_id)
    if not loaded:
        raise ValueError(f"В области данных '{area.scope_id}' ничего не загружено.")
    first = min(v["first_day"] for v in loaded.values())
    last = max(v["last_day"] for v in loaded.values())
    start, end = analytics.full_years(first, last)
    months = grid_index.monthly(area.scope_id, start, end, area.bbox)
    result = analytics.anomaly(months["months"], year, month, series)
    result["area"] = _area_info(area, months["bbox"])
    return result


# ---------- Выгрузка ----------

@app.get("/export.csv", tags=["Выгрузка"], summary="Скачать точки пожаров в CSV (до 31 дня)")
def export_csv(
    period: Annotated[Period, Depends()],
    area: Annotated[Area, Depends()],
    sensor: Annotated[Literal["MODIS", "VIIRS"] | None, Query(description="Только один прибор")] = None,
):
    """Файл отдаётся потоком: скачивание начинается сразу, сервер не держит его в памяти."""
    period.limit(config.MAX_EXPORT_DAYS)
    total = db.count_points(area.scope_id, period.start, period.end, area.bbox, sensor,
                            cap=config.MAX_EXPORT_ROWS)
    if total > config.MAX_EXPORT_ROWS:
        raise ValueError(f"Слишком много точек (больше {config.MAX_EXPORT_ROWS:,}). "
                         "Уменьшите область или период.".replace(",", " "))

    def generate():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=db.POINT_FIELDS)
        writer.writeheader()
        for row in db.stream_points(area.scope_id, period.start, period.end, area.bbox, sensor,
                                    cap=config.MAX_EXPORT_ROWS):
            writer.writerow(row)
            if buffer.tell() > 64_000:      # отдаём кусками примерно по 64 КБ
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()
        yield buffer.getvalue()

    name = f"firesync_{area.region or 'area'}_{period.start}_{period.end}.csv"
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"',
                                      "X-Total-Rows": str(total)})
