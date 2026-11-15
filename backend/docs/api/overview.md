# HTTP API overview

This page describes the conventions shared by all endpoints. Each endpoint is documented on the
[Endpoints](endpoints.md) page. The live, always-current schema is served by the running API at
`/docs` (Swagger UI) and `/openapi.json`.

## Base URL

| Environment | Base URL |
|---|---|
| Local development | `http://localhost:8000` |
| Production | `https://api.YOUR-DOMAIN` (see [Deployment](../operations/deployment.md)) |

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
| Ready-made region | `region=ukraine` | A named rectangle from [`/regions`](endpoints.md#get-regions) |
| Custom rectangle | `west`, `south`, `east`, `north` | Your own box. **All four** are required |
| Nothing | (none) | The whole world |

Rules:

- `region` cannot be combined with `west`/`south`/`east`/`north`.
- Order is **longitude first, then latitude**: `west` and `east` are longitudes (-180 to 180); `south` and
  `north` are latitudes (-90 to 90). Be careful: some frontend types use `[south, west, north, east]`.
- `west < east` and `south < north`. Crossing the antimeridian in one box is not supported.
- The rectangle must lie inside the loaded data scope.
- The rectangle is expanded outward to whole 0.1° cells. Responses return both `requested_bbox` and the
  `bbox` that was actually computed. See [Grid and calendar](../concepts/grid-and-calendar.md#regions-are-whole-cells).

Every response that takes an area includes an `area` object:

```json
{
  "region": "ukraine",
  "scope_id": "world",
  "requested_bbox": [22.0, 44.0, 41.0, 53.0],
  "bbox": [22.0, 44.0, 41.0, 53.0]
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
| `503` | The service cannot answer yet | Index still building (also sends `Retry-After: 30`); database file missing |
| `500` | Unexpected pipeline failure | |

`422` responses add a `details` array of `{"param", "message"}` objects so a form can highlight the faulty field.

!!! note "Language of messages"
    The `error` text is currently written in Russian. Rely on the HTTP status for program logic and show
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
| `Retry-After` | `503` while the index builds | Seconds to wait before retrying |

These headers are exposed to browsers through CORS, so frontend code can read them.

## CORS

Only `GET` requests from the origins listed in `FRONTEND_URLS` are allowed (default `http://localhost:3000`).
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
| `/anomaly` | n/a (uses a year and month) | Needs at least 3 other complete years |

Exceeding a limit returns `400` with a message that states the maximum.
