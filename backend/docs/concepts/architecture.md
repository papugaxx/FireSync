# Architecture

## Data flow

```text
NASA_FIRMS_2000_2025.csv (50 GB) ──(importer.py, once)──┐
                                                         ▼
NASA FIRMS API ──(updater.py, in the background)──► data/firesync.sqlite3   (~3 GB)
                                                         │
                                       reports.py: calendar, months, cells, points
                                                         │
     fire-calendar (browser) ──► frontend_api.py /api/... ┤
     other clients           ──► main.py /calendar, /cells, ... ┘
```

There is **one database**, `data/firesync.sqlite3`. It holds every MODIS (Terra + Aqua) and VIIRS NOAA-20
detection: the 2000–2025 archive and every day downloaded later from the NASA FIRMS API.
The partner's pipeline package (`fires_data`) is still used for what it does best: the NASA client (key handling,
quota, size limits), validated CSV parsing, the grid reference calculation and the calibration experiment.

## Modules

| Module | Responsibility |
|---|---|
| [`main`](../reference/main.md) | The app: general endpoints, errors, CORS, gzip, starts the background updater. |
| [`frontend_api`](../reference/frontend_api.md) | The `/api/...` endpoints that the fire-calendar frontend calls, in the shapes of `fire-calendar/types/api.ts`. |
| [`store`](../reference/store.md) | The database: schema, compressed day blocks, region tables, reading and writing. |
| [`reports`](../reference/reports.md) | Calendar, monthly, map-cell and point queries for a region or an own rectangle. |
| [`importer`](../reference/importer.md) | Loads a NASA FIRMS archive CSV (run once; resumable). |
| [`updater`](../reference/updater.md) | Downloads new days from the NASA FIRMS API, in the background or from the command line. |
| [`analytics`](../reference/analytics.md) | Pure math (levels, harmonization, anomaly). No database and no HTTP. |
| [`config`](../reference/config.md) | Paths, regions, update settings and limits. Also puts `data_pipeline/` on `sys.path`. |
| [`fires_data`](../reference/pipeline.md) | The partner's package: NASA client, parsing, grid analytics, calibration. |

## Why detections are stored in day blocks

The archive has about 267 million MODIS + NOAA-20 detections. Stored one row per detection, SQLite needs
30–600 bytes per row (the partner's schema keeps the raw JSON of every row): tens to hundreds of gigabytes.

`store.py` keeps **all detections of one UTC day and one sensor in one compressed block**: every column
(latitude, longitude, time, FRP, brightness, scan, track, confidence, satellite, day/night, type, version) is
stored as whole numbers (coordinates × 100 000, FRP and brightness × 100 — the precision NASA publishes) and
compressed separately. That is about 11 bytes per detection, 3 GB for the whole archive, and a day reads in
milliseconds. Values come back exactly as NASA published them.

## Why the calendar is instant

For every ready-made region in `config.REGIONS` the database also stores, per day, the number of active 0.1°
cells, detections and FRP sums of each sensor (`region_days`), and per month the distinct cells and their area
(`region_months`). The calendar, the month view and the charts only read these small tables. They are rebuilt
for a month whenever a day of that month changes, and completely when `config.REGIONS` changes.

An own rectangle (`west, south, east, north`) is computed from the day blocks, so its period is limited to
`MAX_CUSTOM_AREA_DAYS` (366).

## Schema

```sql
meta          (key, value)                                -- format version, revision, import and update info
days          (id, day, sensor, product, origin,          -- one row per stored UTC day and sensor
               observations, cells, bytes, loaded_at)     --   product: SP | NRT, origin: archive | api
day_data      (id, block)                                 -- the compressed detections of that day
region_days   (region, day, modis_cells, viirs_cells, shared_cells, modis_obs, viirs_obs,
               modis_frp_n/sum/max, viirs_frp_n/sum/max, modis_product, viirs_product)
region_months (region, month, sensor, loaded_days, nrt_days, cell_days, cells, area_km2,
               cell_day_area_km2, observations, frp_n, frp_sum, frp_max)
```

- A row in `days` means "this day was observed". A stored day with zero detections in a region is a measured
  zero; a day without a row is **no data** and appears as `null` everywhere.
- One product per sensor and day: SP (final) if stored, otherwise NRT. They are never added together.
- `meta.revision` grows with every change. API answers are cached per revision, so a repeated request costs
  nothing until new data arrives.
- The database uses WAL mode: the API keeps reading while the updater writes.

## Why the numbers can be trusted

- The grid is the partner's (`data_pipeline/GRID_METHOD.md`): 0.1° cells from (-180, -90), MODIS = Terra + Aqua,
  VIIRS = NOAA-20. The test suite loads the same rows with the partner's own code and compares his
  `grid_calendar()` with ours on every day (`test_grid_matches_the_partner_calculation`).
- The import was checked against the raw file: on 2024-08-15 the CSV has 106 758 NOAA-20 and 21 936 MODIS rows,
  the database has the same.
- Rows of one day are spread over the archive's year blocks; the importer keeps a year in memory and writes each
  day once, and the tests use a shuffled archive to prove nothing is lost or counted twice.
