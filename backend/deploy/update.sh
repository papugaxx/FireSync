#!/usr/bin/env bash
# =====================================================================
# update.sh — ОБНОВЛЕНИЕ ДАННЫХ НА СЕРВЕРЕ
#   1) загрузчик напарника скачивает свежие данные из NASA в его базу;
#   2) наш быстрый индекс календаря пересчитывает только изменившиеся дни.
# Запускается по расписанию (cron). Два обновления сразу не пойдут: flock.
# Ключ NASA должен лежать в data_pipeline/.env (FIRMS_MAP_KEY=...).
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
code=$?   # 0 — готово, 2 — пауза (лимит запросов, продолжит в следующий раз), 1 — ошибка

echo "$(date -u +%FT%TZ) 2/2 обновление индекса календаря"
cd "$BACKEND"
"$PYTHON" grid_index.py

[ "$code" -eq 1 ] && exit 1
exit 0
