# Testing

There are two independent test suites: one for the backend API and one for the data pipeline. Neither needs a
NASA key, a network connection or the real database.

## Backend (API) tests

Run from `backend/`:

```bash
python -m pytest
```

`pytest.ini` sets `testpaths = tests`, quiet output, disables pytest's cache directory and ignores
deprecation warnings.

### How the test database is built

`tests/conftest.py` builds a small **synthetic pipeline database in a temporary folder**. It does this with the
pipeline's own code (`parse_observations` and `Store.replace_batch`) fed with CSV in the format NASA sends, so the
test data goes through the same path as real data. The real database is never touched.

The synthetic data covers all of August 2024 with two clusters: one inside the Ukraine rectangle and one in
The tests generate a small archive CSV in exactly the format of `NASA_FIRMS_2000_2025.csv` — with the rows of each
year shuffled, like the real export — import it with `importer.py` into a temporary database and test the real
app on it. A few special days exercise edge cases:

| Constant | Date | Purpose |
|---|---|---|
| `SP_AND_NRT_DAY` | 2024-08-05 | Extra NRT rows for an SP day. Only SP is stored. |
| `SNPP_DAY` | 2024-08-10 | S-NPP rows, which must **not** be stored. |
| `EDGE_DAY` | 2024-08-07 | Points exactly on grid lines. |
| `QUIET_UKRAINE_DAY` | 2024-08-20 | Data worldwide but no fire in Ukraine: a measured zero, not a gap. |
| `MODIS_ONLY_DAY` | 2024-09-02 | MODIS stored, VIIRS missing. |
| `HISTORY_YEARS` | Augusts 2021–2023 | Enough complete years for medians and anomalies. |

### Fixtures

| Fixture | Scope | What it provides |
|---|---|---|
| `archive` | session | The generated CSV and the list of rows that must be stored. |
| `app_env` | session | Sets `FIRESYNC_DB_PATH` (temporary) and `FIRESYNC_AUTO_UPDATE=0`, **reloads** the modules, imports the CSV. |
| `client` | session | A FastAPI `TestClient` wrapped around `main.app`. |

### What is covered

| File | Checks |
|---|---|
| `test_store_import.py` | Every stored day has exactly its CSV rows; values round-trip exactly; NRT never added to SP; region tables equal a direct calculation; distinct-cell area; **the partner's `grid_calendar()` gives the same daily numbers**; stop-and-continue import gives the same database. |
| `test_frontend_api.py` | Every `/api/...` call of the website, missing vs zero, complete months, medians, hotspots and their limit, CSV, errors, CORS, no key in the update status. |
| `test_api.py` | `/health`, `/status`, `/regions`, `/calendar`, `/calendar/monthly`, `/cells`, `/points`, `/harmonization`, `/anomaly`, `/export.csv`, errors, gzip. |
| `test_updater.py` | NASA updates with a fake client: plan after the archive, SP vs NRT, NRT → SP replacement, empty world day is not a zero, limits and quota, a bad answer skips one day, no key / no secret in errors, one update at a time. |

### Adding a test

Use `client` for HTTP-level checks and `app_env` for calling modules directly:

```python
def test_regions_include_ukraine(client):
    ids = {r["id"] for r in client.get("/regions").json()}
    assert "ukraine" in ids


def test_level_zero_is_no_fires(app_env):
    analytics = app_env["analytics"]
    assert analytics.level(0, [1, 2, 3]) == 0
```

If you need different source data, extend `make_archive` in `conftest.py`. Note that adding rows changes counts
that existing tests assert.
