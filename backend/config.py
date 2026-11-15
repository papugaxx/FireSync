"""
config.py — SETTINGS

Only variables live here. Any of them can be overridden with an environment
variable without changing the code (this is how it is done on the server).
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# The partner's module (fires_data) lives next to us, in the data_pipeline folder.
# We add it to the list of places where Python looks for modules, so that
# `import fires_data` works however the app is launched — even if it was not installed via pip.
_PIPELINE_DIR = str(BASE_DIR / "data_pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

# ---------- Data ----------

DATA_DIR = BASE_DIR / "data"

# The FireSync database: the whole MODIS + VIIRS NOAA-20 archive and every NASA update.
# Created by importer.py, kept up to date by updater.py, read by the API.
STORE_PATH = Path(os.environ.get("FIRESYNC_DB_PATH", DATA_DIR / "firesync.sqlite3"))

# The NASA FIRMS archive export (2000–2025) that importer.py reads by default.
ARCHIVE_CSV = Path(os.environ.get("FIRESYNC_ARCHIVE_CSV", DATA_DIR / "raw" / "NASA_FIRMS_2000_2025.csv"))

# ---------- Automatic NASA updates (updater.py) ----------
# The API key is read from data_pipeline/.env (FIRMS_MAP_KEY), as before.

def _number(name, default, low, high, kind=float):
    """A setting from the environment; an invalid value falls back to the default."""
    try:
        value = kind(os.environ.get(name, default))
    except ValueError:
        return default
    return value if low <= value <= high else default


AUTO_UPDATE = os.environ.get("FIRESYNC_AUTO_UPDATE", "1") not in ("0", "false", "no")
UPDATE_EVERY_HOURS = _number("FIRESYNC_UPDATE_HOURS", 3, 0.25, 168)
# One NASA request = one day of one sensor for the whole world.
UPDATE_MAX_REQUESTS = _number("FIRESYNC_UPDATE_MAX_REQUESTS", 120, 1, 2000, int)
# The API is responsible for everything after the archive. Without an imported archive (or while its
# import is unfinished) nothing before this day is ever asked from NASA: 2000–2025 comes from the archive.
# It is a fixed first day, not a moving window, so no date is dropped when a new year begins.
def _date(name, default):
    from datetime import date
    try:
        return date.fromisoformat(os.environ.get(name, default))
    except ValueError:
        return date.fromisoformat(default)


UPDATE_START_DATE = _date("FIRESYNC_UPDATE_START_DATE", "2026-01-01")
# After a run that stopped early (NASA quota, network, request limit) the next one starts this soon.
UPDATE_RETRY_MINUTES = _number("FIRESYNC_UPDATE_RETRY_MINUTES", 10, 1, 1440)
UPDATE_REQUEST_INTERVAL = _number("FIRESYNC_UPDATE_INTERVAL_SECONDS", 1.0, 0, 60)
UPDATE_QUOTA_RESERVE = _number("FIRESYNC_QUOTA_RESERVE", 100, 0, 5000, int)
UPDATE_MAX_RESPONSE_MB = _number("FIRESYNC_MAX_RESPONSE_MB", 200, 1, 2048, int)
UPDATE_MAX_DB_GB = _number("FIRESYNC_MAX_DB_GB", 20, 0.1, 4096)
UPDATE_MIN_FREE_GB = _number("FIRESYNC_MIN_FREE_GB", 2, 0, 4096)
# Near-real-time days younger than this are downloaded again: NASA keeps adding passes to them.
UPDATE_REFRESH_RECENT_DAYS = _number("FIRESYNC_REFRESH_RECENT_DAYS", 2, 0, 31, int)

# ---------- Frontend ----------

# Addresses of the site that are allowed to call the API (CORS). On a server:
#   FRONTEND_URLS=https://firesync.example.com
FRONTEND_URLS = [u.strip() for u in os.environ.get(
    "FRONTEND_URLS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if u.strip()]

# ---------- Ready-made regions ----------
# bbox     = [west, south, east, north] — longitude first, then latitude. The rectangle the map zooms to
#            (with a border it is only the view; it does not decide what is counted).
# boundary = the real border the region is counted by (geodata/boundaries.geojson, see geo.py):
#            "country:<ISO 3166-1 alpha-3>" or "state:<ISO 3166-2>". Detections outside the border are
#            not part of the region, even inside the rectangle. None = the region IS the rectangle.
# clip     = True: the region is the border cut by the rectangle (a part of a country).
# A new border must be added to the file once: python tools/build_boundaries.py
# Any change here is picked up automatically: the region tables are rebuilt on the next start.
REGIONS = {
    "world":          {"name": "World",               "bbox": None},
    "ukraine":        {"name": "Ukraine",             "bbox": [22.1, 44.3, 40.2, 52.4],
                       "boundary": "country:UKR"},
    "argentina":      {"name": "Argentina",           "bbox": [-73.6, -55.1, -53.6, -21.8],
                       "boundary": "country:ARG"},
    "california":     {"name": "California, USA",     "bbox": [-124.4, 32.5, -114.1, 42.0],
                       "boundary": "state:US-CA"},
    "amazonas":       {"name": "Amazonas, Brazil",    "bbox": [-73.8, -9.8, -56.1, 2.2],
                       "boundary": "state:BR-AM"},
    "central_africa": {"name": "Central Africa",      "bbox": [12.0, -18.0, 35.0, 0.0]},
    "siberia":        {"name": "Siberia and Yakutia", "bbox": [90.0, 50.0, 140.0, 70.0],
                       "boundary": "country:RUS", "clip": True},
    "australia":      {"name": "Australia",           "bbox": [112.0, -44.0, 154.0, -10.0],
                       "boundary": "country:AUS"},
}
BOUNDARIES_FILE = BASE_DIR / "geodata" / "boundaries.geojson"

# ---------- Limits (protect the server from overly heavy requests) ----------
MAX_CALENDAR_DAYS = 3660      # daily calendar of a ready-made region: up to 10 years per request
MAX_CUSTOM_AREA_DAYS = 366    # own west/south/east/north rectangle: computed from detections, up to 1 year
MAX_POINT_DAYS = 7            # individual points for the map: up to a week
MAX_POINTS_PER_PAGE = 5000
MAX_EXPORT_DAYS = 31          # CSV: up to a month
MAX_EXPORT_ROWS = 1_000_000   # CSV rows (streamed, so memory stays small)
MAX_MAP_CELLS = 20_000        # cells in the /cells response
MAX_MAP_DAYS = 92             # /cells reads every day's detections: up to a quarter
MAX_HOTSPOTS = 10_000         # cell-days in /api/hotspots/ (the map draws each one)
