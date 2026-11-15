# FireSync

**A calendar of satellite-detected burning activity, built from NASA MODIS and VIIRS with the source context kept visible.**

NASA Space Apps Challenge 2026 · Hackathon research prototype

FireSync turns NASA FIRMS fire detections into a calendar, a map layer and a CSV export, and puts the MODIS and VIIRS records side by side on one shared grid so they can actually be compared.

---

## Why this exists

MODIS and VIIRS both report thermal hotspots, but their raw counts cannot be compared directly. They differ in resolution (MODIS ~1 km, VIIRS 375 m), sensitivity and overpass timing. For August 2024 worldwide, MODIS (Terra + Aqua) reported about **0.77 M** hotspot detections while VIIRS (NOAA-20) reported about **3.53 M**. That gap comes from the observing system, not from more fire on the ground.

FireSync addresses this by:

1. Putting both records on **one fixed 0.1° WGS84 grid and UTC day**, so each occupied cell counts once per day.
2. Always showing **which sensor** a number comes from and **whether the day was actually loaded**.
3. Offering an **experimental, honestly validated** MODIS ↔ VIIRS scale factor, never applied automatically.

> Detected hotspots can include agricultural burning and other thermal sources. An *active cell* is not a number of fires and not a burned area.

## Features

- **Regional exploration**: choose a region, month and day; inspect the calendar and both sensor layers.
- **Daily calendar**: active 0.1° cells per UTC day for MODIS and VIIRS, with 0–4 color levels and a count of cells seen by both.
- **Monthly and year-by-year views**, with completeness (`complete` / `partial` / `missing`) per month.
- **Map layer**: GeoJSON of active cells, most active first.
- **Charts**: monthly activity, area with active fire, Fire Radiative Power, trend and anomaly heatmap.
- **CSV export** of selected detections (streamed, up to 31 days).
- **Harmonization experiment** with a chronological train/holdout split.
- **Fast**: a precomputed cell index makes a world calendar for one month take ~0.25 s instead of ~28 s.

## Using the site

Open the landing page at `/` and go to **Explore** (`/explore`). The screen has a map in the background, a control panel on the left, and region / year / month selectors at the top.

### 1. Select the context

- Use the **Region**, **Year** and **Month** drop-downs at the top. Changing the region zooms the map to it and draws a dashed outline (the world view has none).
- The **Burning activity** calendar on the left shows the chosen month, one cell per day. Colored days had fire activity, grouped into high (turquoise), medium (blue) and low (dark). A day with no fill had no detections, and a dimmed, unclickable day has **no data** (it was not loaded, which is different from zero fires).
- Hover a day to see its active-cell count and the MODIS and VIIRS values.
- **Click a day** to show only that day on the map. Click it again, or press **Show whole month**, to go back to the full month. The line under the calendar tells you how many hotspots are currently on the map.

### 2. Compare the records

- Tick or untick **MODIS** and **VIIRS** to choose which sensor's detections appear on the map.
- Drag the **Fire Radiative Power** slider to keep only hotspots within a chosen FRP range in MW. The right end, "500+ MW", means no upper limit.
- Hover a map point to see its date, sensor (MODIS, VIIRS or both) and FRP.
- Pan by dragging and zoom with the **+ / −** buttons at the bottom right. The mouse wheel does not zoom the map, so the page can scroll normally.

### 3. Keep the evidence

- The **Charts** buttons open floating windows. You can drag them, open several at once, and close them with the **×** (or press the button again):
  - **Monthly activity**: active fire cells per month for the chosen year. Toggle MODIS and VIIRS to compare them. VIIRS is shown on the MODIS scale, and VIIRS data starts in 2012.
  - **Surface**: approximate area of 0.1° grid cells with active fire, in km² per month.
  - **FRP**: mean Fire Radiative Power per month (bars) and the strongest fire (dots).
  - **Trend & Anomaly**: a year × month heatmap. Switch between **Activity** and **Anomaly**, and read the yearly totals with a trend line underneath.
- Clicking a bar, a month or a year inside any chart selects it, so the calendar and map jump to that period.
- **CSV File** (bottom of the left panel) downloads the hotspots currently shown on the map: date, latitude, longitude, sensor and FRP. It respects your day, sensor and FRP filters. The button is disabled when no points are on the map.

### Reading what you see

- Calendar numbers are **active 0.1° cells**, not numbers of fires and not burned area.
- Hotspots can include agricultural burning and other thermal sources.
- Raw MODIS and VIIRS counts differ because of the instruments, so use the harmonized view for comparison and keep an eye on the sensor labels.
- If the backend is not connected (`NEXT_PUBLIC_API_URL` is empty), the site runs on **mock data** for layout purposes, and the values are not real measurements.

## Results at a glance

**Known-event check: Athens-area fire, 11–13 August 2024** (rectangle 23.5–24.2°E, 37.8–38.4°N)

| UTC day | MODIS | VIIRS NOAA-20 |
|---|---|---|
| Aug 11 | 43 | 179 |
| **Aug 12** | **131** | **256** |
| Aug 13 | 2 | 23 |

On Aug 12 there were 5 MODIS cells and 7 VIIRS cells, with 5 cells seen by both. This supports location and timing consistency; attributing individual hotspots to the event needs further review.

**Regional scaling experiment** (22–41°E, 44–53°N, August 2024; fit on Aug 1–21, holdout Aug 22–31)

| | MAE (MODIS index units) |
|---|---|
| Raw VIIRS | 223.3 |
| VIIRS × 0.334 | **34.5** |
| Training-mean baseline | 46.6 |

Absolute error drops, but holdout R² is only **0.014**: the factor fixes the *level* difference and does not explain day-to-day variation. Ten adjacent days of one August do not show the factor transfers to other months, regions or seasons, so automatic global application is disabled.

## Repository layout

```text
FireSync/
├── backend/                 FastAPI app, database, NASA updates, deployment files, docs
│   ├── main.py              general HTTP endpoints, starts the NASA updater
│   ├── frontend_api.py      the /api/... endpoints the website calls
│   ├── store.py             the database: compressed day blocks + region tables
│   ├── reports.py           calendar, months, map cells, points
│   ├── importer.py          archive CSV (2000–2025) → database, once
│   ├── updater.py           NASA FIRMS API → database, in the background
│   ├── analytics.py         color levels, harmonization, anomalies
│   ├── config.py            paths, regions, update settings, limits
│   ├── data/                firesync.sqlite3 + raw/NASA_FIRMS_2000_2025.csv (not in git)
│   ├── tests/               tests on a generated archive in the real format
│   ├── deploy/              systemd unit, nginx config, cron, update script
│   ├── docs/ + mkdocs.yml   full documentation site
│   └── data_pipeline/       NASA FIRMS loader + SQLite storage (package `fires_data`)
└── fire-calendar/           Next.js website (landing page + /explore calendar)
```

`backend/_old/` holds earlier versions of some files and is local only.

## How it works

```text
data/raw/NASA_FIRMS_2000_2025.csv (50 GB) ──(importer.py, once)──┐
                                                                  ▼
NASA FIRMS API ──(updater.py, every 3 h in the background)──► data/firesync.sqlite3 (~3 GB)
                                                                  │
                         fire-calendar ──► /api/... (frontend_api.py) ─┤  reports.py
                         other clients ──► /calendar, /cells, ... (main.py) ┘
```

The database holds 267 million MODIS (Terra + Aqua, 2000-11-01 →) and VIIRS NOAA-20 (2018-04-01 →) detections.
All detections of one UTC day and sensor are one compressed block (about 11 bytes per detection), and per-region
daily and monthly totals are precomputed, so the calendar answers in milliseconds.

Key rules:

- **Grid**: fixed WGS84 0.1° grid, origin (−180°, −90°), 3600 × 1800 cells, UTC days.
- **MODIS** = Terra + Aqua (occupied cells merged). **VIIRS** = NOAA-20 only.
- **SP over NRT**: one product per day and sensor — final (SP) data when NASA has it, otherwise near-real-time; NRT is replaced by SP later, never added to it.
- **Missing ≠ zero**: `null` / `"status": "missing"` means no data for that day.
- **Regions are whole cells**: rectangles are expanded outward to grid lines, so adjacent regions never double count.
- **Self-updating**: the API downloads new NASA days in the background and rebuilds only the changed months.
- **Verified**: the tests load the same rows with the pipeline's own code and compare its `grid_calendar()` with ours day by day; the import was checked against the raw CSV.

A monthly sum uses *cell-days*. A degree grid changes cell area with latitude, so it is not equal-area.

## Getting started

### Requirements

- Python **3.11+**
- Node.js (for the website)
- The database `backend/data/firesync.sqlite3` (~3 GB, **not in git**): copy it from a teammate, or import it from the archive CSV (`python importer.py`, about 10 minutes).
- A free [NASA FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/) in `backend/data_pipeline/.env`, needed **only** for the automatic updates.

### Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .\data_pipeline

python importer.py                   # once: data\raw\NASA_FIRMS_2000_2025.csv → data\firesync.sqlite3
python -m uvicorn main:app --reload
```

macOS / Linux:

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e ./data_pipeline
python importer.py                   # once: data/raw/NASA_FIRMS_2000_2025.csv → data/firesync.sqlite3
python -m uvicorn main:app --reload
```

Open <http://localhost:8000/docs> for interactive Swagger. About a minute after start the API begins downloading the days after the archive from NASA in the background (`/api/updates/` shows the progress).

> Always start tools as `python -m uvicorn` / `python -m pytest` so the virtualenv's interpreter is used.

### Frontend

```bash
cd fire-calendar
npm install
npm run dev
```

- <http://localhost:3000>: landing page
- <http://localhost:3000/explore>: calendar prototype

Set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` in `fire-calendar/.env.local` to show the real data. While it is empty, the site serves mock data from `lib/mock.ts`.

### NASA data

The archive (2000–2025) is imported once with `python importer.py`. Everything newer is downloaded by the API
itself in the background (`updater.py`), using `FIRMS_MAP_KEY` from `backend/data_pipeline/.env`:

```bash
cd backend
python updater.py --plan      # what would be downloaded
python updater.py             # one update now
python updater.py --status    # what is stored, what the last update did
```

Never commit `.env` or paste the key anywhere. Details: `backend/docs/pipeline/archive-and-updates.md`.

## API

All endpoints are `GET`. The website uses `/api/meta/`, `/api/calendar/`, `/api/month/`, `/api/monthly/`,
`/api/hotspots/` and `/api/export/` (`region`, `year`, `month`), in exactly the shapes of `fire-calendar/types/api.ts`.
The general endpoints take `region=<id>` or `west,south,east,north` (longitude first) and `date_from` / `date_to`
in `YYYY-MM-DD` (UTC).

| Endpoint | Returns |
|---|---|
| `/health` | liveness check |
| `/status` | what is stored, archive import, NASA update state |
| `/regions` | ready-made regions (world, ukraine, argentina, california, amazonas, central_africa, siberia, australia) |
| `/calendar` | daily active cells for MODIS and VIIRS, levels 0–4, shared cells |
| `/calendar/monthly` | monthly aggregation with completeness |
| `/cells` | GeoJSON map layer of active cells |
| `/points` | individual detections, paged (max 7 days) |
| `/harmonization` | merged MODIS/VIIRS series with train/holdout validation |
| `/anomaly` | a month vs. the median of other years (needs ≥ 3 complete other years) |
| `/export.csv` | detections as CSV (max 31 days, 1 000 000 rows) |

Example:

```bash
curl "http://localhost:8000/calendar?date_from=2024-08-01&date_to=2024-08-31&region=ukraine"
```

Errors always have the form `{"error": "..."}` with status 400, 422, 503 or 500. Full parameter and response details: `backend/docs/api/endpoints.md`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FIRMS_MAP_KEY` | none | NASA key (in `data_pipeline/.env`), only for the automatic updates |
| `FIRESYNC_DB_PATH` | `data/firesync.sqlite3` | the database |
| `FIRESYNC_AUTO_UPDATE` | `1` | `0` turns the background NASA updates off |
| `FIRESYNC_UPDATE_HOURS` | `3` | hours between update runs |
| `FRONTEND_URLS` | `http://localhost:3000,http://127.0.0.1:3000` | comma-separated CORS origins |

All update limits (requests per run, quota reserve, response size, database size, free disk) are listed in
`backend/docs/operations/configuration.md`.

Regions and request limits live in `backend/config.py`.

## Testing

```bash
cd backend
python -m pytest                                   # 44 tests, no key, no network, no real database

cd data_pipeline
python -m unittest discover -s tests -v            # pipeline tests
```

## Documentation

The backend has a full MkDocs site (`backend/docs/`):

```bash
cd backend
pip install -r requirements-docs.txt
mkdocs serve -a 127.0.0.1:8001
```

Method write-ups live next to the pipeline: `GRID_METHOD.md`, `CALIBRATION_METHOD.md` and `LIVE_STATUS.md` in `backend/data_pipeline/`.

## Deployment

Target: Ubuntu 24.04, 2 GB RAM, 20+ GB disk. `backend/deploy/` has a systemd unit (one uvicorn worker behind nginx; it also runs the NASA updates), an nginx config, and an optional cron job for updates. Copy `data/firesync.sqlite3` to the server instead of importing the 50 GB CSV there. Step-by-step instructions: `backend/docs/operations/deployment.md`.

## Limitations

- Counts are **thermal detections on a 0.1° grid**, not fires and not burned area; there is no mask for industrial heat sources.
- The harmonization factor is experimental: it is fitted per region on the first two thirds of the paired days (MODIS + NOAA-20, 2018 onwards) and checked on the last third. It fills MODIS gaps only when it beats both benchmarks on the held-out days. It is not a NASA standard.
- The archive export contains almost no offshore detections (NASA `type` 3); data from the API includes them (about 0.3 % of MODIS detections).
- VIIRS S-NPP and NOAA-21 are not stored: the VIIRS series is NOAA-20 only.
- Regions are rectangles, not administrative borders, and cannot cross the antimeridian.
- The website's yearly total sums the months it receives, so the current, incomplete year looks low.

## Next milestones

- Connect on-demand area queries and a bounded cache.
- Validate the harmonization across more regions and seasons.

## Designed for

Researchers, regional analysts and land managers.

## Data and attribution

- Fire detections: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) (MODIS Terra/Aqua, VIIRS NOAA-20).
- Basemap imagery: Esri, Maxar, Earthstar Geographics.
- Athens consistency check: contains modified Copernicus Sentinel data (2024), processed by ESA.
- Built for the NASA Space Apps Challenge 2026.

## AI assistance

AI assistance supported code, analysis and presentation drafting. Methods and limitations are documented in the repository.
