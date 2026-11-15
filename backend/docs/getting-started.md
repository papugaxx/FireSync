# Getting started

This page takes you from a fresh checkout to a running API and a built documentation site.

## Requirements

- **Python 3.11 or newer.** The data pipeline package declares `requires-python = ">=3.11"`.
- The FireSync database `data/firesync.sqlite3` (about 3 GB, **not in git**). Either import it from the archive
  CSV (below) or copy it from a teammate.
- A NASA FIRMS `MAP_KEY` in `data_pipeline/.env` is needed **only** for the automatic updates, not to run the API.

## Install

=== "Windows (PowerShell)"

    ```powershell
    cd FireSync\backend

    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    pip install -e .\data_pipeline
    ```

=== "macOS / Linux"

    ```bash
    cd FireSync/backend

    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    pip install -e ./data_pipeline
    ```

`pip install -e ./data_pipeline` installs the pipeline package (`fires_data`) in editable mode and also
registers a `fires-data` command. `config.py` additionally adds `data_pipeline/` to `sys.path`, so the
API still starts if you skip this step, but the editable install is the supported setup.

!!! note "Always use `python -m`"
    Start tools as `python -m uvicorn ...` and `python -m pytest`. This guarantees that the interpreter
    from the active virtual environment is used rather than a globally installed `uvicorn`.

## Everything at once

From the repository root (one level above `backend/`):

```bash
python3 run.py            # Windows: py run.py
```

It creates `backend/venv` and installs the packages if needed, runs `npm ci` for the website if needed, checks that
ports 8000 and 3000 are free, starts the API and the website together and stops both with Ctrl+C. Open
<http://127.0.0.1:3000/explore>. `python3 run.py --prod` runs the production build; `--no-update` turns the
background NASA downloads off; `--api-port` / `--web-port` choose other ports.

The sections below do the same by hand.

## Import the archive (once)

Put the archive export at `data/raw/NASA_FIRMS_2000_2025.csv` and run:

```bash
python importer.py
```

It takes about ten minutes and can be stopped with Ctrl+C and continued later. Details are in
[Archive import and NASA updates](pipeline/archive-and-updates.md).

## Run the API

```bash
python -m uvicorn main:app --reload
```

| URL | What it is |
|---|---|
| <http://localhost:8000/docs> | Interactive Swagger UI. Every endpoint has a **Try it out** button. |
| <http://localhost:8000/health> | Returns `{"status": "ok"}` when the server is up. |
| <http://localhost:8000/status> | What is stored and what the automatic NASA update is doing. |

About a minute after start the API begins downloading the days after the archive from NASA, in the background.
The site keeps working meanwhile; new days appear as they arrive.

## Show the data in the website

```text
# fire-calendar/.env.local
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Then `npm run dev` in `fire-calendar/` and open <http://localhost:3000/explore>. See [Frontend](development/frontend.md).

## Try a request

```bash
curl "http://localhost:8000/calendar?date_from=2024-08-01&date_to=2024-08-31&region=ukraine"
```

See the [endpoint reference](api/endpoints.md) for every endpoint and parameter.

## Run the tests

```bash
python -m pytest
```

The tests build their own temporary database, so they do not need the real one. Details are in
[Testing](development/testing.md).

## Build these docs

```bash
pip install -r requirements-docs.txt
mkdocs serve          # live preview at http://127.0.0.1:8000
mkdocs build --strict # static site into site/, fails on broken links and unresolved references
```

!!! tip "Port clash"
    `mkdocs serve` also defaults to port 8000. If the API is running, use `mkdocs serve -a 127.0.0.1:8001`.

See [Writing documentation](development/documentation.md) for how the site is organized.
