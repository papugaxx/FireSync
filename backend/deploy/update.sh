#!/usr/bin/env bash
# =====================================================================
# update.sh — UPDATING DATA ON THE SERVER
#   1) the partner's loader downloads fresh data from NASA into his database;
#   2) our fast calendar index recomputes only the days that changed.
# Runs on a schedule (cron). Two updates cannot run at once: flock.
# The NASA key must be in data_pipeline/.env (FIRMS_MAP_KEY=...).
# =====================================================================
set -uo pipefail

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$BACKEND/venv/bin/python}"

exec 9>"${LOCK_FILE:-/tmp/firesync-update.lock}"
if ! flock -n 9; then
  echo "$(date -u +%FT%TZ) обновление уже идёт — пропускаю"
  exit 0
fi

echo "$(date -u +%FT%TZ) 1/2 загрузка свежих данных из NASA"
cd "$BACKEND/data_pipeline"
"$PYTHON" -m fires_data sync --area world --recent-days 3 --include-today \
  --sources MODIS_NRT VIIRS_NOAA20_NRT \
  --max-requests "${MAX_REQUESTS:-30}" --min-free-gb "${MIN_FREE_GB:-5}"
code=$?   # 0 — done, 2 — paused (request limit, will continue next time), 1 — error

echo "$(date -u +%FT%TZ) 2/2 обновление индекса календаря"
cd "$BACKEND"
"$PYTHON" grid_index.py

[ "$code" -eq 1 ] && exit 1
exit 0
