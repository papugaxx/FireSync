# Deployment

This guide installs FireSync on an Ubuntu 24.04 server: the API as a `systemd` service behind `nginx` with HTTPS,
plus a cron job that refreshes the data. The ready-made files are in `backend/deploy/`.

## What you need

| Resource | Minimum |
|---|---|
| Memory | 2 GB |
| Disk | 20 GB. The database is ~3 GB and grows by roughly 2 GB per month when updating the whole world |
| Python | 3.11 or newer |
| Domain | An `api.` name pointing at the server, for HTTPS |
| NASA key | A [FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/) for scheduled updates |

## 1. Packages and user

```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx git
sudo adduser --disabled-password --gecos "" firesync
sudo mkdir -p /srv/FireSync && sudo chown firesync /srv/FireSync
```

## 2. Code

Run as the `firesync` user:

```bash
sudo -iu firesync
git clone <your repository URL> /srv/FireSync
cd /srv/FireSync/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && pip install -e ./data_pipeline
mkdir -p cache data_pipeline/var
```

The virtual environment must live at `backend/venv`: both `update.sh` and the systemd unit refer to it.

## 3. Copy the database { #copy-the-database }

The database (~3 GB) is not in git. Copy it from the machine that holds it (much faster than importing the
50 GB CSV again), and verify it with a checksum.

On the source machine:

```bash
scp path/to/backend/data/firesync.sqlite3 YOUR_LOGIN@SERVER:/tmp/
shasum -a 256 path/to/backend/data/firesync.sqlite3      # Linux: sha256sum
```

On the server:

```bash
sudo mkdir -p /srv/FireSync/backend/data
sudo mv /tmp/firesync.sqlite3 /srv/FireSync/backend/data/
sudo chown -R firesync /srv/FireSync/backend/data
sha256sum /srv/FireSync/backend/data/firesync.sqlite3
```

The two checksums must match. On Windows, `Get-FileHash -Algorithm SHA256 <file>` gives the same value.

!!! warning "Copy a consistent snapshot"
    Do not copy the file while the API is running (its updater may be writing). Stop the API, or produce a
    snapshot with SQLite's backup (`VACUUM INTO`) first.

## 4. NASA key

Still as `firesync`:

```bash
cd /srv/FireSync/backend
echo "FIRMS_MAP_KEY=your_key" > data_pipeline/.env
exit
```

The API downloads new NASA days by itself (see [Scheduled updates](#scheduled-updates)).

## 5. The API as a service { #api-service }

Open `deploy/firesync-api.service` and replace `YOUR-FRONTEND-DOMAIN` in `FRONTEND_URLS` with the real
website address (including `https://`). Then, as a sudoer:

```bash
sudo cp /srv/FireSync/backend/deploy/firesync-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now firesync-api
```

What the unit does:

- Runs `uvicorn main:app` on `127.0.0.1:8000` with **1 worker** and `--proxy-headers`, as the `firesync` user.
- Restarts automatically (`Restart=always`) and starts at boot.
- Listens only on localhost; nginx is the public entry point.

!!! info "Workers and the background update"
    Every worker starts its own updater thread. Two updates never run at once — they take a file lock
    (`data/firesync.sqlite3.update.lock`) — so more workers are safe, but one is enough: answers are cached.

## 6. nginx and HTTPS

Replace `api.YOUR-DOMAIN` in `deploy/nginx.conf`, then:

```bash
sudo cp /srv/FireSync/backend/deploy/nginx.conf /etc/nginx/sites-available/firesync
sudo ln -s /etc/nginx/sites-available/firesync /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.YOUR-DOMAIN
```

The nginx config forwards to the API with the original `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`
headers. Two settings matter:

- `proxy_read_timeout 120s`: a large CSV export of a whole month can take a while.
- `proxy_buffering off`: the CSV export is streamed, so it must not be buffered.

## 7. Verify

```bash
curl https://api.YOUR-DOMAIN/health
curl https://api.YOUR-DOMAIN/status
```

`/status` should show `"status": "ok"` and the loaded date ranges.

## Scheduled updates { #scheduled-updates }

The API itself downloads new NASA days in the background (`updater.py`): about a minute after start and then every
`FIRESYNC_UPDATE_HOURS` hours (3). It stores SP where NASA has it and NRT otherwise, replaces NRT with SP later,
and re-downloads only the last two NRT days. Details: [Archive import and NASA updates](../pipeline/archive-and-updates.md).

If you prefer cron, set `FIRESYNC_AUTO_UPDATE=0` in the service file and install `deploy/crontab.txt`, which runs
`deploy/update.sh` (`python updater.py`) every three hours.

## Day-to-day operations

| Task | Command |
|---|---|
| API logs | `journalctl -u firesync-api -f` |
| Update state | `curl http://127.0.0.1:8000/api/updates/` or `python updater.py --status` |
| Restart the API | `sudo systemctl restart firesync-api` |
| Service status | `sudo systemctl status firesync-api` |
| One update now | `cd /srv/FireSync/backend && venv/bin/python updater.py` |

## Deploying a code update

```bash
sudo -iu firesync
cd /srv/FireSync && git pull
cd backend && source venv/bin/activate
pip install -r requirements.txt && pip install -e ./data_pipeline
exit
sudo systemctl restart firesync-api
```

If `config.REGIONS` changed, the region tables are rebuilt in the background after the restart (a few minutes);
until then the previous numbers are served.
