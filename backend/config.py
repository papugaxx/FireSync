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

from fires_data import load_settings  # noqa: E402  (import after the path setup)

# ---------- Databases ----------

# The partner's database (fire points from NASA). We take the path THE SAME WAY as its loader does:
#   1) the FIRMS_DB_PATH environment variable,
#   2) otherwise the data_pipeline/.env file,
#   3) otherwise data_pipeline/var/fires.sqlite3.
# That way the API and the loader always look at the same file.
DB_PATH = load_settings().db_path

# Our fast calendar index (created and updated automatically, not committed to git)
INDEX_PATH = Path(os.environ.get("FIRESYNC_INDEX_PATH", BASE_DIR / "cache" / "grid_index.sqlite3"))

# How often the API checks whether new data has appeared (seconds). 0 — do not check.
AUTO_REFRESH_SECONDS = int(os.environ.get("FIRESYNC_AUTO_REFRESH", "60"))

# Default data scope of the partner: the whole world
SCOPE_ID = "world"

# ---------- Frontend ----------

# Website addresses allowed to call the API (CORS). On the server:
#   FRONTEND_URLS=https://firesync.example.com
FRONTEND_URLS = [u.strip() for u in os.environ.get("FRONTEND_URLS", "http://localhost:3000").split(",")
                 if u.strip()]

# ---------- Ready-made regions for the demo ----------
# bbox = [west, south, east, north] — longitude first, then latitude.
# scope — which of the partner's data scopes to search. If the partner loads
# history separately for a region (--scope-id ukraine), change "world" to "ukraine" here.
REGIONS = {
    "world":          {"name": "Весь мир",                  "bbox": None,                      "scope": "world"},
    "ukraine":        {"name": "Украина (прямоугольник)",   "bbox": [22.0, 44.0, 41.0, 53.0],  "scope": "world"},
    "central_africa": {"name": "Центральная Африка",        "bbox": [12.0, -18.0, 35.0, 0.0],  "scope": "world"},
    "amazon":         {"name": "Амазония",                  "bbox": [-70.0, -15.0, -45.0, 0.0], "scope": "world"},
    "siberia":        {"name": "Сибирь и Якутия",           "bbox": [90.0, 50.0, 140.0, 70.0], "scope": "world"},
    "australia":      {"name": "Австралия",                 "bbox": [112.0, -44.0, 154.0, -10.0], "scope": "world"},
    "california":     {"name": "Калифорния",                "bbox": [-124.5, 32.5, -114.0, 42.0], "scope": "world"},
}

# ---------- Limits (protect the server from overly heavy requests) ----------
MAX_CALENDAR_DAYS = 3660      # daily calendar: up to 10 years per request
MAX_REFERENCE_DAYS = 366      # the partner's reference calculation is slow: up to 1 year
MAX_POINT_DAYS = 7            # individual points for the map: up to a week
MAX_POINTS_PER_PAGE = 5000
MAX_EXPORT_DAYS = 31          # CSV: up to a month
MAX_EXPORT_ROWS = 200_000
MAX_MAP_CELLS = 20_000        # cells in the /cells response
