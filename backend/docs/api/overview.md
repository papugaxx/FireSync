# HTTP API overview

This page describes the conventions shared by all endpoints. Each endpoint is documented on the
[Endpoints](endpoints.md) page. The live, always-current schema is served by the running API at
`/docs` (Swagger UI) and `/openapi.json`.

## Base URL

| Environment | Base URL |
|---|---|
| Local development | `http://localhost:8000` |
| Production | `https://YOUR-DOMAIN` — the API is under `/api/`, `/docs` and the general paths (see [Deployment](../operations/deployment.md)) |

All endpoints are `GET`. The API is read-only.

## Common parameters

Most data endpoints accept the same two groups of parameters.

### Period

| Parameter | Type | Description |
|---|---|---|
| `date_from` | date `YYYY-MM-DD` | First day, inclusive (UTC). Required. |
| `date_to` | date `YYYY-MM-DD` | Last day, inclusive (UTC). Required. Must not be before `date_from`. |

All dates and times are **UTC**. Each endpoint caps the period length; see [Limits](#limits).

### Area

Choose **one** of three ways to select an area:

| Option | Parameters | Result |
|---|---|---|
| Ready-made region | `region=ukraine` | A named region from [`/regions`](endpoints.md#get-regions), counted by its real country/state border where one is configured, otherwise by its rectangle |
| Custom rectangle | `west`, `south`, `east`, `north` | Your own box. **All four** are required |
| Nothing | (none) | The whole world |

Rules:

- `region` cannot be combined with `west`/`south`/`east`/`north`.
- Order is **longitude first, then latitude**: `west` and `east` are longitudes (-180 to 180); `south` and
  `north` are latitudes (-90 to 90). Be careful: some frontend types use `[south, west, north, east]`.
- `west < east` and `south < north`. Crossing the antimeridian in one box is not supported.
- A custom rectangle is computed from the stored detections, so its period is limited to 366 days.
- The rectangle is expanded outward to whole 0.1° cells. Responses return both `requested_bbox` and the
  `bbox` that was actually computed. See [Grid and calendar](../concepts/grid-and-calendar.md#regions-are-whole-cells).
- For a ready-made region with a real border, detections outside the border are not counted, even inside the
  region's rectangle (its `bbox` in `/regions` is only the view the map zooms to). In the `area` object of a response,
  `bbox` is then the part of the grid the border touches. See [Region borders](endpoints.md#region-borders).

Every response that takes an area includes an `area` object. `requested_bbox` is `null` for a ready-made region and
holds your own rectangle otherwise:

```json
{
  "region": "ukraine",
  "requested_bbox": null,
  "bbox": [22.1, 44.3, 40.2, 52.4]
}
```

## Errors

Errors always use one JSON shape:

```json
{"error": "human-readable explanation"}
```

| Status | Meaning | Example cause |
|---|---|---|
| `400` | The request is well-formed but violates a rule | `date_to` before `date_from`; unknown `region`; period too long; only some of the four boundaries |
| `422` | A parameter is malformed or out of range | Not a date; `west=500` |
| `503` | The service cannot answer yet | Database not created yet (also sends `Retry-After: 60`); database file not available |
| `500` | Unexpected pipeline failure | |

`422` responses add a `details` array of `{"param", "message"}` objects so a form can highlight the faulty field.

!!! note "Language of messages"
    The `error` text is written in English and may be reworded. Rely on the HTTP status for program logic and show
    `error` to the user, rather than matching on its text.

## Response conventions

- **`null` means "not loaded", not "no fires".** A value of `0` means the day was loaded and nothing was
  detected. See [Missing versus zero](../concepts/grid-and-calendar.md#missing-versus-zero).
- **Unit.** The main number is the *active cell* (a 0.1° cell with at least one detection in a UTC day).
  It is not a fire count and not a burned area.
- **Method block.** `/calendar` returns a `method` object describing exactly how the numbers were computed
  (grid, platforms, SP/NRT preference, `harmonized: false`).

## Response headers

| Header | On | Meaning |
|---|---|---|
| `X-Process-Time-Ms` | all responses | Server processing time in milliseconds |
| `X-Total-Rows` | `/export.csv` | Number of rows in the file |
| `Content-Disposition` | `/export.csv` | Suggested file name |
| `Retry-After` | `503` when the database does not exist yet | Seconds to wait before retrying (60) |

These headers are exposed to browsers through CORS, so frontend code can read them.

## CORS

Only `GET` requests from the origins listed in `FRONTEND_URLS` are allowed (default `http://localhost:3000,http://127.0.0.1:3000`).
If the browser reports a CORS error, add the frontend's address to that variable. See
[Configuration](../operations/configuration.md#environment-variables).

## Compression

Responses larger than 1000 bytes are gzip-compressed when the client sends `Accept-Encoding: gzip`, which
browsers do automatically. For the world map layer this reduces about 1.8 MB to about 91 KB.

## Limits

Limits protect the server from heavy requests. They live in `config.py`.

| Endpoint | Maximum period | Other limits |
|---|---|---|
| `/calendar` | 3660 days (~10 years) for a region | Own rectangle: 366 days |
| `/calendar/monthly` | 14 640 days (40 years) for a region | Own rectangle: 366 days |
| `/cells` | 92 days | At most 20 000 cells; `truncated` flag if cut |
| `/points` | 7 days | At most 5000 points per page |
| `/harmonization` | 3660 days for a region | Own rectangle: 366 days |
| `/export.csv` | 31 days | At most 1 000 000 rows (streamed) |
| `/api/hotspots/` | one month | At most 10 000 cell-days; strongest per day kept, `truncated` and `total` |
| `/api/export/` | one month or one day | At most 1 000 000 rows |
| `/api/detections/` | one day (`date` is required) | At most 5000 detections per page (`limit`, `offset`) |
| `/api/sync/` | up to 366 days when `date_from`/`date_to` are given | Computed from the database only; NASA is never asked |
| `/anomaly` | n/a (uses a year and month) | Ready-made region only; needs at least 3 complete earlier years |

Exceeding a limit returns `400` with a message that states the maximum.
