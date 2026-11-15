# Data status as of 14 November 2026

The retrieval path already works: NASA FIRMS Area API → CSV response validation → SQLite.
The old user CSV files and NASA ZIP archives were not used.

## What is actually loaded

Area: the whole world, `scope_id="world"`. All dates and times are in UTC.
The database holds 4 893 436 raw observations. The database file size is about 2.88 GiB.

| Source | Loaded dates | Days | Records |
|---|---|---:|---:|
| MODIS_SP | 2000-11-01 — 2001-02-09 and separately 2024-08-01 — 2024-08-31 | 132 | 1 262 957 |
| VIIRS_SNPP_SP | 2012-01-20 | 1 | 45 269 |
| MODIS_NRT | 2026-11-12 | 1 | 9 252 |
| VIIRS_NOAA20_NRT | 2026-11-12 | 1 | 49 061 |
| VIIRS_NOAA20_SP | 2024-08-01 — 2024-08-31 | 31 | 3 526 897 |

This is partial coverage, not the whole world archive. The table is a snapshot of the state:
after the next loads, look at the current values with `python3 -m fires_data status`.

The last load of the common August 2024 is finished: 62 of 62 daily slices, without errors.
For August MODIS gave 773 697 observations, VIIRS NOAA-20 gave 3 526 897.
Before that, the early historical portion of MODIS was stopped by the request limit;
this is the saved progress of a separate job, not an error of the August load.

NASA reports the availability of later history and of other VIIRS platforms;
they are supported by the loader but not yet fully loaded. A day missing from the database
means "not loaded", not "there were no fires".

## What has already been verified

- The key works: real date boundaries and real Area API responses were received.
- Historical and fresh requests work.
- A repeated request for two fresh sets kept the previous count: 58 313 records.
- The SQLite integrity check: `ok`.
- All 52 automated checks passed; their data lives only in temporary databases.
- Loaded days and progress are saved, and errors do not overwrite the previous daily snapshot.
- A request limit, a NASA quota check and a free-disk reserve were added.

## Connecting Sasha

The backend is FastAPI. This package does not depend on Django.
From the root of the shared repository, in the backend environment:

```bash
python -m pip install -e ./data_pipeline
```

An example of reading a real loaded day:

```python
from datetime import date
from fires_data import Store, load_settings

store = Store(load_settings().db_path)
rows = store.observations(
    scope_id="world",
    start=date(2026, 11, 12),
    end=date(2026, 11, 12),
    limit=1000,
    offset=0,
)
```

`limit` bounds the response page. For the whole selection you need the following pages,
and for the map an area filter and/or a separate map layer. Do not send hundreds of thousands
of records in one response and do not download NASA history inside a user request.

Sasha needs to make the HTTP methods agreed with the frontend, convert the fields,
pass the needed period and the `bbox` for an area, and return the data coverage.

The filter has already been added to `Store`: `observations(..., bbox=(22, 44, 41, 53))` and
`daily_counts(..., bbox=(22, 44, 41, 53))`. The same world database and
`scope_id="world"` are used. This is a rectangle, not an exact administrative border.
Sasha maps the frontend's region identifiers to their coordinates.
The storage methods: `observations`, `daily_counts`, `list_windows`, `status`.
The description and other examples are in README.md.

On another computer `.env` must be set up separately. The database itself is not passed through
ordinary Git: `var/` is excluded. To pass SQLite while a loader is running, use the
standard SQLite backup, and do not copy a single file while writing is active.

## What remains to be done

1. Continue loading the needed periods and platforms with progress saved.
2. Sasha connects the database to FastAPI, then checks the full scenario together with the frontend.
3. Separately connect a WMS map / a suitable layer and the regular update run.
4. Check the transferability of the experimental correction on new periods and territories.

For now `daily_counts` counts raw detections. This is not the number of separate fires,
not active cells and not a harmonized indicator. The quality of the reconciliation of the instruments has not been measured yet.

The key is stored only in a local setting. No commits or pushes were made at this stage.

## The common grid calculation was added

The function `grid_calendar(store, scope_id, start, end, bbox=None)` and the `calendar` command
read the raw records in one database snapshot. They give separate series for MODIS Terra+Aqua
and VIIRS NOAA-20, the number of active 0.1° cells per day, the shared cells and the completeness of the data.
This is the first comparative indicator, not a validated harmonization.

For Sasha, for FastAPI:

```python
from fires_data import grid_calendar
report = grid_calendar(store, "world", start, end, bbox=(22, 44, 41, 53))
```

Detailed units and limitations: GRID_METHOD.md.


The real calculation for August has been verified: the raw sums of 773 697 MODIS and 3 526 897 VIIRS
matched the database; the activity was 285 264 and 723 687 cell-days respectively.
These are two independent series without calibration. For 1 August the result was independently
cross-checked by another way of counting cells. A date that is not loaded correctly gives null.

The ready local snapshots: `var/calendar-world-2024-08.json` and
`var/calendar-ukraine-bbox-2024-08.json`. The second one is the rectangle 22,44,41,53, not the outline of
a country. Recompute when the sources are updated. The calculation time on this computer:
28 seconds for the world, 22 seconds for the rectangle.

## The scale correction experiment

A separate `calibrate` command and the `calibrate_calendar` function were added.
The base calendar still contains two raw series without an automatic correction.
The run uses the training dates before `--split` and keeps the remaining ones for checking.
Raw VIIRS, scaled VIIRS and the constant training
mean of MODIS are compared. The result is experimental, `apply_automatically=false`.
The method and limitations are in CALIBRATION_METHOD.md.

The first run is finished for bbox 22,44,41,53 and August 2024. Train 21 days / test 10 days,
coefficient 0.3342303670. Test MAE: raw 223.30, with correction 34.52,
training mean 46.64. Test R² = 0.0143, so the daily dynamics are explained weakly.
The status improved_on_holdout applies only to this short experiment. All 52 checks
passed; the coefficient and the main metrics were independently cross-checked. The snapshot of the results:
`var/calibration-ukraine-bbox-2024-08.json`, the human-readable report with the same name `.md`.
