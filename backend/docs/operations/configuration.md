# Configuration

FireSync is configured through environment variables and the constants in `config.py`. Nothing needs to change in
code for deployment: every path and address below can be overridden from the environment.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `FIRMS_MAP_KEY` | none (read from `data_pipeline/.env`) | NASA FIRMS key. Needed only for the automatic updates, not to serve the API. |
| `FIRESYNC_DB_PATH` | `data/firesync.sqlite3` | The FireSync database. |
| `FIRESYNC_ARCHIVE_CSV` | `data/raw/NASA_FIRMS_2000_2025.csv` | The archive file `importer.py` reads by default. |
| `FRONTEND_URLS` | `http://localhost:3000,http://127.0.0.1:3000` | Website origins allowed by CORS (comma-separated). |
| `FIRESYNC_AUTO_UPDATE` | `1` | `0` turns the background NASA updates off. |
| `FIRESYNC_UPDATE_HOURS` | `3` | Hours between update runs. |
| `FIRESYNC_UPDATE_MAX_REQUESTS` | `120` | NASA requests per run (one request = one day of one sensor, whole world). |
| `FIRESYNC_UPDATE_MAX_BACKFILL_DAYS` | `400` | How far back an update may reach after the last stored day. |
| `FIRESYNC_UPDATE_INTERVAL_SECONDS` | `1` | Pause between NASA requests. |
| `FIRESYNC_QUOTA_RESERVE` | `100` | NASA transactions left untouched in the quota window. |
| `FIRESYNC_MAX_RESPONSE_MB` | `200` | Largest accepted NASA answer. |
| `FIRESYNC_MAX_DB_GB` | `20` | Updates stop when the database reaches this size. |
| `FIRESYNC_MIN_FREE_GB` | `2` | Updates and the importer stop when less disk space is free. |
| `FIRESYNC_REFRESH_RECENT_DAYS` | `2` | NRT days younger than this are downloaded again. |

An invalid number falls back to its default.

## Where the database is found

The FireSync API, `importer.py` and `updater.py` all use `FIRESYNC_DB_PATH`, by default `data/firesync.sqlite3`
next to `main.py`. The partner pipeline's own command line (`python -m fires_data ...`) still uses its separate
database, found in this order: its `--db` option, the `FIRMS_DB_PATH` environment variable, `FIRMS_DB_PATH` in
`data_pipeline/.env`, then `data_pipeline/var/fires.sqlite3`. The FireSync API no longer reads that file.

## Constants in `config.py`

### Regions

`REGIONS` defines the ready-made regions (`/regions`, `/api/meta/`, `region=` everywhere):

```python
"ukraine": {"name": "Ukraine", "bbox": [22.1, 44.3, 40.2, 52.4]},
```

`bbox` is `[west, south, east, north]` (**longitude first**), or `None` for the whole world. The first five
regions have the ids and rectangles of the fire-calendar frontend (`lib/mock.ts`), so the calendar counts exactly
the rectangle the map draws.

To add or change a region, edit this dictionary and restart the API. The region tables are rebuilt in the
background (a few minutes for the whole archive); until then the old numbers are served.

### Limits

| Constant | Value | Applies to |
|---|---|---|
| `MAX_CALENDAR_DAYS` | 3660 | `/calendar`, `/harmonization` for a ready-made region |
| `MAX_CUSTOM_AREA_DAYS` | 366 | any request with an own `west, south, east, north` rectangle |
| `MAX_MAP_DAYS` | 92 | `/cells` |
| `MAX_POINT_DAYS` | 7 | `/points` |
| `MAX_POINTS_PER_PAGE` | 5000 | `/points` `limit` |
| `MAX_EXPORT_DAYS` | 31 | `/export.csv` |
| `MAX_EXPORT_ROWS` | 1 000 000 | `/export.csv`, `/api/export/` (streamed) |
| `MAX_MAP_CELLS` | 20 000 | `/cells` |
| `MAX_HOTSPOTS` | 10 000 | `/api/hotspots/` (the strongest cells per day are kept) |

## Files and folders created at runtime

| Path | Created by | Notes |
|---|---|---|
| `data/firesync.sqlite3` | `importer.py`, `updater.py` | The database. Back it up; **not** in git. |
| `data/firesync.sqlite3-wal`, `-shm` | SQLite | Normal WAL side files |
| `data/firesync.sqlite3.update.lock` | `updater.py` | Only one update at a time (also across processes) |
| `data/raw/NASA_FIRMS_2000_2025.csv` | you | The archive export; only read. Not needed after the import. |
