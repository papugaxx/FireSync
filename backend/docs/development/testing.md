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
central Africa. VIIRS is generated to see roughly three times more cells than MODIS, as in reality. On top of that,
a few special days exercise edge cases:

| Constant | Date | Purpose |
|---|---|---|
| `SP_AND_NRT_DAY` | 2024-08-05 | Both SP and NRT exist with different points. SP must win. |
| `SNPP_DAY` | 2024-08-10 | S-NPP points, which must **not** be part of the VIIRS series. |
| `EDGE_DAY` | 2024-08-07 | Points exactly on grid lines and region borders. |
| `NRT_ONLY_DAY` | 2024-09-01 | Only NRT data exists. It still counts as loaded. |
| `EMPTY_DAY` | 2024-09-02 | MODIS loaded with zero detections; VIIRS not loaded. |

### Fixtures

| Fixture | Scope | What it provides |
|---|---|---|
| `partner_db` | session | Path to the generated pipeline database. |
| `app_env` | session | Sets `FIRMS_DB_PATH`, `FIRESYNC_INDEX_PATH` (temporary) and `FIRESYNC_AUTO_REFRESH=0`, **reloads** `config`, `grid_index`, `db`, `analytics` and `main`, then builds the index. Returns the modules in a dict. |
| `client` | session | A FastAPI `TestClient` wrapped around `main.app`. |

The modules are reloaded because `config` reads environment variables at import time.

### What is covered

The tests in `tests/test_api.py` are grouped by section:

| Group | Checks |
|---|---|
| Fast index = reference | The index gives **exactly** the same daily numbers, totals and coverage as the pipeline's `grid_calendar()`, for the whole world and inside a region. |
| Borders | A point on a region boundary is counted once, never in both neighbours. |
| Incremental refresh | A second refresh with no changes rebuilds nothing. |
| System | `/` redirect, `/health`, `/status` (and that the database path is not leaked), `X-Process-Time-Ms`, `/regions`. |
| Calendar | Region and custom boxes, snapping to the grid, missing versus empty days, SP over NRT, `engine=reference`, monthly completeness. |
| Map | `/cells` GeoJSON, automatic resolution, `/points` paging and GeoJSON. |
| Science | `/harmonization` (status, coefficient range, error reduction, gap filling with scaled VIIRS), `/anomaly` history rules and math. |
| Export | CSV content, headers, sensor filter, ordering. |
| Errors | A table of bad requests, each returning the right status and a JSON `{"error": ...}`. |
| HTTP behaviour | CORS for the frontend origin; gzip compression for large responses. |

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

If you need different source data, extend `build_partner_db` in `conftest.py` with the `save(...)` helper, which
writes one daily slice the same way the real loader does. Note that adding days changes counts that existing tests
assert (for example the number of loaded days in `/status`).

## Pipeline tests

Run from `data_pipeline/`:

```bash
python -m unittest discover -s tests -v
```

| File | Area |
|---|---|
| `test_storage_parser.py` | CSV validation, parsing, atomic replacement, repeated loads, corrections |
| `test_service.py` | Planning, resumable jobs, request budget, disk reserve |
| `test_store_bbox.py` | Bounding-box filtering and scope isolation |
| `test_analytics.py` | The 0.1° grid calendar |
| `test_calibration.py` | The scaling experiment and its train/test logic |
| `test_cli_config.py` | Command line and `.env` handling |

The pipeline tests cover repetition, corrections, atomicity, empty responses, SP over NRT and scope isolation.
The "Area" column is summarized from the file names and the pipeline README, so open the files for the exact
cases. Real access to NASA is verified separately with `availability` and a first real `sync`; it is not part of
the automated tests.
