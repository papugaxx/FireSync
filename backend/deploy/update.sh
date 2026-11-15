#!/usr/bin/env bash
# =====================================================================
# update.sh — ONE NASA UPDATE FROM CRON (optional)
# The API already downloads new NASA days by itself in the background
# (updater.py, every FIRESYNC_UPDATE_HOURS). Use this script only if you run
# the API with FIRESYNC_AUTO_UPDATE=0 and prefer cron.
# The NASA key must be in data_pipeline/.env (FIRMS_MAP_KEY=...).
# Two updates never run at once (updater.py takes a lock).
# =====================================================================
set -uo pipefail

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$BACKEND/venv/bin/python}"

echo "$(date -u +%FT%TZ) NASA FIRMS update"
cd "$BACKEND" || exit 1
exec "$PYTHON" updater.py
