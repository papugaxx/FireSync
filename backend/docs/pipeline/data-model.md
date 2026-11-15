# Data model

The pipeline database (`data_pipeline/var/fires.sqlite3`) is defined in `fires_data/schema.sql`. SQLite runs in
WAL mode with foreign keys on. This page explains what each table means and how the API reads them. The Python
access layer is documented in the [pipeline reference](../reference/pipeline.md).

## Tables

```text
products ◄──── availability
    ▲
    │
scopes ◄──── fetch_windows ◄──── detections
    ▲
    └──────── sync_jobs
```

### `products`

One row per NASA product: the combination of instrument family and processing level.

| Column | Meaning |
|---|---|
| `source_code` | Primary key, such as `MODIS_SP` or `VIIRS_NOAA20_NRT` |
| `sensor` | `MODIS` or `VIIRS` |
| `family` | `MODIS`, `VIIRS_SNPP`, `VIIRS_NOAA20`, `VIIRS_NOAA21` |
| `processing` | `SP` or `NRT` |
| `priority` | SP is `2`, NRT is `1`. Higher wins when both exist |
| `expected_platform` | Expected satellite name for VIIRS families; empty for MODIS |

### `scopes`

A named geographic extent that was requested from NASA (`world`, or a bounding box). Unique by bounding box.
`west < east` and `south < north` are enforced by constraints.

!!! warning "Scope is not region"
    A *scope* describes what was **downloaded**. A *region* in the API (`/regions`) describes what a user
    **looks at**: a rectangle or, for most regions, a real country or state border (`boundary` in `config.REGIONS`).
    The FireSync API no longer reads scopes: it uses its own database.

### `availability`

The date range NASA currently reports for each product (`min_date`, `max_date`) and when it was checked.
`plan` uses this to avoid requesting dates NASA does not have.

### `fetch_windows`

**One row per (scope, product, day)**: the unit of downloading and the unit of atomic replacement.

| Column | Meaning |
|---|---|
| `status` | `pending`, `loaded` or `failed` |
| `row_count` | Number of detections stored for this slice |
| `checksum` | SHA-256 of the downloaded body. Required when `loaded` |
| `fetched_at` | When it was downloaded. Required when `loaded` |
| `attempt_count`, `last_attempt_at`, `last_error` | Retry bookkeeping |
| `request_url_redacted` | The request URL with the key removed |

A `loaded` slice with `row_count = 0` is valid: it means NASA answered and returned no detections.
`checksum` lets the pipeline notice when a downloaded slice has changed.

### `detections`

One row per detected hot spot. Each belongs to a `fetch_windows` row and is deleted with it
(`ON DELETE CASCADE`).

| Column | Meaning |
|---|---|
| `observed_at` | UTC timestamp of the satellite pass |
| `sensor`, `satellite` | Instrument and the individual platform. Terra and Aqua are **not** merged under one name |
| `latitude`, `longitude` | Point coordinates (validated to the valid ranges) |
| `frp_mw` | Fire radiative power, in megawatts. May be `NULL`, which is not zero |
| `brightness_k` | Brightness temperature, in kelvin |
| `confidence_raw` | Confidence as NASA gave it (a number for MODIS, a word for VIIRS) |
| `daynight` | `D` or `N` |
| `product_version`, `processing` | Version string and processing level of the row (`SP`, `NRT`, `RT` or `URT`) |
| `scan_km`, `track_km` | Pixel size in the scan and track directions, in kilometres |
| `type_code` | Detection type code |
| `raw_json` | The original record, kept for traceability |
| `record_hash` | Hash used to avoid duplicates; unique within a slice |

### `sync_jobs`

Progress of `sync` runs: planned, completed, skipped and failed units, and a status of `pending`, `running`,
`completed`, `paused` or `failed`. `fires-data status` prints the ten most recent.

## Which slice is read: SP over NRT

A single day of one product family can exist both as SP and as NRT. Readers never add them together. The
"canonical" slice for each (family, day) is the SP slice if one is loaded (even if it is empty), otherwise
the NRT slice. The pipeline implements this once as a SQL common table expression, `_canonical_cte`, and
the pipeline's `Store` uses it. (The FireSync API now reads its own database, `data/firesync.sqlite3`, which
stores one product per day and sensor in the first place; see
[Archive import and NASA updates](archive-and-updates.md).)

Consequences:

- A day that has SP data ignores any NRT data for the same family.
- Different VIIRS platforms (S-NPP, NOAA-20, NOAA-21) remain distinguishable, so each can be selected on its own.
- Each read selects exactly one scope. Results from overlapping scopes must not be summed.

## Reading from Python

```python
from datetime import date
from fires_data import Store, load_settings

store = Store(load_settings().db_path)

rows = store.observations(
    scope_id="world",
    start=date(2024, 8, 1),
    end=date(2024, 8, 1),
    bbox=(22, 44, 41, 53),   # west, south, east, north
    limit=1000,
    offset=0,
)
```

`observations` returns UTC time, coordinates, instrument, satellite, FRP, confidence, version and more.
Other methods: `list_scopes()`, `list_windows(scope_id, start, end)`, `daily_counts(scope_id, start, end)`,
`status(scope_id)`, `list_jobs()` and `get_job(id)`. Connections are created inside each method and are not
shared between FastAPI threads.

!!! note "Mapping to frontend field names"
    `lat = latitude`, `lon = longitude`, `seenBy = sensor`, `date = observed_at[:10]`. The value `BOTH`
    cannot be assigned to a single detection; it requires a separate matching algorithm.

## Backups and copies

Do not copy `fires.sqlite3` with a plain file copy while a loader is writing to it. Use SQLite's own backup
(for example `VACUUM INTO`) to get a consistent snapshot, then verify the copy with a SHA-256 checksum.
`data_pipeline/DATABASE_INFO.json` records the coverage and checksum of the snapshot that was shared with the
backend team.
