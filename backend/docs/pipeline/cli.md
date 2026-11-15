# Command line

The data pipeline (`data_pipeline/`, Python package `fires_data`) downloads NASA FIRMS detections into SQLite.
It uses only the Python standard library and does not depend on FastAPI.

Run commands from the `data_pipeline` folder, either as `python -m fires_data <command>` or, after
`pip install -e ./data_pipeline`, as `fires-data <command>`.

## Setup

1. Request a free key: [NASA FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/) (it arrives by email).
2. Copy `.env.example` to `.env` and fill in the key.

```text
FIRMS_MAP_KEY=your_real_key
FIRMS_DB_PATH=var/fires.sqlite3
```

!!! danger "Keep the key private"
    Do not commit `.env` (it is in `.gitignore`) and do not paste the key into chats. `doctor` reports only
    *whether* a key is configured, never its value. Request URLs saved in the database have the key redacted.

The pipeline reads `.env` itself; no `python-dotenv` is needed. Environment variables override `.env`.
See [Configuration](../operations/configuration.md#where-the-database-is-found) for how the database path is resolved.

## Global options

| Option | Description |
|---|---|
| `--db PATH` | SQLite path. Default is `var/fires.sqlite3` next to the package. |
| `--env-file PATH` | Use a different configuration file. |

## Commands

| Command | Contacts NASA? | Purpose |
|---|---|---|
| `init` | no | Create the schema and the `world` scope. Keeps existing data. |
| `doctor` | no | Check local configuration (Python version, database path, whether a key exists). |
| `availability` | yes | Fetch and cache the date range each NASA product currently offers. |
| `plan` | yes (or `--cached`) | Preview which daily slices a request would download. |
| `sync` | yes | Download, validate and save the slices. |
| `status` | no | Show database contents and the last ten jobs. |
| `observations` | no | Print stored detections as JSON. |
| `calendar` | no | Compute the daily common-grid report from the local database. |
| `calibrate` | no | Run the MODIS/VIIRS scaling experiment. |

### Choosing what to load

`plan` and `sync` share these options:

| Option | Description |
|---|---|
| `--from YYYY-MM-DD` `--to YYYY-MM-DD` | An explicit period. |
| `--recent-days N` | The last N complete UTC days, ending yesterday (1 to 31). |
| `--include-today` | With `--recent-days`, also include today's incomplete day. |
| `--all-history` | From the earliest date NASA offers for the chosen products. Cannot be combined with `--from`. |
| `--area world` | The whole planet (default). |
| `--bbox W S E N` | A rectangle instead. Order is **west south east north**. |
| `--scope-id`, `--scope-name` | Name the saved scope (otherwise a hash-based id is generated). |
| `--sources ...` | `auto` (default) or specific products, see below. |
| `--refresh` | Re-download dates that are already loaded. |
| `--refresh-recent-days N` | How many recent days are always re-downloaded (default 3). |
| `--cached` | `plan` only: use the availability already saved in the database, without contacting NASA. |

Use exactly one of `--from/--to`, `--recent-days`, or `--all-history`.

**Source codes** are `<FAMILY>_<PROCESSING>`:

| Family | Instruments / platforms |
|---|---|
| `MODIS` | Terra and Aqua |
| `VIIRS_SNPP` | S-NPP |
| `VIIRS_NOAA20` | NOAA-20 |
| `VIIRS_NOAA21` | NOAA-21 |

Each has `_SP` (standard processing) and `_NRT` (near real time), for example `MODIS_SP` or `VIIRS_NOAA20_NRT`.
With `auto`, SP or NRT is chosen per family and day. The calendar uses MODIS and VIIRS NOAA-20 only.

### `sync` controls

| Option | Default | Description |
|---|---|---|
| `--batch-days {1..5}` | `1` | Days per NASA request. |
| `--max-requests N` | `20` | Request budget per run. `0` means unlimited. |
| `--min-interval SECONDS` | `1.0` | Minimum gap between requests. |
| `--quota-reserve N` | `100` | Stop before the NASA quota drops below this. |
| `--min-free-gb GB` | `30` | Keep this much disk free. The job pauses safely if the reserve would be crossed. |

## Typical workflows

### First check

```bash
python -m fires_data init
python -m fires_data doctor
python -m fires_data availability
python -m fires_data plan --area world --recent-days 1 --sources MODIS_NRT VIIRS_NOAA20_NRT
python -m fires_data sync --area world --recent-days 1 --sources MODIS_NRT VIIRS_NOAA20_NRT --max-requests 2
python -m fires_data status
```

`--recent-days 1` means yesterday (UTC). If NASA does not report availability for a needed day, `plan` shows it;
dates are never invented.

### Loading history

Always preview first:

```bash
python -m fires_data plan --area world --all-history
```

Then load in bounded portions. Re-running the same command continues where it stopped:

```bash
python -m fires_data sync --area world --all-history --batch-days 5 --max-requests 100
```

A whole world archive is very large (hundreds of gigabytes over many years), so for demos load history for one
to three regions instead:

```bash
python -m fires_data plan --bbox 22 44 41 53 --scope-id ukraine --all-history --sources MODIS_SP VIIRS_NOAA20_SP
```

!!! warning "The pipeline database and the API"
    The FireSync API no longer reads this database (it uses `data/firesync.sqlite3`, see
    [Archive import and NASA updates](archive-and-updates.md)), and a region has no `scope` setting in
    `config.REGIONS`. Data loaded with `fires_data` is for the pipeline's own commands. Scopes that overlap are
    not added together, because that would count the same detection twice.

### Keeping data fresh

```bash
python -m fires_data sync --area world --recent-days 3 --include-today \
  --sources MODIS_NRT VIIRS_NOAA20_NRT VIIRS_NOAA21_NRT --max-requests 20
```

This includes today and the two previous UTC days. Today's data is incomplete. The most recent days are
re-downloaded by default. On the server this is done by `deploy/update.sh` via cron; see
[Deployment](../operations/deployment.md#scheduled-updates). Do not run several syncs of the same area at once.

### Inspecting and computing locally

```bash
python -m fires_data status
python -m fires_data observations --scope world --from 2024-08-01 --to 2024-08-01 --sensor MODIS --limit 5
python -m fires_data calendar --scope world --from 2024-08-01 --to 2024-08-31 --bbox 22 44 41 53
python -m fires_data calibrate --scope world --from 2024-08-01 --to 2024-08-31 --split 2024-08-22 --bbox 22 44 41 53
```

`calendar` and `calibrate` read only the local database and print JSON. `calendar` takes about 20-30 seconds on
the full database; this is exactly the slowness that the API's index avoids.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed |
| `1` | Error |
| `2` | `sync` paused (request budget or disk reserve reached). Re-run to continue. |
| `130` | Interrupted with Ctrl+C. Already-committed daily slices are kept. |

## Behaviour worth knowing

- **Resumable.** Progress is stored per daily slice, so a stopped job resumes without repeating finished days.
- **Atomic.** A day is replaced as a whole. A failed or invalid response never overwrites a previous good slice.
- **Validated.** A response is checked as real CSV, not just by HTTP 200. A header with no rows means zero
  detections; HTML, error text or an empty body are rejected.
- **Correction-safe.** Corrected FRP/confidence values or disappeared temporary records do not turn into extra
  observations.
- **Zero is not proof.** Zero detections does not prove there was no fire, and a downloaded response does not
  prove full satellite coverage. A day that is absent from the database means "not loaded".
- **Dateline.** A single `--bbox` that crosses the antimeridian is not supported. Use `--area world` or split it.

## Methodology documents

These documents sit next to the code and are the authoritative method descriptions. Their
content is summarized in [Grid and calendar](../concepts/grid-and-calendar.md) and
[Harmonization](../concepts/harmonization.md).

| File | Content |
|---|---|
| `data_pipeline/GRID_METHOD.md` | The 0.1° grid method, units and limits |
| `data_pipeline/CALIBRATION_METHOD.md` | The scaling experiment, its train/test design and criteria |
| `data_pipeline/LIVE_STATUS.md` | A dated snapshot of what is actually loaded |
| `data_pipeline/examples/` | Saved reference outputs used to verify the fast index |
