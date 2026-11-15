# Endpoints

All endpoints are `GET` and return JSON unless stated otherwise. Shared conventions (period, area, errors,
headers, limits) are on the [Overview](overview.md) page; this page lists what is specific to each endpoint.

Examples use `http://localhost:8000`. Responses are shortened with `...`.

!!! note "About the example values"
    The structure of every response is taken from the code. The `/calendar` day example and the
    `/harmonization` numbers are real results for August 2024 (see the project README). Other numbers
    (`/status`, `/calendar/monthly`, `/cells`, `/points`) are illustrative placeholders, not real measurements.

| Endpoint | Purpose |
|---|---|
| [`/api/...`](#frontend-endpoints) | What the fire-calendar website calls |
| [`/health`](#get-health) | Is the server alive? |
| [`/status`](#get-status) | What data is loaded, and is the index ready? |
| [`/regions`](#get-regions) | Ready-made regions |
| [`/calendar`](#get-calendar) | Daily activity, MODIS and VIIRS |
| [`/calendar/monthly`](#get-calendarmonthly) | Monthly activity with completeness |
| [`/cells`](#get-cells) | Map layer (GeoJSON): active cells |
| [`/points`](#get-points) | Individual detections, paged |
| [`/harmonization`](#get-harmonization) | MODIS and VIIRS merged into one series, with validation |
| [`/anomaly`](#get-anomaly) | A month versus the median of other years |
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

`bbox` is `[west, south, east, north]`. `scope` is the pipeline data scope searched for that region. Names are
currently in Russian. Available ids: `world`, `ukraine`, `central_africa`, `amazon`, `siberia`, `australia`,
`california`.

## GET /calendar

Daily activity: for each UTC day, how many 0.1° cells were active according to MODIS (Terra + Aqua) and VIIRS
(NOAA-20), how many cells both saw, and a ready-made 0-4 color level.

**Parameters:** [period](overview.md#period), [area](overview.md#area), plus:

| Parameter | Default | Description |
|---|---|---|
| `engine` | `fast` | `fast` uses the index (instant). `reference` uses the pipeline's original calculation (~25 s, up to 366 days), for cross-checking. |
| `include_windows` | `false` | Also return `input_windows`: the NASA slices (day, source, checksum, fetch time, row count) the numbers came from. |

```bash
curl "http://localhost:8000/calendar?date_from=2024-08-01&date_to=2024-08-31&region=ukraine"
```

One element of `daily`:

```json
{
  "date": "2024-08-01",
  "modis": {"status": "loaded", "observations": 207, "active_cells": 135, "level": 2},
  "viirs": {"status": "loaded", "observations": 861, "active_cells": 349, "level": 3},
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
| `method` | Full description of how the numbers were computed. |
| `bbox` / `requested_bbox` / `area` | The area actually computed and the one requested. |
| `engine` | Which engine produced the result. |

Status values per series and day: `loaded` or `missing`. When `missing`, `observations`, `active_cells` and
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
  "bbox": [22.0, 44.0, 41.0, 53.0],
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
    {"id": "9f2c41aa07b3d812", "observed_at": "2024-08-01T00:12:00Z", "day": "2024-08-01",
     "sensor": "MODIS", "satellite": "Aqua", "source_code": "MODIS_SP",
     "latitude": 48.51, "longitude": 31.2, "frp_mw": 12.5, "brightness_k": 321.5,
     "confidence_raw": "80", "daynight": "D", "type_code": 0}
  ]
}
```

- To read the next page, request again with `offset=next_offset`. `next_offset` is `null` on the last page.
- `has_more` is `true` whenever the page is full, so the final page can still report `true` if it ended exactly
  on a page boundary. In that case the next page is simply empty.
- `frp_mw`, `brightness_k` and other numeric fields can be `null`. A `null` is not zero power.
- With `format=geojson`, `meta` holds the paging fields and each feature's `properties` contains the same fields.

## GET /harmonization

Merges MODIS and VIIRS into one series and checks the merge on days the model has not seen. See
[Harmonization](../concepts/harmonization.md) for the method.

**Parameters:** [period](overview.md#period), [area](overview.md#area), plus:

| Parameter | Default | Description |
|---|---|---|
| `split_date` | last third of the period | First day of the test period. Must lie inside the period and not be its first day. |

```bash
curl "http://localhost:8000/harmonization?date_from=2024-08-01&date_to=2024-08-31&region=ukraine&split_date=2024-08-22"
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

Compares one month with the median of the same month in other years.

**Parameters:** [area](overview.md#area), plus:

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
| `insufficient_history` | Fewer than 3 other complete years. `years_available` lists what exists. |
| `ok` | Includes `median`, `anomaly_percent`, `verdict` (`above_normal`, `normal`, `below_normal`), `rank` and `rank_of`. |

Every response carries `value`, `history` (value per other year) and a human-readable `message` (currently
in Russian). If nothing at all is loaded for the area's scope the request fails with `400`.

## GET /export.csv

Downloads detections as a CSV file. The file is **streamed**: the download begins immediately and the server does
not hold it in memory.

**Parameters:** [period](overview.md#period) (**maximum 31 days**), [area](overview.md#area), plus `sensor`
(`MODIS` or `VIIRS`).

```bash
curl -OJ "http://localhost:8000/export.csv?date_from=2024-08-15&date_to=2024-08-15&west=30&south=46&east=36&north=50"
```

- Response type is `text/csv; charset=utf-8`, sorted by `observed_at`.
- Columns: `observed_at, day, sensor, satellite, source_code, latitude, longitude, frp_mw, brightness_k,
  confidence_raw, daynight, type_code`.
- The file name looks like `firesync_ukraine_2024-08-15_2024-08-15.csv` (`area` when no region is used).
- `X-Total-Rows` gives the row count. If more than 200 000 rows match, the request fails with `400` and asks you
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
