#!/usr/bin/env bash
# =====================================================================
# setup_server.sh — install or update FireSync on an Ubuntu 24.04 server
#
#   sudo bash backend/deploy/setup_server.sh YOUR-DOMAIN            # first install and every update
#   sudo bash backend/deploy/setup_server.sh YOUR-DOMAIN --https you@example.com   # + free HTTPS
#
# Before the first run:
#   1. the repository is at /srv/FireSync         (git clone ... /srv/FireSync)
#   2. the database is copied to /srv/FireSync/backend/data/firesync.sqlite3
#      (scp from your Mac — about 3 GB, much faster than importing the 50 GB CSV here)
#   3. /srv/FireSync/backend/data_pipeline/.env contains FIRMS_MAP_KEY=... (for NASA updates)
#   4. the domain's DNS A record points to this server
#
# What it does: system packages (Python, nginx, Node.js 22), the "firesync" user,
# backend venv + packages, website build with NEXT_PUBLIC_API_URL=https://YOUR-DOMAIN,
# two systemd services (firesync-api, firesync-web), nginx for one domain, a final check.
# Safe to run again after `git pull`: it updates packages, rebuilds and restarts.
# =====================================================================
set -euo pipefail

DOMAIN="${1:?Usage: sudo bash backend/deploy/setup_server.sh YOUR-DOMAIN [--https EMAIL]}"
HTTPS_EMAIL=""
if [ "${2:-}" = "--https" ]; then HTTPS_EMAIL="${3:?--https needs an email address for the HTTPS certificate}"; fi
APP=/srv/FireSync
RUN_AS=firesync
SCHEME=$([ -n "$HTTPS_EMAIL" ] || [ -e "/etc/letsencrypt/live/$DOMAIN" ] && echo https || echo http)

say() { echo -e "\n==> $*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
[ -d "$APP/backend" ] && [ -d "$APP/fire-calendar" ] || { echo "Clone the repository to $APP first."; exit 1; }

say "1/7 System packages"
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip nginx git curl ca-certificates
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -q nodejs
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11+ is needed."; exit 1; }

say "2/7 User $RUN_AS owns $APP"
id "$RUN_AS" >/dev/null 2>&1 || adduser --system --group --home "$APP" --no-create-home "$RUN_AS"
mkdir -p "$APP/backend/data"
chown -R "$RUN_AS:$RUN_AS" "$APP"

say "3/7 Backend packages"
sudo -u "$RUN_AS" bash -c "cd '$APP/backend' && { [ -x venv/bin/python ] || python3 -m venv venv; } \
  && venv/bin/pip install -q --upgrade pip && venv/bin/pip install -q -r requirements.txt \
  && venv/bin/pip install -q -e ./data_pipeline"
if [ ! -f "$APP/backend/data/firesync.sqlite3" ]; then
  echo "WARNING: $APP/backend/data/firesync.sqlite3 is missing. Copy it from your Mac:"
  echo "  scp ~/Desktop/FireSync/backend/data/firesync.sqlite3 USER@SERVER:/tmp/ && sudo mv /tmp/firesync.sqlite3 $APP/backend/data/"
fi
grep -q '^FIRMS_MAP_KEY=.' "$APP/backend/data_pipeline/.env" 2>/dev/null \
  || echo "NOTE: no FIRMS_MAP_KEY in backend/data_pipeline/.env — new NASA days will not be downloaded."

say "4/7 Website build (API at $SCHEME://$DOMAIN)"
sudo -u "$RUN_AS" bash -c "cd '$APP/fire-calendar' && npm ci --no-audit --no-fund \
  && NEXT_PUBLIC_API_URL='$SCHEME://$DOMAIN' npm run build"

say "5/7 systemd services"
for unit in firesync-api firesync-web; do
  sed "s/YOUR-DOMAIN/$DOMAIN/g" "$APP/backend/deploy/$unit.service" > "/etc/systemd/system/$unit.service"
done
sed -i "s#ExecStart=/usr/bin/npm#ExecStart=$(command -v npm)#" /etc/systemd/system/firesync-web.service
systemctl daemon-reload
systemctl enable firesync-api firesync-web >/dev/null
systemctl restart firesync-api firesync-web

say "6/7 nginx"
if [ ! -e "/etc/letsencrypt/live/$DOMAIN" ]; then
  # first install: plain config; certbot adds HTTPS to it below
  sed "s/YOUR-DOMAIN/$DOMAIN/g" "$APP/backend/deploy/nginx.conf" > /etc/nginx/sites-available/firesync
fi
ln -sf /etc/nginx/sites-available/firesync /etc/nginx/sites-enabled/firesync
nginx -t
systemctl reload nginx
if [ -n "$HTTPS_EMAIL" ] && [ ! -e "/etc/letsencrypt/live/$DOMAIN" ]; then
  apt-get install -y -q certbot python3-certbot-nginx
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$HTTPS_EMAIL" --redirect
fi

say "7/7 Check"
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/health && echo "  API ok"
for _ in $(seq 1 30); do curl -fsS -o /dev/null http://127.0.0.1:3000 && break; sleep 1; done
curl -fsS -o /dev/null http://127.0.0.1:3000 && echo "  website ok"
echo
echo "FireSync: $SCHEME://$DOMAIN/explore      API docs: $SCHEME://$DOMAIN/docs"
echo "Logs: journalctl -u firesync-api -f   |   journalctl -u firesync-web -f"
echo "NASA updates: curl -s $SCHEME://$DOMAIN/api/updates/"
