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
- **Automatic updates**: new NASA days are downloaded in the background every 3 hours, and only the changed months are rebuilt.
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
│   ├── main.py              general HTTP endpoints, error handling, CORS; starts the NASA updater
│   ├── frontend_api.py      the /api/... endpoints the website calls
│   ├── store.py             the database: compressed day blocks + region tables
│   ├── reports.py           calendar, months, map cells, points (for a region or a custom rectangle)
│   ├── importer.py          archive CSV (2000–2025) → database, once
│   ├── updater.py           NASA FIRMS API → database, in the background
│   ├── analytics.py         color levels, harmonization, anomalies
│   ├── config.py            paths, regions, update settings, limits
│   ├── data/                firesync.sqlite3 + raw/NASA_FIRMS_2000_2025.csv (not in git)
│   ├── tests/               tests on a generated archive in the real format
│   ├── deploy/              setup_server.sh, systemd units (API and website), nginx config, optional cron, update script
│   ├── docs/ + mkdocs.yml   full documentation site
│   └── data_pipeline/       NASA FIRMS loader + SQLite storage (package `fires_data`):
│                            NASA client, CSV parsing, calibration
├── fire-calendar/           Next.js website (landing page + /explore calendar)
└── run.py                   starts the backend and the website together
```

`backend/_old/` holds earlier versions of some files and is local only. It contains the former `grid_index.py` and `db.py`, which read the teammate's database and are no longer needed.

The teammate's database `backend/data_pipeline/var/fires.sqlite3` (~3 GB) is no longer used by the API. It can be deleted unless it is needed for the pipeline's own commands.

## How it works

```text
data/raw/NASA_FIRMS_2000_2025.csv (50 GB) ──(importer.py, once)──┐
                                                                  ▼
NASA FIRMS API ──(updater.py, every 3 h in the background)──► data/firesync.sqlite3 (~3 GB)
                                                                  │
                         fire-calendar ──► /api/... (frontend_api.py) ─┤  reports.py
                         other clients ──► /calendar, /cells, ... (main.py) ┘
```

### Key numbers

| | |
|---|---|
| Archive `NASA_FIRMS_2000_2025.csv` | 50 GB, 548 M rows |
| In the database | **267 M detections**: MODIS 111.4 M (2000-11-01 → 2025-12-31), NOAA-20 155.9 M (2018-04-01 → 2025-12-31) |
| Database size | **≈ 3 GB** (about 11 bytes per detection) |
| Archive import | ≈ 10 minutes, can be interrupted and resumed |
| New NASA data | downloaded automatically in the background every 3 hours |
| Tests | 44, with no key, no network and no real database |

All detections of one UTC day and sensor are stored as one compressed block, and per-region daily and monthly totals are precomputed, so the calendar answers in milliseconds.

### 1. The archive: `importer.py` (once)

- Reads the MODIS (Terra/Aqua) and VIIRS NOAA-20 rows. **VIIRS S-NPP (281 M rows) is skipped**: the VIIRS series in this project is NOAA-20 only, otherwise VIIRS would be counted twice.
- Compressing one block per day and sensor turns 50 GB of CSV into 3 GB, and a day can be read in milliseconds. Values are stored **exactly** (coordinates to 5 decimals, FRP and brightness to 2 decimals, as in NASA's data).
- If a day has both SP and NRT, only SP is kept (they are never added together).
- Ctrl+C is safe: progress is saved together with the data, and the next run continues from the same place. `python importer.py --max-minutes 10` stops itself after about 10 minutes.
- Checked against the real file: for 2024-08-15 the CSV has 106,758 NOAA-20 rows and 21,936 MODIS rows, and the database holds exactly as many.

### 2. New data: `updater.py` (automatic, in the background)

One minute after the API starts, and then every 3 hours, it:

1. asks NASA which dates are available (SP is final, NRT is near-real-time);
2. downloads **only what is missing** after the end of the archive. One request is one day of one satellite for the whole world: first the most recent week (so fresh fires show up immediately), then the rest in order;
3. recomputes the region tables for the changed months, so the website sees the new days right away.

| Situation | What it does |
|---|---|
| The day is not in the database | downloads SP if NASA has released it, otherwise NRT |
| The day is stored as NRT and NASA has released SP | downloads it again and replaces it with SP |
| NRT for the last 2 days | downloads it again (NASA keeps appending new overpasses) |
| The day is stored as SP (the whole archive) | **never downloads it again** |
| The whole world comes back empty for a day | does not store it: that is a satellite outage, not "no fires" |
| Request limit / NASA quota / disk / database size | stops with a clear reason; the next run continues |

The key is read from `data_pipeline/.env` (`FIRMS_MAP_KEY`) and **never leaves it**: it is not written to logs, the database or API responses. Catching up the period after the archive (from 2026-01-01 to today) takes about 640 requests, so it needs several runs in a row (with 10 minutes between them).

### Key rules

- **Grid**: fixed WGS84 0.1° grid, origin (−180°, −90°), 3600 × 1800 cells, UTC days.
- **MODIS** = Terra + Aqua (occupied cells merged). **VIIRS** = NOAA-20 only.
- **SP over NRT**: one product per day and sensor — final (SP) data when NASA has it, otherwise near-real-time; NRT is replaced by SP later, never added to it.
- **Missing ≠ zero**: `null` / `"status": "missing"` means no data for that day; `0` means data exists and there were no fires. An incomplete month is `null` (the `*_partial` fields show what is available).
- **Regions are whole cells**: rectangles are expanded outward to grid lines, so adjacent regions never double count.
- **Self-updating**: the API downloads new NASA days in the background and rebuilds only the changed months.
- **Verified**: the tests load the same rows with the pipeline's own code and compare its `grid_calendar()` with ours day by day; the import was checked against the raw CSV.

### Units and rules

- An **active cell** is a 0.1° cell (~10 km) where at least one hotspot was detected during a UTC day. It is not a number of fires and not a burned area. A monthly sum uses *cell-days* (the sum over days). A degree grid changes cell area with latitude, so it is not equal-area.
- **Area** is the area of the distinct occupied cells, taking latitude into account (cells are smaller near the poles). It is not burned area.
- **Mean FRP** is computed over detections that have an FRP value; a missing FRP is not counted as zero.
- **Harmonization**: on the first 2/3 of the days shared by MODIS and NOAA-20, a factor `k` is fitted (MODIS ≈ k × VIIRS) and then checked on the last third. MODIS gaps are filled with `k × VIIRS` **only if** `k` beat both benchmarks on the held-out days.

## Getting started

Everything at once (backend + website), from the repository root:

```bash
python3 run.py            # Windows: py run.py
```

`run.py` creates `backend/venv` and installs the packages if needed, runs `npm ci` for the website if needed,
checks that ports 8000 and 3000 are free, starts the API and the website together and stops both with Ctrl+C.
Open <http://127.0.0.1:3000/explore> (API docs: <http://127.0.0.1:8000/docs>).

| Command | What it does |
|---|---|
| `python3 run.py` | development mode (code changes are picked up immediately) |
| `python3 run.py --prod` | the production build of the website, as on the server |
| `python3 run.py --no-update` | turns the background NASA downloads off |
| `python3 run.py --setup` | only installs what is needed, then exits |
| `python3 run.py --api-port 8001 --web-port 3001` | other ports, if these are taken |

### Requirements

- Python **3.11+**
- Node.js (for the website)
- The database `backend/data/firesync.sqlite3` (~3 GB, **not in git**): copy it from a teammate, or import it from the archive CSV (`python importer.py`, about 10 minutes). Copying the ready-made database is faster than importing the 50 GB CSV again.
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

Open <http://localhost:8000/docs> for interactive Swagger, with every request described and a "Try it out" button. About a minute after start the API begins downloading the days after the archive from NASA in the background (`/api/updates/` shows the progress).

> Always start tools as `python -m uvicorn` / `python -m pytest` so the virtualenv's interpreter is used.

### Frontend

`python3 run.py` starts it together with the API. To run only the website:

```bash
cd fire-calendar
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
npm ci
npm run dev
```

- <http://localhost:3000>: landing page
- <http://localhost:3000/explore>: the fire calendar (real data from the API)

Without `NEXT_PUBLIC_API_URL` the site serves the demo data from `lib/mock.ts`.

#### Connecting the backend

The backend is FastAPI (`backend/`). The `/api/...` endpoints are defined in `backend/frontend_api.py`, and the response formats are described in `fire-calendar/types/api.ts`. The API address is set by `NEXT_PUBLIC_API_URL`. If the variable is empty, `lib/api.ts` returns the demo data from `lib/mock.ts`.

On a server the address is baked in at build time:

```bash
NEXT_PUBLIC_API_URL=https://your-domain npm run build
```

(see `backend/deploy/setup_server.sh`, which does this for you).

#### Frontend structure

```text
fire-calendar/
├── app/
│   ├── page.tsx              landing page (sections: hero, problem, how, features, team, cta)
│   └── explore/page.tsx      the calendar page
├── components/
│   ├── ui/index.tsx          basic elements: Section, Card, Button, Select, Stat, Placeholder
│   ├── layout/               Header, Footer
│   └── explore/              Explorer (the page logic), YearCalendar, DayStrip,
│                             MonthlyChart, FireMap, legends
├── lib/
│   ├── api.ts                API requests / mocks, CSV export
│   ├── useApi.ts             data-loading hook
│   ├── mock.ts               test data
│   └── colors.ts             color scales for the data (calendar, map)
└── types/api.ts              API response types
```

#### Customizing the design

There are currently no styles, only the layout and placeholder frames.

1. Colors and fonts: `app/globals.css`, in the `@theme` block.
2. Buttons, cards and fields: `components/ui/index.tsx`, which every page uses.
3. Header and footer: `components/layout/`.
4. Data colors (heat scale, MODIS/VIIRS): `lib/colors.ts`.
5. Places marked `TODO` in the code are waiting for content from the design (logo, hero image, team).

### NASA data

The archive (2000–2025) is imported once with `python importer.py`. Everything newer is downloaded by the API
itself in the background (`updater.py`), using `FIRMS_MAP_KEY` from `backend/data_pipeline/.env`:

```bash
cd backend
python updater.py --plan      # what would be downloaded
python updater.py             # one update now
python updater.py --status    # what is stored, what the last update did
```

The same information is available over HTTP: `GET /api/updates/` and `GET /status`.

Never commit `.env` or paste the key anywhere. Details: `backend/docs/pipeline/archive-and-updates.md`.

## API

All endpoints are `GET`.

### For the website (`frontend_api.py`)

The website uses these endpoints (`region`, `year`, `month`), in exactly the shapes of `fire-calendar/types/api.ts`:

| Endpoint | Returns |
|---|---|
| `/api/meta/` | regions (bbox in the frontend's order `[south, west, north, east]`) and the years with data |
| `/api/calendar/?region=` | a "year × month" calendar: cell-days on the MODIS scale, the median per month, the harmonization factor and R² |
| `/api/month/?region=&year=&month=` | the days of a month: active MODIS and NOAA-20 cells + the harmonized value |
| `/api/monthly/?region=&year=` | 12 months: MODIS, VIIRS on the MODIS scale, area of occupied cells, mean and maximum FRP |
| `/api/hotspots/?region=&year=&month=` | map points: one active 0.1° cell per day, which sensor saw it (MODIS / VIIRS / BOTH), FRP |
| `/api/export/?region=&year=&month=` | CSV with the real individual detections |
| `/api/updates/` | what is in the database and what the automatic update is doing |

The regions the frontend uses (`world`, `ukraine`, `argentina`, `california`, `amazonas`) exist in `config.REGIONS` with the same rectangles, so the calendar counts exactly what the map draws.

### General (`main.py`)

| Endpoint | Returns |
|---|---|
| `/health` | liveness check |
| `/status` | what is stored (and for which dates), archive import, NASA update state |
| `/regions` | ready-made regions (world, ukraine, argentina, california, amazonas, central_africa, siberia, australia) |
| `/calendar` | **per day**: daily active cells for MODIS and VIIRS, levels 0–4, shared cells |
| `/calendar/monthly` | **per month**: monthly aggregation with completeness, area and FRP |
| `/cells` | GeoJSON map layer of active cells (up to 92 days) |
| `/points` | individual detections, paged (max 7 days) |
| `/harmonization` | merged MODIS/VIIRS series with train/holdout validation |
| `/anomaly` | a month vs. the median of **other** years (needs ≥ 3 complete other years) |
| `/export.csv` | detections as CSV (max 31 days, 1 000 000 rows) |

**Area**: `region=ukraine`, or `west,south,east,north` (longitude first), or nothing for the whole world. A custom rectangle is computed directly from the detections, so its period can be up to 366 days.

**Period**: `date_from` and `date_to` in `YYYY-MM-DD` (UTC).

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

Target: Ubuntu 24.04, 2 GB RAM, 20+ GB disk, and a domain pointing at the server. One domain serves everything: `/` is the website, `/api/...` the API, `/docs` the API documentation.

```bash
# 1. Code and NASA key (on the server)
sudo git clone <repository> /srv/FireSync
sudo mkdir -p /srv/FireSync/backend/data
echo "FIRMS_MAP_KEY=your_key" | sudo tee /srv/FireSync/backend/data_pipeline/.env

# 2. The database (3 GB): copy it from your machine instead of re-importing the 50 GB CSV
#    (run on your machine)
scp backend/data/firesync.sqlite3 LOGIN@SERVER:/tmp/
#    (run on the server)
sudo mv /tmp/firesync.sqlite3 /srv/FireSync/backend/data/

# 3. Everything else in one command: packages, Node.js, website build, services, nginx, HTTPS
cd /srv/FireSync
sudo bash backend/deploy/setup_server.sh YOUR-DOMAIN --https you@example.com
```

`setup_server.sh` installs Node.js 22 and the Python packages, builds the website for the domain, installs two systemd services (`firesync-api`, `firesync-web`) and the nginx site, and gets an HTTPS certificate.

To update the code on the server, run `sudo -u firesync git pull`, then the same `setup_server.sh` command again (without `--https`).

Logs: `journalctl -u firesync-api -f` and `journalctl -u firesync-web -f`.

Details: `backend/docs/operations/deployment.md`.

## Limitations

- Counts are **thermal detections on a 0.1° grid**, not fires and not burned area; there is no mask for industrial heat sources.
- The harmonization factor is experimental: it is fitted per region on the first two thirds of the paired days (MODIS + NOAA-20, 2018 onwards) and checked on the last third. It fills MODIS gaps only when it beats both benchmarks on the held-out days. It is not a NASA standard.
- The archive export contains almost no offshore detections (NASA `type` 3); data from the API includes them (about 0.3 % of MODIS detections).
- VIIRS S-NPP and NOAA-21 are not stored: the VIIRS series is NOAA-20 only.
- Regions are rectangles, not administrative borders, and cannot cross the antimeridian.
- The website's yearly total sums the months it receives, so the current, incomplete year looks low.

## Designed for

Researchers, regional analysts and land managers.

## Data and attribution

- Fire detections: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) (MODIS Terra/Aqua, VIIRS NOAA-20).
- Basemap imagery: Esri, Maxar, Earthstar Geographics.
- Athens consistency check: contains modified Copernicus Sentinel data (2024), processed by ESA.
- Built for the NASA Space Apps Challenge 2026.

## SI assistance

SI was used for: learning/explaining new things, fixing code errors, spellchecking everything.
