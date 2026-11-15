# Deployment

This guide puts the whole of FireSync — the website and the API — on one Ubuntu 24.04 server under one domain:

```text
https://YOUR-DOMAIN/          → website (Next.js, port 3000, service firesync-web)
https://YOUR-DOMAIN/api/...   → API the website calls (FastAPI, port 8000, service firesync-api)
https://YOUR-DOMAIN/docs      → interactive API documentation
```

Both programs listen only on `127.0.0.1`; nginx is the public entry point. The API downloads new NASA days by
itself in the background. The ready-made files are in `backend/deploy/`, and `setup_server.sh` does everything below.

## What you need

| Resource | Minimum |
|---|---|
| Memory | 2 GB |
| Disk | 20 GB. The database is ~3 GB and grows by less than 0.1 GB per month |
| Domain | An A record pointing at the server |
| NASA key | A [FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/) for the automatic updates |

## 1. Code, database and key

```bash
sudo git clone <your repository URL> /srv/FireSync
sudo mkdir -p /srv/FireSync/backend/data
echo "FIRMS_MAP_KEY=your_key" | sudo tee /srv/FireSync/backend/data_pipeline/.env
```

## 2. Copy the database { #copy-the-database }

The database (~3 GB) is not in git. Copy it from a machine that has it — much faster than importing the 50 GB
CSV on the server — and compare the checksums.

On your computer:

```bash
scp path/to/backend/data/firesync.sqlite3 YOUR_LOGIN@SERVER:/tmp/
shasum -a 256 path/to/backend/data/firesync.sqlite3      # Linux: sha256sum
```

On the server:

```bash
sudo mv /tmp/firesync.sqlite3 /srv/FireSync/backend/data/
sha256sum /srv/FireSync/backend/data/firesync.sqlite3
```

!!! warning "Copy a consistent snapshot"
    Do not copy the file while the API is running on your computer (its updater may be writing). Stop it first,
    or make a snapshot with SQLite's backup (`VACUUM INTO`).

## 3. Install everything

```bash
cd /srv/FireSync
sudo bash backend/deploy/setup_server.sh YOUR-DOMAIN --https you@example.com
```

The script:

1. installs Python, nginx, git and Node.js 22 (Next.js 16 needs Node 20.9+);
2. creates the `firesync` user and gives it `/srv/FireSync`;
3. creates `backend/venv` and installs the Python packages;
4. builds the website with `NEXT_PUBLIC_API_URL=https://YOUR-DOMAIN` (the address is built into the site);
5. installs and starts `firesync-api` and `firesync-web` (systemd: restart on failure and after a reboot);
6. installs the nginx site for the domain and, with `--https`, a free Let's Encrypt certificate;
7. checks that both answer.

Without `--https` the site is built for `http://YOUR-DOMAIN`; run the script again with `--https` later.

## 4. Verify

```bash
curl https://YOUR-DOMAIN/health
curl https://YOUR-DOMAIN/api/updates/
```

Then open `https://YOUR-DOMAIN/explore`.

## Updating the code

```bash
cd /srv/FireSync && sudo -u firesync git pull
sudo bash backend/deploy/setup_server.sh YOUR-DOMAIN
```

The same script updates the packages, rebuilds the website and restarts both services. The database and the NASA
key are not touched.

## NASA updates on the server { #scheduled-updates }

The API service downloads new days in the background (`updater.py`): about a minute after start and then every
three hours. Its state is at `/api/updates/`. To use cron instead, set `FIRESYNC_AUTO_UPDATE=0` in
`/etc/systemd/system/firesync-api.service` and install `backend/deploy/crontab.txt`.
Details: [Archive import and NASA updates](../pipeline/archive-and-updates.md).

## Day-to-day operations

| Task | Command |
|---|---|
| API logs | `journalctl -u firesync-api -f` |
| Website logs | `journalctl -u firesync-web -f` |
| Restart | `sudo systemctl restart firesync-api firesync-web` |
| Status | `systemctl status firesync-api firesync-web` |
| Update state | `curl http://127.0.0.1:8000/api/updates/` |
| One NASA update now | `cd /srv/FireSync/backend && sudo -u firesync venv/bin/python updater.py` |

## Files in `backend/deploy/`

| File | Purpose |
|---|---|
| `setup_server.sh` | installs or updates everything (above) |
| `firesync-api.service` | systemd unit of the API (one uvicorn worker, which also runs the NASA updates) |
| `firesync-web.service` | systemd unit of the website (`next start`) |
| `nginx.conf` | one domain: `/api/`, `/docs` and the general endpoints → API, everything else → website |
| `update.sh`, `crontab.txt` | optional cron alternative to the background updates |
