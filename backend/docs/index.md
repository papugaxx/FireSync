# FireSync backend

FireSync is an API for a fire-activity calendar built from the NASA **MODIS** and **VIIRS** satellite
fire detections, placed on one common 0.1° grid.

The NASA data is downloaded by the data pipeline (`data_pipeline/`). This backend turns it into a
calendar, a map layer, a harmonized MODIS ↔ VIIRS series, and CSV exports.

## Where to start

| I want to... | Go to |
|---|---|
| Install and run the API | [Getting started](getting-started.md) |
| Understand what the numbers mean | [Grid and calendar](concepts/grid-and-calendar.md) |
| Understand the MODIS ↔ VIIRS merge | [Harmonization](concepts/harmonization.md) |
| See how the pieces fit and why it is fast | [Architecture](concepts/architecture.md) |
| Call the API from a frontend | [HTTP API overview](api/overview.md) and [Endpoints](api/endpoints.md) |
| Download or update NASA data | [Command line](pipeline/cli.md) and [Data model](pipeline/data-model.md) |
| Configure or deploy a server | [Configuration](operations/configuration.md) and [Deployment](operations/deployment.md) |
| Fix a problem | [Troubleshooting](operations/troubleshooting.md) |
| Run tests, work on the website, or edit these docs | [Testing](development/testing.md), [Frontend](development/frontend.md), [Writing documentation](development/documentation.md) |
| Look up a Python function | the **API reference** section |

## How it fits together

```
NASA FIRMS ──(data pipeline)──► data_pipeline/var/fires.sqlite3
                                        │  read-only
                                        ▼
                     grid_index.py: points → 0.1° cells per day
                                        │
                                        ▼
                        cache/grid_index.sqlite3
                                        │
        browser ──► main.py (FastAPI) ──┘   + db.py for points and CSV
```

| Module | Responsibility |
|---|---|
| [`main`](reference/main.md) | API endpoints: accept parameters, validate them, return JSON |
| [`grid_index`](reference/grid_index.md) | Fast calendar index: points are placed into cells once, so calendars are computed instantly |
| [`db`](reference/db.md) | Data read straight from the pipeline database: individual points, CSV, reference calculation |
| [`analytics`](reference/analytics.md) | Math only: coloring levels, MODIS/VIIRS harmonization, anomalies |
| [`config`](reference/config.md) | Settings: paths, regions, limits |
| [`fires_data`](reference/pipeline.md) | The data pipeline package: NASA client, storage, parsing, calibration |

## Main concepts

- **Active cell**: a 0.1° cell (about 10 km) where a satellite detected at least one fire in a UTC day.
  It is not a fire count and not a burned area.
- **Missing vs. zero**: `null` means the day was not loaded, not that there were no fires.
- **SP over NRT**: for each day and satellite family, standard-processing data is preferred and
  near-real-time data is the fallback.
- **Harmonization**: a coefficient `k` is fitted so that MODIS ≈ k × VIIRS on training days, then checked
  on days the model has not seen.

These are explained in full in [Grid and calendar](concepts/grid-and-calendar.md) and
[Harmonization](concepts/harmonization.md).

## Running the API

```bash
python -m uvicorn main:app --reload
```

Interactive endpoint documentation is then available at <http://localhost:8000/docs>.
Full installation steps, including Windows, are in [Getting started](getting-started.md).

## Project layout

```text
FireSync/
├── backend/               FastAPI app, fast index, deployment files, and this documentation
│   ├── main.py            endpoints
│   ├── grid_index.py      fast calendar index
│   ├── db.py              raw points, CSV, reference calendar
│   ├── analytics.py       levels, harmonization, anomalies
│   ├── config.py          settings
│   ├── tests/             API tests
│   ├── deploy/            systemd, nginx, cron, update script
│   ├── docs/ mkdocs.yml   this documentation
│   └── data_pipeline/     NASA loader and SQLite storage (package fires_data)
└── fire-calendar/         Next.js website
```

The `backend/_old/` folder holds earlier versions of some files. It is kept locally and is not in git.
