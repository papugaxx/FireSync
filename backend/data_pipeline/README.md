# NASA FIRMS data for FastAPI

This folder covers the path **NASA API → response validation → SQLite → reading from FastAPI**.
It does not depend on Django or FastAPI and uses the Python 3.11+ standard library.
The user's old CSV files and the archives from the website are not used. Here, CSV is the format of the HTTP
response of the Area API; the module parses that response and saves the records to the database.

## What the module already does

- Finds out the actual availability of products through the NASA API.
- Supports MODIS, VIIRS S-NPP, NOAA-20 and NOAA-21, SP and NRT.
- Fetches data for the whole world or for a rectangle and given dates.
- Splits history into requests of 1-5 days, saves progress and continues after a stop.
- Stores the satellite and the version of each row. Terra and Aqua are not mixed under one name.
- Atomically replaces a daily snapshot. Corrected FRP/confidence values and temporary records that disappeared
  do not turn into extra observations. An error does not delete the previous snapshot.
- In ordinary reads it prefers SP if it is loaded, and uses NRT as a fallback.
- Provides functions for reading observations and daily counts for Sasha's backend.

Real NASA requests need their own MAP_KEY. In this working copy the key has already been added: the live API
and saving were verified on 13 November 2026. The coverage at the time of verification is recorded in
`LIVE_STATUS.md`. Test responses are used only in automated checks with a temporary database and are not loaded
into the working database.

## Getting started

Run all the commands below from this `data_pipeline` folder.

```bash
python3 -m fires_data init
python3 -m fires_data doctor
```

Get a free key: [NASA FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/).
The key arrives by email. Copy `.env.example` to `.env` and fill in `FIRMS_MAP_KEY`.
Do not send the `.env` file in chat and do not add it to Git. The module reads this file itself;
a separate dotenv library is not needed.

```text
FIRMS_MAP_KEY=your_real_key
FIRMS_DB_PATH=var/fires.sqlite3
```

Environment variables take priority over `.env`. A relative database path in `.env`
is resolved from the folder of the `.env` file itself, not from the current working folder.

## Check the connection and make the first load

```bash
python3 -m fires_data availability
python3 -m fires_data plan --area world --recent-days 1 --sources MODIS_NRT VIIRS_NOAA20_NRT
python3 -m fires_data sync --area world --recent-days 1 --sources MODIS_NRT VIIRS_NOAA20_NRT --max-requests 2
python3 -m fires_data status
```

`--recent-days 1` means the last complete UTC day, that is, yesterday in UTC.
If NASA does not report availability for a needed day, the plan shows it. Dates are never invented.
`availability` shows the real product boundaries; the old dates from the NASA handbook
are not used as current boundaries.

## Load history

First look at the plan:

```bash
python3 -m fires_data plan --area world --all-history
```

Then run a bounded portion:

```bash
python3 -m fires_data sync --area world --all-history --batch-days 5 --max-requests 100
```

Repeating the same command continues the load from the saved daily slices. When the
request budget is reached, the job gets the status `paused` and the CLI returns code 2.
Code 0 means the requested plan finished successfully, code 1 means an error. On Ctrl+C
the finished daily slices are kept. There is `--max-requests 0` for an unlimited number of
requests, but the speed and the actual quota use must be measured first.

By default a reserve of 30 GiB of free disk is kept, plus an estimate of the space for the next
batch and the temporary SQLite write. If there is not enough space, the job is paused.
The reserve is set with `--min-free-gb`; on a server it must be chosen for the real disk and
the retention policy. This limit is not an estimate of the size of the whole archive.

`auto` by default chooses SP or NRT for each family and day. The whole history of the
instruments differs; unavailable dates are listed separately. The absence of VIIRS before the launch of the
satellite does not turn into zero. Loading the whole world archive instantly is not promised:
the time and size depend on the real responses and the NASA quota.

An example with your own area:

```bash
python3 -m fires_data plan --bbox 22 44 41 53 --from 2024-08-01 --to 2024-08-31
```

The order of the bounds is always **west south east north**. This is a rectangle, not the exact
administrative border of a country. Crossing the date line in one bbox is not yet
supported. Use `--area world` for the whole planet.

## Update fresh data

```bash
python3 -m fires_data sync --area world --recent-days 3 --include-today --sources MODIS_NRT VIIRS_NOAA20_NRT VIIRS_NOAA21_NRT --max-requests 20
```

This command includes today and the two previous UTC days. Today's data is incomplete.
These fresh windows are re-downloaded by default. To force a re-request of
previously loaded history, use `--refresh`.

The scheduler is not connected yet: the update command is already separated out, and it can be run
from a separate process or on a schedule. Do not run many syncs of the same
area at once. Ordinary FastAPI requests should read the ready database, not
wait inside an HTTP response for a multi-year history download.

## For Sasha, for FastAPI

In your Python environment install the local package from the root of the shared repository:

```bash
python -m pip install -e ./data_pipeline
```

Reading from the same database file:

```python
from datetime import date
from fires_data import Store, load_settings

settings = load_settings()
store = Store(settings.db_path)

rows = store.observations(
    scope_id="world",
    start=date(2026, 11, 12),
    end=date(2026, 11, 12),
    limit=1000,
    offset=0,
)
```

Replace the dates in the example with dates that are really loaded. `observations` returns UTC time,
coordinates, instrument, satellite, FRP, confidence, version and other fields. For the frontend:
`lat = latitude`, `lon = longitude`, `seenBy = sensor`, `date = observed_at[:10]`.
For a rectangular area in the world database, pass `bbox=(west, south, east, north)`
to `observations` or `daily_counts`, keeping `scope_id="world"`. For example,
`bbox=(22, 44, 41, 53)`. This is an approximate area: such a rectangle is not the exact border of a country.
Do not substitute the frontend's region identifier for the scope.

`BOTH` cannot be assigned to a single source record: it needs a separate matching algorithm.
Some numeric fields can be `None`; do not turn that into zero power.

Other methods: `list_scopes()`, `list_windows(scope_id, start, end)`,
`daily_counts(scope_id, start, end)`, `status(scope_id)`, `list_jobs()`, `get_job(id)`.
SQL queries and connections are created inside the methods; a connection is not shared between
FastAPI threads. SQLite works in WAL mode, with foreign keys and a wait for short locks.

Each read request selects one `scope_id`. Results of overlapping saved areas must not
be added together: that would count the same observations again.
By default a read selects SP instead of NRT for the same family and day, including
a valid empty SP slice. Different VIIRS platforms remain distinguishable.

## Calculating the common grid for the calendar

```bash
python3 -m fires_data calendar --scope world --from 2024-08-01 --to 2024-08-31
```

This reads the local database, without NASA requests. For each UTC day it calculates
the number of observations and the number of active cells of the common 0.1° grid separately for MODIS
(Terra+Aqua, union of cells) and VIIRS NOAA-20. An example for a chosen area:

```bash
python3 -m fires_data calendar --scope world --from 2024-08-01 --to 2024-08-31 --bbox 22 44 41 53
```

The bounds are a rectangle, not the exact outline of a country. From FastAPI:

```python
from fires_data import grid_calendar
report = grid_calendar(store, "world", start, end, bbox=(22, 44, 41, 53))
```

`daily` holds the values by day. For a source that is not loaded: `status: missing`
and `null`; for a valid empty loaded day: `loaded` and 0.
`shared_active_cells` means the number of cells where both selected sets gave observations
within the same UTC day. This is not a confirmation of one physical fire.

`totals.*.active_cell_days` is the sum of the daily values, that is, cell-days, not distinct
cells of the month. If at least one requested day of a source is not loaded, its total is `null`.
`coverage` shows the completeness of retrieval. One call is limited to 366 days.

The result is computed from one database snapshot on every call. After a raw
slice is updated, the next call recomputes the result; there is no separate stale cache.
On this working database the world for August 2024 took 28 seconds; the rectangle
22,44,41,53 took 22 seconds. For the website, use a precomputed result
or a separate background task that checks the input versions. Even a call in a thread pool
does not make a heavy calculation instant. The `var/calendar-*.json` examples are saved
snapshots; after the input data changes they must be recomputed.

The common grid is the initial comparative indicator, **not a validated harmonization**.
The coefficient, R², historical norm and anomalies are not invented by this method.
The method, limitations and sources are in `GRID_METHOD.md`.

## A limited experiment on reconciling the indices

```bash
python3 -m fires_data calibrate --scope world --from 2024-08-01 --to 2024-08-31 --split 2024-08-22 --bbox 22 44 41 53
```

The command first reads the current records of the database and calculates the grid series. Then it
fits a coefficient only on the dates before `--split`; the remaining dates are kept for
checking. The NASA API and the source records are not changed.

From Python:

```python
from datetime import date
from fires_data import calibrate_calendar
experiment = calibrate_calendar(report, split_date=date(2024, 8, 22))
```

`coefficient` is a scale correction of VIIRS to the chosen MODIS reference. `metrics`
holds the separate train/test results for the raw VIIRS, the correction and the constant
training mean of MODIS. `daily` keeps the source and calculated values.
`insufficient_data` means there is not enough data for the experiment; in that case the coefficient and metrics
are absent. `improved_on_holdout` means an improvement only on the
held-out dates of this experiment. `not_improved` means the improvement criterion was not met.

Any result remains experimental and has `apply_automatically=false`.
The correction does not change the map points or the source series. The conditions of the experiment and the limitations
are in `CALIBRATION_METHOD.md`.

## What data readiness means

A successful HTTP response is checked as CSV, not only by status 200. A header with no
rows means zero detections received. HTML, error text and an empty body do not
overwrite data. Loading a full response does not prove full observation of the
territory by the satellite; zero detections do not prove the absence of fire.

`daily_counts` counts raw observations. This is not yet the number of separate fires,
not the number of active cells and not a harmonized indicator. `grid_calendar`
already calculates separate grid series. A separate experiment on reconciling the indices is implemented by the `calibrate` command;
its transferability to other periods and territories has not yet been confirmed.

## Map layers and data are different

[NASA WMS/WMS-Time](https://firms.modaps.eosdis.nasa.gov/mapserver/wms-info/) provide map
images. FastAPI/Leaflet connects them separately. This module saves numeric observations
through the Area API. WFS is not needed for this first path.

## Checks

```bash
python3 -m unittest discover -s tests -v
```

The checks cover repetition, corrections, atomicity, an empty response, SP/NRT and isolation of areas.
The checks work without a key and without a network. Once a MAP_KEY is available, `availability` and the first real request
are run separately. Until then, the connection to live NASA is not considered
verified.

## Main files

- `fires_data/client.py` - calls to NASA and the response limit.
- `fires_data/parsing.py` - CSV validation and parsing of observations.
- `fires_data/schema.sql`, `store.py` - the SQLite schema and storage operations.
- `fires_data/service.py` - planning, loading, updates and progress.
- `fires_data/cli.py` - the launch commands.

Official documents: [Area API](https://firms.modaps.eosdis.nasa.gov/api/area/),
[product availability](https://firms.modaps.eosdis.nasa.gov/api/data_availability/),
[MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/).
