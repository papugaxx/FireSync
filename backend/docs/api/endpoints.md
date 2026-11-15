# Endpoints

All endpoints are `GET` and return JSON unless stated otherwise. Shared conventions (period, area, errors,
headers, limits) are on the [Overview](overview.md) page; this page lists what is specific to each endpoint.

Examples use `http://localhost:8000`. Responses are shortened with `...`.

!!! note "About the example values"
    The structure of every response is taken from the code. The `/calendar` day example and the
    `/harmonization` numbers are real results for August 2024 in the rectangle `west=22, south=44, east=41, north=53`
    (see the project README); the `ukraine` region is slightly smaller, so its numbers differ. Other numbers
    (`/status`, `/calendar/monthly`, `/cells`, `/points`) are illustrative placeholders, not real measurements.

| Endpoint | Purpose |
|---|---|
| [`/api/...`](#frontend-endpoints) | What the fire-calendar website calls |
| [`/health`](#get-health) | Is the server alive? |
| [`/status`](#get-status) | What data is loaded, and what the NASA update is doing |
| [`/regions`](#get-regions) | Ready-made regions |
| [`/calendar`](#get-calendar) | Daily activity, MODIS and VIIRS |
| [`/calendar/monthly`](#get-calendarmonthly) | Monthly activity with completeness |
| [`/cells`](#get-cells) | Map layer (GeoJSON): active cells |
| [`/points`](#get-points) | Individual detections, paged |
| [`/harmonization`](#get-harmonization) | MODIS and VIIRS merged into one series, with validation |
| [`/anomaly`](#get-anomaly) | A month versus the median of earlier years |
| [`/export.csv`](#get-exportcsv) | Download points as CSV |

`GET /` redirects to `/docs`.

---

## GET /health

Liveness check. Does not touch the databases.

```json
{"status": "ok"}
```

## GET /status

What is stored and what the automatic NASA update is doing.

```json
{
  "status": "ok",
  "data": {
    "modis": {"first_day": "2000-11-01", "last_day": "2025-12-31", "days": 9166, "nrt_days": 0,
              "observations": 111424408, "api_days": 0},
    "viirs": {"first_day": "2018-04-01", "last_day": "2025-12-31", "days": 2826, "nrt_days": 0,
              "observations": 155932146, "api_days": 0}
  },
  "database": {"revision": 3, "size_mb": 2851.2, "archive": {"status": "completed", "...": "..."}},
  "update": {"state": "idle", "message": "Up to date with NASA FIRMS.", "api_key_configured": true,
             "last_completed_run": {"requests": 61, "days_written": 60, "stopped_because": null, "...": "..."}},
  "version": "2.0.0"
}
```

- `status` is `"no_database"` until `data/firesync.sqlite3` exists (run `python importer.py`).
- `first_day` and `last_day` are the extremes, **not** a guarantee that every day in between is stored.
  Use `days` or the `coverage` block of `/calendar`. Missing days inside the archive are instrument outages.
- `nrt_days` are days stored as near-real-time data; they are replaced by final (SP) data when NASA publishes it.
- The NASA key and the database file path are never exposed.

## GET /regions

Ready-made regions for demos. Defined in `config.REGIONS`.

```json
[
  {"id": "world",   "name": "World",   "bbox": null},
  {"id": "ukraine", "name": "Ukraine", "bbox": [22.1, 44.3, 40.2, 52.4]}
]
```

`bbox` is `[west, south, east, north]`, or `null` for the whole world. Available ids: `world`, `ukraine`,
`argentina`, `california`, `amazonas`, `central_africa`, `siberia`, `australia`.

## GET /calendar

Daily activity: for each UTC day, how many 0.1° cells were active according to MODIS (Terra + Aqua) and VIIRS
(NOAA-20), how many cells both saw, and a ready-made 0-4 color level.

**Parameters:** [period](overview.md#period), [area](overview.md#area), plus:

| Parameter | Default | Description |
|---|---|---|
| `include_windows` | `false` | Also return `input_windows`: the stored days the numbers came from (`day`, `source_code`, `origin`, `row_count`, `fetched_at`). |

```bash
curl "http://localhost:8000/calendar?date_from=2024-08-01&date_to=2024-08-31&region=ukraine"
```

One element of `daily`:

```json
{
  "date": "2024-08-01",
  "modis": {"status": "loaded", "product": "SP", "observations": 207, "active_cells": 135, "level": 2},
  "viirs": {"status": "loaded", "product": "SP", "observations": 861, "active_cells": 349, "level": 3},
  "shared_active_cells": 68
}
```

Top-level fields:

| Field | Description |
|---|---|
| `daily` | One entry per requested day, in order. |
| `coverage` | Per series: `{"loaded_days", "requested_days"}`. |
| `totals` | Per series: `observations` and `active_cell_days` over the period. `null` if any requested day of that series is missing. |
| `color_scale` | Per series: `{"unit": "active_cells", "levels": 5, "breaks": [q1, q2, q3]}`. Use `breaks` to draw a legend. |
| `method` | Full description of how the numbers were computed (including `engine`, the calculation version). |
| `bbox` / `requested_bbox` / `area` | The area actually computed and the one requested. |

Status values per series and day: `loaded` or `missing`; `product` is `SP` (final data) or `NRT` (near real time). When `missing`, `product`, `observations`, `active_cells` and
`level` are `null`. `shared_active_cells` is `null` unless **both** series are loaded that day.

## GET /calendar/monthly

Activity aggregated by month, for a year-by-month calendar.

**Parameters:** [period](overview.md#period), [area](overview.md#area).

```bash
curl "http://localhost:8000/calendar/monthly?date_from=2000-01-01&date_to=2026-12-31&region=ukraine"
```

One element of `months`:

```json
{
  "month": "2024-08", "year": 2024, "month_number": 8, "days": 31,
  "modis": {"status": "complete", "loaded_days": 31, "active_cell_days": 4210,
            "observations": 61234, "level": 3},
  "viirs": {"status": "complete", "loaded_days": 31, "active_cell_days": 11640,
            "observations": 283001, "level": 3},
  "shared_cell_days": 2100
}
```

- `active_cell_days` is the sum of daily active cells ("cell-days"), not a count of distinct cells.
- `status` is `complete` (all days loaded), `partial` (some) or `missing` (none). For `missing`, the numbers are
  `null`. Treat `partial` months with caution.
- `color_scale` uses the unit `active_cell_days`; levels are computed across the months in the response.

## GET /cells

A ready-made map layer: points at cell centers with the number of active days, most active first.

**Parameters:** [period](overview.md#period), [area](overview.md#area), plus:

| Parameter | Default | Description |
|---|---|---|
| `resolution` | automatic | Cell size in degrees: `0.1`, `0.2`, `0.5`, `1`, `2` or `5`. |

When `resolution` is omitted it is chosen from the size of the area (larger side): up to 10° gives `0.1`, up to
30° gives `0.2`, up to 90° gives `0.5`, anything larger (including the whole world) gives `1.0`.

```bash
curl "http://localhost:8000/cells?date_from=2024-08-01&date_to=2024-08-31&region=ukraine"
```

```json
{
  "type": "FeatureCollection",
  "bbox": [22.1, 44.3, 40.2, 52.4],
  "features": [
    {"type": "Feature",
     "geometry": {"type": "Point", "coordinates": [30.55, 50.45]},
     "properties": {"active_days": 14, "modis_cell_days": 9, "viirs_cell_days": 14,
                    "modis_observations": 31, "viirs_observations": 88, "level": 4}}
  ],
  "meta": {"date_from": "2024-08-01", "date_to": "2024-08-31", "resolution_degrees": 0.1,
           "cells": 1234, "truncated": false,
           "color_scale": {"unit": "active_days", "levels": 5, "breaks": [1, 3, 6]},
           "area": {"...": "..."}}
}
```

- Coordinates are `[longitude, latitude]`, as GeoJSON requires.
- `active_days` is the number of distinct days the (possibly coarse) cell had activity in either series.
- At most 20 000 cells are returned. If more exist, the most active are kept and `meta.truncated` is `true`.

The layer plugs into MapLibre as a single source:

```js
map.addSource('fires', {
  type: 'geojson',
  data: 'http://localhost:8000/cells?date_from=2024-08-01&date_to=2024-08-31'
});
```

## GET /points

Individual detections as received from NASA, in pages. Intended for zoomed-in map views.

**Parameters:** [period](overview.md#period) (**maximum 7 days**), [area](overview.md#area), plus:

| Parameter | Default | Description |
|---|---|---|
| `sensor` | both | `MODIS` or `VIIRS`. |
| `limit` | `1000` | Page size, 1 to 5000. |
| `offset` | `0` | Number of points to skip. |
| `format` | `json` | `json` (a list) or `geojson` (a `FeatureCollection`). |

```bash
curl "http://localhost:8000/points?date_from=2024-08-01&date_to=2024-08-01&region=ukraine&limit=2"
```

```json
{
  "limit": 2, "offset": 0, "count": 2, "has_more": true, "next_offset": 2,
  "points": [
    {"observed_at": "2024-08-01T00:12:00Z", "acq_date": "2024-08-01", "acq_time": "0012",
     "sensor": "MODIS", "satellite": "Aqua", "latitude": 48.51, "longitude": 31.2,
     "frp_mw": 12.5, "brightness_k": 321.5, "brightness2_k": 295.1, "scan_km": 1.1, "track_km": 1.0,
     "confidence": "80", "daynight": "D", "type": 0, "version": "6.1"}
  ]
}
```

- To read the next page, request again with `offset=next_offset`. `next_offset` is `null` on the last page.
- `has_more` is `true` whenever the page is full, so the final page can still report `true` if it ended exactly
  on a page boundary. In that case the next page is simply empty.
- `frp_mw`, `brightness_k` and other numeric fields can be `null`. A `null` is not zero power.
- `confidence` is the MODIS percentage (as text) or the VIIRS class `l`, `n` or `h`. `type` is NASA's `type` code
  (0 vegetation fire, 1 volcano, 2 static source, 3 offshore). `brightness_k` is MODIS `brightness` / VIIRS `bright_ti4`;
  `brightness2_k` is `bright_t31` / `bright_ti5`.
- With `format=geojson`, `meta` holds the paging fields and each feature's `properties` contains the same fields.

## GET /harmonization

Merges MODIS and VIIRS into one series and checks the merge on days the model has not seen. See
[Harmonization](../concepts/harmonization.md) for the method.

**Parameters:** [period](overview.md#period), [area](overview.md#area), plus:

| Parameter | Default | Description |
|---|---|---|
| `split_date` | last third of the period | First day of the test period. Must lie inside the period and not be its first day. |

```bash
curl "http://localhost:8000/harmonization?date_from=2024-08-01&date_to=2024-08-31&west=22&south=44&east=41&north=53&split_date=2024-08-22"
```

```json
{
  "summary": {
    "status": "improved_on_holdout",
    "coefficient": 0.3342,
    "formula": "MODIS ≈ k × VIIRS NOAA-20 (active 0.1° cells per day)",
    "split_date": "2024-08-22",
    "test_mae_raw": 223.3,
    "test_mae_harmonized": 34.52,
    "error_reduction_percent": 84.5,
    "test_r2_harmonized": 0.014
  },
  "series": [
    {"date": "2024-08-01", "split": "train", "modis": 135, "viirs": 349,
     "viirs_scaled": 116.64, "harmonized": 135, "harmonized_source": "MODIS"}
  ],
  "experiment": {"...": "..."},
  "date_from": "2024-08-01", "date_to": "2024-08-31", "area": {"...": "..."}
}
```

- `summary.status` is `improved_on_holdout`, `not_improved` or `insufficient_data`. When there is not enough
  data, `coefficient` is `null` and `reasons` explains why.
- `series[].harmonized_source` is `MODIS`, `VIIRS_NOAA20 x k`, or `null`.
- `experiment` carries the pipeline's full calibration result (metrics for train, test and baselines).

## GET /anomaly

Compares one month with the median of the same month in earlier years.

**Parameters:** [area](overview.md#area), but only a ready-made `region` (or nothing, meaning the world). A custom
`west/south/east/north` rectangle returns `400`, because the norm needs many years of data. Plus:

| Parameter | Default | Description |
|---|---|---|
| `year` | required | 2000 to 2100. |
| `month` | required | 1 to 12. |
| `series` | `modis` | `modis` or `viirs`. MODIS has the longer history. |

```bash
curl "http://localhost:8000/anomaly?year=2024&month=8&region=ukraine"
```

Possible `status` values:

| `status` | Meaning |
|---|---|
| `month_not_loaded` | The requested month is not fully loaded; nothing to compare. |
| `insufficient_history` | Fewer than 3 complete earlier years (only years before the requested one form the norm). `years_available` lists what exists. |
| `ok` | Includes `median`, `anomaly_percent`, `verdict` (`above_normal`, `normal`, `below_normal`), `rank` and `rank_of`. |

Every response carries `value`, `history` (`{year, value}` for each earlier year) and a human-readable `message`.
If nothing is stored at all, the request fails with `400`.

## GET /export.csv

Downloads detections as a CSV file. The file is **streamed**: the download begins immediately and the server does
not hold it in memory.

**Parameters:** [period](overview.md#period) (**maximum 31 days**), [area](overview.md#area), plus `sensor`
(`MODIS` or `VIIRS`).

```bash
curl -OJ "http://localhost:8000/export.csv?date_from=2024-08-15&date_to=2024-08-15&west=30&south=46&east=36&north=50"
```

- Response type is `text/csv; charset=utf-8`. Rows come day by day (MODIS, then VIIRS), by time within each day.
- Columns: `observed_at, acq_date, acq_time, sensor, satellite, latitude, longitude, frp_mw, brightness_k,
  brightness2_k, scan_km, track_km, confidence, daynight, type, version`.
- The file name looks like `firesync_ukraine_2024-08-15_2024-08-15.csv` (`area` when no region is used).
- `X-Total-Rows` gives the row count. If more than 1 000 000 rows match, the request fails with `400` and asks you
  to narrow the area or period.


## Frontend endpoints { #frontend-endpoints }

The fire-calendar website calls `/api/...` (see [Frontend](../development/frontend.md) for every field). All take
`region` (an id from `/regions`), and where needed `year` and `month`:

| Endpoint | Answer |
|---|---|
| `GET /api/meta/` | regions (bbox `[south, west, north, east]`) and years with data |
| `GET /api/calendar/?region=` | year × month active cell-days on the MODIS scale, monthly medians, harmonization `k` and `r2` |
| `GET /api/month/?region&year&month` | per day: MODIS and NOAA-20 active cells, harmonized value, products |
| `GET /api/monthly/?region&year` | per month: MODIS and scaled NOAA-20 cell-days, area of distinct cells, FRP mean and max |
| `GET /api/hotspots/?region&year&month[&day][&sensor][&limit]` | active 0.1° cells per day with `seenBy` and FRP |
| `GET /api/export/?region&year&month[&day][&sensor]` | CSV of the individual detections |
| `GET /api/updates/` | stored data and the state of the automatic NASA update |


## Region borders { #region-borders }

Regions with a `boundary` in `config.REGIONS` are counted by the **real border** (Natural Earth 1:10m,
`geodata/boundaries.geojson`), not by their rectangle — for the calendar, the monthly statistics, the map
cells, `/api/detections/` and the CSV export alike. Each detection is tested (`geo.py`): cells completely
inside or outside the border are decided at once, cells the border passes through are decided detection by
detection. A border cell is active for a country only when one of its detections is inside; its counts
include only those detections. `bbox` is now only the view the map zooms to.

| Region | Counted by |
|---|---|
| ukraine, argentina, australia | country border (Ukraine in its internationally recognised borders) |
| california, amazonas | state border |
| siberia | Russia's border cut by the rectangle 90–140°E, 50–70°N |
| central_africa | the rectangle (no border configured) |
| world | everything |

To add a border: set `"boundary": "country:<ISO3>"` or `"state:<ISO 3166-2>"` and run
`python tools/build_boundaries.py`. Region tables are rebuilt automatically on the next start.

## GET /api/boundary/?region= { #api-boundary }

The border a region is counted by, as a GeoJSON Feature (MultiPolygon). `detail` (degrees, default 0.02)
simplifies it for drawing.

## GET /api/detections/?region=&date=[&cell=][&sensor=] { #api-detections }

Individual detections of one UTC day inside the region's border: real latitude/longitude, time, satellite,
FRP, confidence, product (SP/NRT) and the number of the 0.1° `cell`. With `cell` (from `/api/hotspots/`)
only that cell. Paged with `limit`/`offset`.

`/api/hotspots/` items are **grid cells** (`kind: "cell"`, `cell`, `cell_size_degrees: 0.1`, `edge`); their
`lat`/`lon` is the cell centre, never a fire location.

## GET /api/sync/ { #api-sync }

The state of the synchronisation with NASA FIRMS; see [Archive and updates](../pipeline/archive-and-updates.md).
