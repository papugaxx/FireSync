# For Sasha: the code and the real database

The archive holds one folder, data_pipeline: the data module, the SQLite database var/fires.sqlite3, the reading functions for FastAPI, the calendar calculation and a separate correction experiment. You connect the FastAPI routes and the frontend JSON contract in your backend.

## Quick connection

1. Unpack data_pipeline next to the backend.
2. In the backend's Python environment (Python 3.11+), from the project root run:

```bash
python -m pip install -e ./data_pipeline
```

3. Set one absolute FIRMS_DB_PATH pointing to the unpacked var/fires.sqlite3 for the backend and the worker. You can copy .env.example to .env inside data_pipeline and put this path there. An environment variable takes priority over .env. Without an explicit path, var/fires.sqlite3 next to the package itself is used, not the current working folder.
4. Before starting the backend and the updates, run (substitute your own absolute path):

```bash
python -m fires_data --db /full/path/data_pipeline/var/fires.sqlite3 init
```

The command keeps the existing observations and turns on WAL. The database folder must be writable for the -wal/-shm files.
5. Reading a ready database does not need a NASA key. Example:

```python
from datetime import date
from fires_data import Store, load_settings

store = Store(load_settings().db_path)
points = store.observations(
    "world", date(2024, 8, 1), date(2024, 8, 1),
    bbox=(22, 44, 41, 53), limit=1000, offset=0,
)
```

Record fields: latitude, longitude, observed_at (UTC), sensor, satellite, frp_mw, confidence_raw, source_code and others. observations returns pages, by default up to 1000 records. Use Store: it selects SP instead of NRT. Do not add both versions directly and do not add overlapping scopes.

The scope is world. The frontend's region ID is not equal to scope_id. For a region, pass bbox=(west,south,east,north). A rectangle around Ukraine is not equal to the exact border of the country.

## What is loaded

4 893 436 raw observations. August 2024 is fully loaded for the whole world for MODIS and VIIRS NOAA-20. There is also an early segment of MODIS and some separate check days. This is not the whole world history. The coverage and the SHA256 of the copy are in DATABASE_INFO.json; the extreme dates do not mean a fully loaded interval.

## Calendar and experiment

grid_calendar(store,scope_id,start,end,bbox=...) gives the daily series of the two instruments on the 0.1° grid. JSON examples are in examples. The units are active cells per day and cell-days per period; these are not separate fires or burned area. Values that are not loaded are null.

A month for the world took 28 seconds. Use the ready JSON or a background task that checks the versions of the input data. A thread pool does not make the calculation instant.

calibrate_calendar is a separate limited experiment: train 1–21 Aug / test 22–31 Aug, bbox 22,44,41,53. The correction is not applied automatically globally. The daily dynamics are explained weakly on the check. The conditions are in CALIBRATION_METHOD.md, the results in examples/calibration-ukraine-bbox-2024-08.md.

## New NASA data

The private .env and MAP_KEY are not included. Your own MAP_KEY is needed only for availability/sync. The loading commands with saved progress are in README.md. One ingestion worker; the update schedule and fetching what is missing over HTTP are not connected yet.

The database is a consistent SQLite VACUUM INTO snapshot. The source database was not changed. The code passed 52 checks. No commits/pushes were made.
