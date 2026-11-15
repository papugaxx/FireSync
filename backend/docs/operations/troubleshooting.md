# Troubleshooting

## Setup and startup

| Symptom | Cause and fix |
|---|---|
| `requires a different Python` during `pip install -e ./data_pipeline` | Python is older than 3.11. Install 3.11+ and recreate the virtual environment. |
| `No module named 'fires_data'` or `'fastapi'` | The terminal picked up a global `uvicorn` instead of the one in the virtual environment. Activate the venv and start with `python -m uvicorn main:app --reload`. Check with `which python` (macOS/Linux) or `Get-Command python` (PowerShell): it must point into `backend/venv`. |
| `Address already in use` | The API is already running in another window, or another program has the port. Use another port: `--port 8001`. `mkdocs serve` also defaults to port 8000. |
| Windows: `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `venv\Scripts\activate.bat` from `cmd`. |

## API responses

| Symptom | Cause and fix |
|---|---|
| `503` "The fire database has not been created yet" | `data/firesync.sqlite3` does not exist. Run `python importer.py` (or copy the file from a teammate), or set `FIRESYNC_DB_PATH`. |
| `400` period too long | Each endpoint has a maximum period. See [limits](../api/overview.md#limits). Split the request into several. |
| `400` "either region or west/south/east/north" | Both a `region` and bounding-box values were sent. Send only one. |
| `400` "all four boundaries are needed" | A bounding box needs `west`, `south`, `east` **and** `north`. |
| `400` "west < east and south < north" | The order is longitude first, then latitude. Check that you did not send `[south, west, north, east]`. |
| `400` "For an own rectangle the period is limited" | Own rectangles are computed from the detections; use a ready-made region for long periods. |
| `422` with a `details` list | A parameter is malformed or out of range, for example not `YYYY-MM-DD`, or `west=500`. |
| Browser shows a CORS error | The site's address is not in `FRONTEND_URLS`. Add it (comma-separated, with scheme and without a trailing slash) and restart the API. |

## Data that looks wrong

| Symptom | Explanation |
|---|---|
| A region's numbers are lower than the same rectangle | Expected for regions with a real border (Ukraine, Argentina, Australia, California, Amazonas, Siberia): only detections inside the border are counted, not those of neighbouring countries inside the rectangle. Use an own `west/south/east/north` rectangle to count the plain box. |
| Calendar values are `null` | The day is **not stored** (no data, or an instrument outage). This does not mean "no fires". Check `coverage` in the response or `/status`. |
| `totals` is `null` | At least one requested day of that series is missing. Narrow the period to loaded days. |
| `/anomaly` returns `insufficient_history` | It needs at least 3 earlier years with complete data for that month. |
| `/anomaly` returns `month_not_loaded` | The requested month is not completely loaded. |
| MODIS and VIIRS differ a lot | Expected: VIIRS detects more cells. That is why [harmonization](../concepts/harmonization.md) exists. |
| Numbers differ slightly from the pipeline's own calendar for a custom rectangle | The API expands rectangles to whole 0.1° cells; the pipeline filters by the exact rectangle. See [Regions are whole cells](../concepts/grid-and-calendar.md#regions-are-whole-cells). Compare using a rectangle that lies on grid lines. |
| New NASA data does not appear | Check `/api/updates/` (`update.message`, `last_completed_run.stopped_because`). Run `python updater.py` and read its output. Without `FIRMS_MAP_KEY` in `data_pipeline/.env` nothing is downloaded. |
| The website still shows demo data | `fire-calendar/.env.local` needs `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`; restart `npm run dev`. |

## Import and updates

| Symptom | Cause and fix |
|---|---|
| The importer stopped (Ctrl+C, power, disk) | Run the same command again: it continues from the last saved point. Nothing is counted twice. |
| `Stopped: the disk is almost full` | Free some space (the database grows to about 3 GB), then run the importer again. |
| An update says "Another update is already running" | A run from the API thread or another terminal holds the lock. This is normal. |
| An update stops at the request limit | Normal during catch-up; the next run starts after 10 minutes and continues. |
| An update stops with "quota" | The NASA transaction quota is nearly used. The next run continues after the quota window resets. |
| Region numbers look stale after editing `config.REGIONS` | The region tables are rebuilt in the background after a restart (a few minutes). |
| `Region 'x': the border 'country:XXX' is not in boundaries.geojson` | A region names a border that has not been extracted yet. Run `python tools/build_boundaries.py` from `backend/` (it needs the network, or `--from-folder DIR` with the Natural Earth files) and restart. |

## Documentation build

| Symptom | Cause and fix |
|---|---|
| `mkdocs: command not found` | Install the docs tools: `pip install -r requirements-docs.txt`, in the active virtual environment. |
| `Could not collect 'main'` or a similar mkdocstrings error | Run `mkdocs` from the `backend/` folder so that `paths: [., data_pipeline]` in `mkdocs.yml` resolves. |
| Warning about a link target not found | A page link or anchor is wrong. `mkdocs build --strict` turns such warnings into errors so they get fixed. |
| A function appears in the reference with no description | It has no docstring. Add one; see [Writing documentation](../development/documentation.md). |
