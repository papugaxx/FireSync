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
├── backend/                 FastAPI app, fast index, deployment files, docs
│   ├── main.py              HTTP endpoints
│   ├── grid_index.py        fast calendar index (points → 0.1° cells per day)
│   ├── db.py                raw points, CSV export, reference calculation
│   ├── analytics.py         color levels, harmonization, anomalies
│   ├── config.py            paths, regions, limits
│   ├── tests/               API tests (synthetic temporary database)
│   ├── deploy/              systemd unit, nginx config, cron, update script
│   ├── docs/ + mkdocs.yml   full documentation site
│   └── data_pipeline/       NASA FIRMS loader + SQLite storage (package `fires_data`)
└── fire-calendar/           Next.js website (landing page + /explore calendar)
```

`backend/_old/` holds earlier versions of some files and is local only.

## How it works

```text
NASA FIRMS ──(fires_data)──► data_pipeline/var/fires.sqlite3     raw detections (GBs, read-only for the API)
                                      │
                                      ▼
                    grid_index.py: points → 0.1° cells per day
                                      │
                                      ▼
                       cache/grid_index.sqlite3                   small derived index (safe to delete)
                                      │
            browser ──► main.py (FastAPI) ──┘   + db.py for raw points and CSV
```

Key rules:

- **Grid**: fixed WGS84 0.1° grid, origin (−180°, −90°), 3600 × 1800 cells, UTC days.
- **MODIS** = Terra + Aqua (occupied cells merged). **VIIRS** = NOAA-20 only.
- **SP over NRT**: per day and sensor family, standard-processing data is preferred, near-real-time is the fallback.
- **Missing ≠ zero**: `null` / `"status": "missing"` means the day was not loaded.
- **Regions are whole cells**: rectangles are expanded outward to grid lines, so adjacent regions never double count.
- **Self-updating**: the API fingerprints the pipeline database and recomputes only changed days, with no restart.
- **Verified**: the fast index matches the pipeline's reference calculation on all 31 days of August 2024 for the world and Ukraine, to the unit. `engine=reference` lets you recompute any request the slow way.

A monthly sum uses *cell-days*. A degree grid changes cell area with latitude, so it is not equal-area.

## Getting started

### Requirements

- Python **3.11+**
- Node.js (for the website)
- The pipeline database `backend/data_pipeline/var/fires.sqlite3` (several GB, **not in git**). Copy it from whoever holds it, or build it with the pipeline.
- A free [NASA FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/), needed **only** to download new data.

### Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .\data_pipeline

python -m fires_data init            # prepare the database schema (keeps existing data)
python -m uvicorn main:app --reload
```

macOS / Linux:

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e ./data_pipeline
python -m fires_data init
python -m uvicorn main:app --reload
```

Open <http://localhost:8000/docs> for interactive Swagger. On first start the index is built in the background (about a minute); until then data endpoints return `503` with `Retry-After`. You can build it explicitly with `python grid_index.py`.

> Always start tools as `python -m uvicorn` / `python -m pytest` so the virtualenv's interpreter is used.

### Frontend

```bash
cd fire-calendar
npm install
npm run dev
```

- <http://localhost:3000>: landing page
- <http://localhost:3000/explore>: calendar prototype

Set `NEXT_PUBLIC_API_URL` in `.env.local` to point at the backend. While it is empty, the site serves mock data from `lib/mock.ts`.

### Downloading NASA data

```bash
cd backend/data_pipeline
cp .env.example .env                 # then set FIRMS_MAP_KEY
python -m fires_data doctor
python -m fires_data availability
python -m fires_data plan --area world --recent-days 1 --sources MODIS_NRT VIIRS_NOAA20_NRT
python -m fires_data sync --area world --recent-days 1 --sources MODIS_NRT VIIRS_NOAA20_NRT --max-requests 2
```

Never commit `.env` or paste the key anywhere. Downloads are resumable, atomic per day and validated as real CSV. See `backend/docs/pipeline/cli.md` for history loading and all options.

## API

All endpoints are `GET`. Area is `region=<id>` or `west,south,east,north` (longitude first); period is `date_from` / `date_to` in `YYYY-MM-DD` (UTC).

| Endpoint | Returns |
|---|---|
| `/health` | liveness check |
| `/status` | what is loaded, index state |
| `/regions` | ready-made regions (world, ukraine, central_africa, amazon, siberia, australia, california) |
| `/calendar` | daily active cells for MODIS and VIIRS, levels 0–4, shared cells |
| `/calendar/monthly` | monthly aggregation with completeness |
| `/cells` | GeoJSON map layer of active cells |
| `/points` | individual detections, paged (max 7 days) |
| `/harmonization` | merged MODIS/VIIRS series with train/holdout validation |
| `/anomaly` | a month vs. the median of other years (needs ≥ 3 complete other years) |
| `/export.csv` | detections as CSV (max 31 days, 200 000 rows) |

Example:

```bash
curl "http://localhost:8000/calendar?date_from=2024-08-01&date_to=2024-08-31&region=ukraine"
```

Errors always have the form `{"error": "..."}` with status 400, 422, 503 or 500. Full parameter and response details: `backend/docs/api/endpoints.md`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FIRMS_MAP_KEY` | none | NASA key, only for downloading |
| `FIRMS_DB_PATH` | `data_pipeline/var/fires.sqlite3` | pipeline database location |
| `FIRESYNC_INDEX_PATH` | `cache/grid_index.sqlite3` | fast index location |
| `FIRESYNC_AUTO_REFRESH` | `60` | seconds between checks for new data (`0` disables) |
| `FRONTEND_URLS` | `http://localhost:3000` | comma-separated CORS origins |

Regions and request limits live in `backend/config.py`.

## Testing

```bash
cd backend
python -m pytest                                   # API tests, no key or real DB needed

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

Target: Ubuntu 24.04, 2 GB RAM, 20+ GB disk. `backend/deploy/` has a systemd unit (2 uvicorn workers behind nginx), an nginx config, and a cron job (`update.sh`, every 3 hours) that downloads recent NRT data and refreshes only the changed days of the index. Step-by-step instructions: `backend/docs/operations/deployment.md`.

## Limitations

- Counts are **thermal detections on a 0.1° grid**, not fires and not burned area; there is no mask for industrial heat sources.
- The harmonization factor is experimental, fitted per request, and validated on one region and one month. It is not a NASA standard.
- Fully loaded data currently covers August 2024; `/anomaly` returns `insufficient_history` until more history is loaded.
- Regions are rectangles, not administrative borders, and cannot cross the antimeridian.
- The frontend currently calls `/api/...` routes (`lib/api.ts`) that differ from the FastAPI endpoints above and still falls back to mock data. Wiring it to the real API is open work.

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
