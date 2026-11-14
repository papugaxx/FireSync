# Getting started

This page takes you from a fresh checkout to a running API and a built documentation site.

## Requirements

- **Python 3.11 or newer.** The data pipeline package declares `requires-python = ">=3.11"`.
- The pipeline database `data_pipeline/var/fires.sqlite3`. It is several gigabytes and is **not in git**
  (`*.sqlite3` is ignored), so it has to be copied from whoever holds it. See
  [Deployment](operations/deployment.md#copy-the-database) for how to verify a copy with a checksum.
- A NASA FIRMS `MAP_KEY` is needed **only** to download new data, not to run the API on an existing database.

## Install

=== "Windows (PowerShell)"

    ```powershell
    cd C:\Users\User\PycharmProjects\FireSync\backend

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

## Prepare the database

```bash
python -m fires_data init
```

This creates the schema if it is missing, enables WAL mode and registers the `world` scope. It never deletes
existing observations, so it is safe to run on a database that already has data.

Run it from `data_pipeline/`, or pass `--db` with an absolute path. Which database file is used is decided by
[the pipeline settings](operations/configuration.md#where-the-database-is-found).

## Run the API

```bash
python -m uvicorn main:app --reload
```

| URL | What it is |
|---|---|
| <http://localhost:8000/docs> | Interactive Swagger UI. Every endpoint has a **Try it out** button. |
| <http://localhost:8000/health> | Returns `{"status": "ok"}` when the server is up. |
| <http://localhost:8000/status> | What data is loaded and whether the index is ready. |

On the **first start** the fast calendar index does not exist yet. It is built in the background, which takes
about a minute for the full database. Until then, data endpoints answer `503` with a `Retry-After: 30` header
and `/status` reports `"status": "building_index"`. You can also build it explicitly:

```bash
python grid_index.py
```

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
