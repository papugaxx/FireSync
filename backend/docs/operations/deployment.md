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

The database (~3 GB) is not in git. Copy it from the machine that holds it, and verify it with a checksum.

On the source machine:

```bash
scp path/to/backend/data_pipeline/var/fires.sqlite3 YOUR_LOGIN@SERVER:/tmp/
shasum -a 256 path/to/backend/data_pipeline/var/fires.sqlite3      # Linux: sha256sum
```

On the server:

```bash
sudo mv /tmp/fires.sqlite3 /srv/FireSync/backend/data_pipeline/var/
sudo chown firesync /srv/FireSync/backend/data_pipeline/var/fires.sqlite3
sha256sum /srv/FireSync/backend/data_pipeline/var/fires.sqlite3
```

The two checksums must match. On Windows, `Get-FileHash -Algorithm SHA256 <file>` gives the same value.

!!! warning "Copy a consistent snapshot"
    Do not copy the file while a loader is writing to it. Stop the loader, or produce a snapshot with SQLite's
    backup (`VACUUM INTO`) first.

## 4. NASA key and first index

Still as `firesync`:

```bash
cd /srv/FireSync/backend
echo "FIRMS_MAP_KEY=your_key" > data_pipeline/.env
python -m fires_data init
python grid_index.py                                     # builds the index, about a minute
chmod +x deploy/update.sh && crontab deploy/crontab.txt  # scheduled updates, see below
exit
```

## 5. The API as a service { #api-service }

Open `deploy/firesync-api.service` and replace `YOUR-FRONTEND-DOMAIN` in `FRONTEND_URLS` with the real
website address (including `https://`). Then, as a sudoer:

```bash
sudo cp /srv/FireSync/backend/deploy/firesync-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now firesync-api
```

What the unit does:

- Runs `uvicorn main:app` on `127.0.0.1:8000` with **2 workers** and `--proxy-headers`, as the `firesync` user.
- Restarts automatically (`Restart=always`) and starts at boot.
- Listens only on localhost; nginx is the public entry point.

!!! info "Two workers and the background refresh"
    Each worker runs its own auto-refresh thread. They cannot refresh at the same time because refreshes take a
    file lock (`cache/grid_index.lock`), so extra workers cost nothing but a lock attempt.

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

- `proxy_read_timeout 120s`: the slow `engine=reference` calculation can take around 30 seconds.
- `proxy_buffering off`: the CSV export is streamed, so it must not be buffered.

## 7. Verify

```bash
curl https://api.YOUR-DOMAIN/health
curl https://api.YOUR-DOMAIN/status
```

`/status` should show `"status": "ok"` and the loaded date ranges.

## Scheduled updates { #scheduled-updates }

`deploy/crontab.txt` runs `deploy/update.sh` every three hours (at minute 17) and appends to
`cache/update.log`:

```text
17 */3 * * * /srv/FireSync/backend/deploy/update.sh >> /srv/FireSync/backend/cache/update.log 2>&1
```

Each run does two steps:

1. **Download.** `fires_data sync --area world --recent-days 3 --include-today --sources MODIS_NRT VIIRS_NOAA20_NRT`
   with a request budget (`MAX_REQUESTS`, default 30) and a disk reserve (`MIN_FREE_GB`, default 5).
2. **Index.** `python grid_index.py` recomputes only the days that changed, which takes seconds.

Safety features:

- `flock` on `LOCK_FILE` means an update that finds another one running logs a message and exits successfully.
- The script exits with an error **only** if the download step fails (code 1). A paused download (code 2: request
  budget reached) is normal and continues on the next run.
- The API's own auto-refresh also notices the new data within `FIRESYNC_AUTO_REFRESH` seconds, so the website
  updates without a restart.

The scheduled job downloads **only NRT** data for MODIS and VIIRS NOAA-20, for the last three days. Standard
processing (SP) data for older days has to be loaded manually with `sync`; see
[Command line](../pipeline/cli.md#loading-history).

## Day-to-day operations

| Task | Command |
|---|---|
| API logs | `journalctl -u firesync-api -f` |
| Update log | `tail -f /srv/FireSync/backend/cache/update.log` |
| Restart the API | `sudo systemctl restart firesync-api` |
| Service status | `sudo systemctl status firesync-api` |
| Check the cron entry | `sudo -u firesync crontab -l` |
| Rebuild the index from scratch | stop the API, delete `cache/grid_index.sqlite3`, run `python grid_index.py` |
| Data status | `cd data_pipeline && python -m fires_data status` |

## Deploying a code update

```bash
sudo -iu firesync
cd /srv/FireSync && git pull
cd backend && source venv/bin/activate
pip install -r requirements.txt && pip install -e ./data_pipeline
exit
sudo systemctl restart firesync-api
```

If `INDEX_VERSION` in `grid_index.py` changed, the index rebuilds itself on the next start (about a minute during
which data endpoints return `503`).
