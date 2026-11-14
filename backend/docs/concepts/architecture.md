# Architecture

## Data flow

```text
NASA FIRMS ──(data pipeline: fires_data)──► data_pipeline/var/fires.sqlite3     raw detections (GBs)
                                                   │  opened read-only
                                                   ▼
                              grid_index.py: points → 0.1° cells per day
                                                   │
                                                   ▼
                                  cache/grid_index.sqlite3                        small cell index
                                                   │
                  browser ──► main.py (FastAPI) ───┘   + db.py for raw points and CSV
```

There are **two SQLite databases** with very different roles:

| Database | Written by | Size (reference data) | Purpose |
|---|---|---|---|
| `data_pipeline/var/fires.sqlite3` | the pipeline (`fires_data`) | ~3 GB, millions of points | Source of truth: raw detections from NASA |
| `cache/grid_index.sqlite3` | `grid_index.py` | ~64 MB, ~1 million rows | Derived cache: per-day, per-cell counts. Safe to delete; it rebuilds itself |

The API **never writes** to the pipeline database. It opens it with a SQLite URI in read-only mode
(`file:...?mode=ro`).

## Modules

| Module | Responsibility |
|---|---|
| [`main`](../reference/main.md) | HTTP layer only: parse and validate parameters, call the layers below, return JSON. |
| [`grid_index`](../reference/grid_index.md) | Builds, refreshes and queries the cell index. All calendar, monthly and map-cell queries go through it. |
| [`db`](../reference/db.md) | Direct reads from the pipeline database: raw points, CSV streaming, and the slow reference calendar. |
| [`analytics`](../reference/analytics.md) | Pure math (levels, harmonization, anomaly). No database and no HTTP, which makes it easy to test. |
| [`config`](../reference/config.md) | Settings, regions and limits. Also puts `data_pipeline/` on `sys.path`. |
| [`fires_data`](../reference/pipeline.md) | The pipeline package: NASA client, parsing, storage, grid analytics, calibration, CLI. |

!!! note "Import order"
    Modules begin with `import config` before importing anything from `fires_data`. `config` adds the pipeline
    folder to `sys.path`, so the import works however the app is started.

## Why the index exists

The pipeline's `grid_calendar()` scans every raw point on every call. For the whole world for one month that is
about 28 seconds; for the Ukraine rectangle about 22 seconds. That is too slow for a website.

The index does that work **once**. For each (scope, day, cell) it stores how many points MODIS saw and how many
VIIRS saw. A calendar is then a `GROUP BY day` over a small table.

| Query (August 2024, real data) | Pipeline calculation | Index |
|---|---|---|
| World calendar, one month | ~28 s | ~0.25 s |
| Ukraine calendar, one month | ~22 s | ~0.12 s |

### Why the numbers can be trusted

- The grid rule, the MODIS/VIIRS composition and the SP-over-NRT rule are the same as the pipeline's. The SP/NRT
  rule is imported from the pipeline rather than copied.
- The index output was compared against the pipeline's reference files for world and Ukraine in August 2024
  and matched on every day, to the unit.
- The test suite repeats this comparison on every run (`test_fast_index_matches_partner_*`).
- Any request can be recomputed with the original method by passing `engine=reference` to `/calendar`.

## Index schema

```sql
meta     (key, value)                              -- index_version, signature, last_refresh
scopes   (id, name, west, south, east, north)      -- copy of the pipeline's scopes
windows  (scope_id, channel, day, window_id,       -- which slice each day was built from
          source_code, checksum, fetched_at, observations)
cells    (scope_id, day, cell_y, cell_x, modis, viirs)   -- the main table
```

- `cells` is a `WITHOUT ROWID` table keyed by `(scope_id, day, cell_y, cell_x)`, which is fast for "many cells
  on a few days". A second index `cells_by_place (scope_id, cell_y, cell_x, day)` makes a small region over many
  years fast. `ANALYZE` runs after changes so SQLite picks the better order.
- Cells with zero points in both series are not stored.
- `windows` records, for every day and series, which pipeline slice and which **checksum** the cells came from.
  This is what makes incremental refresh possible.
- `INDEX_VERSION` is stored in `meta`. If the code's version changes, the index tables are dropped and rebuilt.

## How the index stays current

Each loaded slice (day + source) in the pipeline database has a checksum.

1. **Fingerprint.** `partner_signature()` combines the count, maximum id and latest fetch time of loaded
   slices plus the number of scopes into one short string. It changes after any download. It is cheap to compute.
2. **Compare.** `needs_refresh()` checks it against the signature saved at the last refresh.
3. **Rebuild only what changed.** `refresh()` determines the canonical slice for every (channel, day), compares
   `(window_id, checksum)` against the `windows` table, and recomputes only days that differ. Days that disappeared
   are removed. Each day is rebuilt in a single transaction, so a day is never left half-updated.
4. **Publish.** Only after the refresh finishes is `last_refresh` written. A connection to an index without
   `last_refresh` raises `IndexNotReady`, so partially built numbers are never served.

A refresh after a new NASA download therefore takes seconds, not minutes.

### Automatic refresh in the API

On startup, `lifespan` in `main.py` calls `grid_index.start_auto_refresh(config.AUTO_REFRESH_SECONDS)`. This starts
a daemon thread that checks `needs_refresh()` every `FIRESYNC_AUTO_REFRESH` seconds (default 60) and refreshes
when the pipeline database has changed. No restart is needed. Setting the interval to `0` disables it.
`/status` exposes the thread's `last_error` and `last_result`.

### Concurrency

Only one refresh may run at a time:

- Inside a process, a `threading.Lock` prevents overlap.
- Across processes (for example two uvicorn workers and the cron job), an exclusive `flock` on
  `cache/grid_index.lock` does the same. A refresh that cannot get the lock returns `{"status": "busy"}`.

!!! warning "Windows"
    `fcntl` does not exist on Windows, so the cross-process lock is skipped there. The in-process lock still
    works. On Windows, avoid running `grid_index.py` while the API's auto-refresh is also running. The production
    target (Ubuntu) has the full lock.

SQLite runs in WAL mode so API reads continue while a refresh writes.

## Request lifecycle

1. **Middleware**: `GZipMiddleware` compresses responses over 1000 bytes. `CORSMiddleware` allows `GET` from
   `FRONTEND_URLS`. A custom middleware adds `X-Process-Time-Ms` to every response.
2. **Parameters**: the `Period` and `Area` dependencies validate dates and region/bounding box. Invalid
   combinations raise `ValueError`.
3. **Handler**: calls `grid_index` (fast path) or `db` (raw points, reference calculation), then `analytics`.
4. **Errors**: exception handlers map failures to a single JSON shape.

| Exception | HTTP status | When |
|---|---|---|
| `ValueError` | 400 | Business-rule violation: reversed dates, unknown region, period too long |
| `RequestValidationError` | 422 | Malformed parameter: not a date, out of numeric range |
| `IndexNotReady` | 503 + `Retry-After: 30` | Index not built yet |
| `StorageError` | 503 | Pipeline database missing or unreadable |
| `PipelineError` | 500 | Other pipeline failure |

All error bodies look like `{"error": "text"}`; 422 also includes a `details` list.
