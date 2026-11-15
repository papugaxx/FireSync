# FireSync backend

FireSync is an API for a fire-activity calendar built from the NASA **MODIS** and **VIIRS** satellite
fire detections, placed on one common 0.1° grid.

The 2000–2025 archive and every new NASA FIRMS day are stored in one database (`data/firesync.sqlite3`).
This backend turns them into a calendar, a map layer, a harmonized MODIS ↔ VIIRS series and CSV exports,
and serves the fire-calendar website.

## Where to start

| I want to... | Go to |
|---|---|
| Install and run the API | [Getting started](getting-started.md) |
| Understand what the numbers mean | [Grid and calendar](concepts/grid-and-calendar.md) |
| Understand the MODIS ↔ VIIRS merge | [Harmonization](concepts/harmonization.md) |
| See how the pieces fit and why it is fast | [Architecture](concepts/architecture.md) |
| Call the API from a frontend | [HTTP API overview](api/overview.md) and [Endpoints](api/endpoints.md) |
| Import the archive, understand the NASA updates | [Archive import and NASA updates](pipeline/archive-and-updates.md) |
| Configure or deploy a server | [Configuration](operations/configuration.md) and [Deployment](operations/deployment.md) |
| Fix a problem | [Troubleshooting](operations/troubleshooting.md) |
| Run tests, work on the website, or edit these docs | [Testing](development/testing.md), [Frontend](development/frontend.md), [Writing documentation](development/documentation.md) |
| Look up a Python function | the **API reference** section |

## How it fits together

```
NASA_FIRMS_2000_2025.csv ──(importer.py, once)──┐
                                                 ▼
NASA FIRMS API ──(updater.py, background)──► data/firesync.sqlite3
                                                 │
                     fire-calendar ──► /api/... ─┤  frontend_api.py + reports.py
                     other clients ──► /calendar, /cells, ... (main.py)
```

| Module | Responsibility |
|---|---|
| [`main`](reference/main.md) | General endpoints, errors, CORS; starts the background NASA updater |
| [`frontend_api`](reference/frontend_api.md) | The `/api/...` endpoints of the fire-calendar website |
| [`store`](reference/store.md) | The database: compressed day blocks of detections and region tables |
| [`reports`](reference/reports.md) | Calendar, months, map cells and points for a region or rectangle |
| [`geo`](reference/geo.md) | Real country/state borders: tests every detection against the border of a region |
| [`importer`](reference/importer.md) | Loads the 2000–2025 archive CSV (once) |
| [`updater`](reference/updater.md) | Downloads new days from the NASA FIRMS API |
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
│   ├── main.py            general endpoints
│   ├── frontend_api.py    /api/... for the website
│   ├── store.py           the database (data/firesync.sqlite3)
│   ├── reports.py         calendar, months, cells, points
│   ├── geo.py             real borders for the region filter (geodata/boundaries.geojson)
│   ├── importer.py        archive CSV → database
│   ├── updater.py         NASA FIRMS API → database (background)
│   ├── data/              database and raw/ archive CSV (not in git)
│   ├── geodata/           boundaries.geojson (Natural Earth 1:10m borders)
│   ├── tools/             build_boundaries.py (rebuilds geodata/boundaries.geojson)
│   ├── analytics.py       levels, harmonization, anomalies
│   ├── config.py          settings
│   ├── tests/             API tests
│   ├── deploy/            systemd, nginx, cron, update script
│   ├── docs/ mkdocs.yml   this documentation
│   └── data_pipeline/     NASA loader and SQLite storage (package fires_data)
├── fire-calendar/         Next.js website
└── run.py                 starts the backend and the website together
```

The `backend/_old/` folder holds earlier versions of some files (`config.py`, `db.py`, `main.py`). It is kept locally and is not in git.

## About the project

FireSync is a hackathon research prototype built for the NASA Space Apps Challenge 2026, designed for researchers,
regional analysts and land managers.

## Data and attribution

- Fire detections: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) (MODIS Terra/Aqua, VIIRS NOAA-20).
- Basemap imagery: Esri, Maxar, Earthstar Geographics.
- Athens consistency check: contains modified Copernicus Sentinel data (2024), processed by ESA.

## SI assistance

SI was used for: learning/explaining new things, fixing code errors, spellchecking everything.
