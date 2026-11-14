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
| `503` with an "index is still being built" message (Russian text) | The fast index does not exist yet (first run) or an old index version is being rebuilt. Wait a minute and retry; the response has `Retry-After: 30`. Or run `python grid_index.py`. |
| `503` "database unavailable" | The pipeline database file was not found. Check that `data_pipeline/var/fires.sqlite3` exists, or set `FIRMS_DB_PATH`. `/status` shows `partner_database.found`. |
| `400` period too long | Each endpoint has a maximum period. See [limits](../api/overview.md#limits). Split the request into several. |
| `400` "either region or west/south/east/north" | Both a `region` and bounding-box values were sent. Send only one. |
| `400` "all four boundaries are needed" | A bounding box needs `west`, `south`, `east` **and** `north`. |
| `400` "west < east and south < north" | The order is longitude first, then latitude. Check that you did not send `[south, west, north, east]`. |
| `400` area outside the loaded scope | The rectangle goes beyond the extent of the downloaded data scope. |
| `422` with a `details` list | A parameter is malformed or out of range, for example not `YYYY-MM-DD`, or `west=500`. |
| Browser shows a CORS error | The site's address is not in `FRONTEND_URLS`. Add it (comma-separated, with scheme and without a trailing slash) and restart the API. |

## Data that looks wrong

| Symptom | Explanation |
|---|---|
| Calendar values are `null` | The day is **not loaded** in the database. This does not mean "no fires". Check `coverage` in the response or `fires_data status`. |
| `totals` is `null` | At least one requested day of that series is missing. Narrow the period to loaded days. |
| `/anomaly` returns `insufficient_history` | It needs at least 3 other years with complete data for that month. Load more history; see [Command line](../pipeline/cli.md#loading-history). |
| `/anomaly` returns `month_not_loaded` | The requested month is not completely loaded. |
| MODIS and VIIRS differ a lot | Expected: VIIRS detects more cells. That is why [harmonization](../concepts/harmonization.md) exists. |
| Numbers differ slightly from the pipeline's own calendar for a custom rectangle | The API expands rectangles to whole 0.1° cells; the pipeline filters by the exact rectangle. See [Regions are whole cells](../concepts/grid-and-calendar.md#regions-are-whole-cells). Compare using a rectangle that lies on grid lines. |
| New NASA data does not appear | Check `/status` → `index.auto_refresh` for `last_error`. Run `python grid_index.py` to force a refresh and read its output. |
| `/calendar?engine=reference` is slow | That is expected: it recomputes from raw points (~25 s for a month of world data). Use `fast` normally. |

## Updates and the index

| Symptom | Cause and fix |
|---|---|
| `update.sh` logs "update already running" | Another update holds the lock. This is normal and the script exits successfully. If it persists, check for a stuck process and the lock file (`LOCK_FILE`). |
| `sync` exits with code `2` | It paused after reaching the request budget or the free-disk reserve. Re-run the same command to continue. |
| Refresh returns `{"status": "busy"}` | Another refresh is in progress (another worker or process). Try again shortly. |
| The index seems inconsistent | It is a cache. Stop the API, delete `cache/grid_index.sqlite3*`, then run `python grid_index.py`. The pipeline database is untouched. |
| Windows: two refreshes at once | Cross-process locking uses `fcntl`, which Windows does not have. Do not run `grid_index.py` while the API's auto-refresh is active, or set `FIRESYNC_AUTO_REFRESH=0` while developing. |

## Documentation build

| Symptom | Cause and fix |
|---|---|
| `mkdocs: command not found` | Install the docs tools: `pip install -r requirements-docs.txt`, in the active virtual environment. |
| `Could not collect 'main'` or a similar mkdocstrings error | Run `mkdocs` from the `backend/` folder so that `paths: [., data_pipeline]` in `mkdocs.yml` resolves. |
| Warning about a link target not found | A page link or anchor is wrong. `mkdocs build --strict` turns such warnings into errors so they get fixed. |
| A function appears in the reference with no description | It has no docstring. Add one; see [Writing documentation](../development/documentation.md). |
