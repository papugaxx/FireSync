# Configuration

FireSync is configured through environment variables and the constants in `config.py`. Nothing needs to change in
code for deployment: every path and address below can be overridden from the environment.

## Environment variables

| Variable | Read by | Default | Purpose |
|---|---|---|---|
| `FIRMS_MAP_KEY` | pipeline | none | NASA FIRMS key. Needed only for `availability`, `plan` and `sync`. Not needed to serve the API. |
| `FIRMS_DB_PATH` | pipeline and API | `data_pipeline/var/fires.sqlite3` | Location of the pipeline database. |
| `FIRESYNC_INDEX_PATH` | API | `cache/grid_index.sqlite3` | Location of the fast calendar index. |
| `FIRESYNC_AUTO_REFRESH` | API | `60` | Seconds between checks for new pipeline data. `0` turns the background check off. |
| `FRONTEND_URLS` | API | `http://localhost:3000` | Comma-separated list of website origins allowed by CORS. |

Variables used only by `deploy/update.sh`:

| Variable | Default | Purpose |
|---|---|---|
| `PYTHON` | `<backend>/venv/bin/python` | Interpreter to use |
| `LOCK_FILE` | `/tmp/firesync-update.lock` | Lock that prevents two updates running together |
| `MAX_REQUESTS` | `30` | NASA request budget per run |
| `MIN_FREE_GB` | `5` | Free disk to keep |

Example for production (set in the systemd unit, see [Deployment](deployment.md)):

```text
FRONTEND_URLS=https://firesync.example.com,https://www.firesync.example.com
```

## Where the database is found

The API and the pipeline loader must look at the **same file**. Both use the same rule
(`fires_data.config.load_settings`), in this order:

1. The `--db` command-line option (pipeline CLI only).
2. The `FIRMS_DB_PATH` environment variable.
3. `FIRMS_DB_PATH` in `data_pipeline/.env`. A **relative** path there is resolved against the folder that
   contains the `.env` file, not against the current directory.
4. The default `data_pipeline/var/fires.sqlite3`.

Environment variables therefore beat `.env`. `config.DB_PATH` is computed once, when the API starts.

!!! tip
    On a server, use an **absolute** `FIRMS_DB_PATH` so that the API, the cron job and manual commands cannot
    disagree about which file they use.

## Constants in `config.py`

### Data scope

`SCOPE_ID = "world"` is the default pipeline scope used when a request names a custom rectangle instead of a region.

### Regions

`REGIONS` defines the ready-made regions returned by `/regions`:

```python
"ukraine": {"name": "Украина (прямоугольник)", "bbox": [22.0, 44.0, 41.0, 53.0], "scope": "world"},
```

| Key | Meaning |
|---|---|
| name | Display name shown to users (currently Russian) |
| bbox | `[west, south, east, north]`, or `None` for the whole world. **Longitude first.** |
| scope | Which pipeline scope to read. Change `"world"` to a scope id such as `"ukraine"` if history is loaded separately for that region. |

To add a region, add an entry here. No other change is needed; it appears in `/regions` and works with
`region=<key>` everywhere.

### Limits

These protect the server from very heavy requests. They are enforced in the endpoint handlers and described per
endpoint in the [API overview](../api/overview.md#limits).

| Constant | Value | Applies to |
|---|---|---|
| `MAX_CALENDAR_DAYS` | 3660 | `/calendar` (fast), `/cells`, `/harmonization` |
| `MAX_REFERENCE_DAYS` | 366 | `/calendar?engine=reference` |
| `MAX_POINT_DAYS` | 7 | `/points` |
| `MAX_POINTS_PER_PAGE` | 5000 | `/points` `limit` |
| `MAX_EXPORT_DAYS` | 31 | `/export.csv` |
| `MAX_EXPORT_ROWS` | 200 000 | `/export.csv` |
| `MAX_MAP_CELLS` | 20 000 | `/cells` |

`/calendar/monthly` allows `40 * 366` days; this value is written directly in `main.py`.

## Files and folders created at runtime

| Path | Created by | Notes |
|---|---|---|
| `cache/grid_index.sqlite3` | API or `python grid_index.py` | Derived; safe to delete, it rebuilds. In `.gitignore`. |
| `cache/grid_index.sqlite3-wal`, `-shm` | SQLite | Normal WAL side files |
| `cache/grid_index.lock` | `grid_index.py` | Cross-process refresh lock (Linux/macOS) |
| `cache/update.log` | cron | Output of `update.sh` |
| `data_pipeline/var/fires.sqlite3` | pipeline | Source data. Back it up; **not** in git |
