# Archive import and NASA updates

## 1. Import the archive (once)

The 2000–2025 archive export lives in `data/raw/NASA_FIRMS_2000_2025.csv` (50 GB, not in git).

```bash
python importer.py                       # data/raw/NASA_FIRMS_2000_2025.csv → data/firesync.sqlite3
python importer.py --max-minutes 10      # stop after ~10 minutes; run again to continue
python importer.py other_export.csv      # any FIRMS archive CSV with the same columns
python importer.py --workers 4           # reading processes (default: CPU cores - 1, at most 8)
python importer.py --replace             # import the whole file again
python importer.py --db other.sqlite3    # another database file (default: FIRESYNC_DB_PATH)
```

The default file is `FIRESYNC_ARCHIVE_CSV` (see [Configuration](../operations/configuration.md)).

- Rows of MODIS (Terra/Aqua) and VIIRS NOAA-20 are kept. VIIRS S-NPP (281 million rows in this file) and
  NOAA-21 are skipped: the FireSync VIIRS series is NOAA-20 only, and mixing platforms would double-count.
- Impossible values (coordinates, time, satellite) are counted and skipped; the report lists them.
- If a day has both SP and NRT rows, only SP is kept.
- Ctrl+C is safe. Progress is saved together with the data, and the next run continues there.
- Several processes read the file at the same time; on a laptop the import takes about 10 minutes.

Result for `NASA_FIRMS_2000_2025.csv`:

| | MODIS (Terra + Aqua) | VIIRS NOAA-20 |
|---|---|---|
| Days | 9 166 (2000-11-01 … 2025-12-31) | 2 826 (2018-04-01 … 2025-12-31) |
| Detections | 111 424 408 | 155 932 146 |

Days that are missing inside these ranges are instrument outages: they stay "no data".

!!! note "Offshore detections"
    The archive export contains almost no offshore detections (NASA `type` 3: gas platforms). Data from the
    API includes them. For a month this is about 0.3 % of MODIS detections.

## 2. Automatic updates from the NASA FIRMS API

The API starts `updater.py` in the background (unless `FIRESYNC_AUTO_UPDATE=0`). About a minute after start,
and then every `FIRESYNC_UPDATE_HOURS` hours (3 by default), it:

1. asks NASA which dates exist for MODIS and VIIRS NOAA-20 (SP and NRT);
2. plans what the database lacks after the end of the archive;
3. downloads one UTC day of one sensor for the whole world per request — the last week first, then the rest
   oldest first;
4. rebuilds the region tables of the changed months, so the website shows the new days.

| Situation | What happens |
|---|---|
| Day not stored | Downloaded: SP if NASA has it, otherwise NRT |
| Stored as NRT, NASA now has SP | Downloaded again as SP and replaced |
| Stored as NRT, younger than `FIRESYNC_REFRESH_RECENT_DAYS` (2) | Downloaded again — NASA keeps adding passes |
| Stored as SP (the whole archive) | Never downloaded again |
| A whole-world day comes back empty | Not stored: an outage is "no data", not "no fires" |
| Request limit, quota reserve, disk or size limit reached | The run stops with a reason; the next run continues |
| One bad NASA answer | That day is skipped and retried by the next run |

Responsibility is split by date: **2000–2025 comes only from the archive**; the API downloads from
`FIRESYNC_UPDATE_START_DATE` (2026-01-01), or from the day after the archive if the archive reaches further.
The start is a fixed day, not a moving window: in 2027 and later every missing day since 2026-01-01 is still
planned, and no code changes are needed for a new year. Even if the database has no archive at all, nothing
before the start date is asked from NASA (`updater.py --plan` then prints a warning and the database path).

When a run stops early — the request limit, the NASA quota, several network failures in a row — everything
stored so far is kept and the next run starts after `FIRESYNC_UPDATE_RETRY_MINUTES` (10) instead of the full
interval, until no day is missing. A single timed-out or malformed day is skipped and counted as still to do.
Catching up from 2026-01-01 takes about 640 requests and a few gigabytes; to do it at once:

```bash
python updater.py --until-done     # repeats runs until nothing is missing (waits after a failure)
```

### Sync state of every day

From the database alone (NASA is never asked by a page view) every day and sensor has a state:

| Day status | Meaning |
|---|---|
| `complete` | every sensor that observed the day is stored |
| `partial` | one sensor stored, the other still to come — or NRT of the last days that NASA is still adding passes to |
| `pending` | NASA offers the day; not downloaded yet |
| `unavailable` | NASA does not offer it (yet) through the API — e.g. between the end of SP and the start of NRT |
| `no_data` | archive years without observations (instrument outage) |
| `not_imported` | archive years while the archive has not been imported |
| `future` | the day has not happened yet |

`GET /api/sync/` (also inside `/status` and `/api/updates/`) gives the summary — per sensor the archive's last
day, the API's first day, counts, `pending_ranges` and `unavailable_ranges`, `last_success_at`,
`last_complete_at` and `last_error`. With `date_from`/`date_to` it lists every day. `/api/month/` gives every day
its `status`, `/api/calendar/` every month.

If NASA's API leaves a gap (`unavailable_ranges` not empty for a past period), the official alternative is the
FIRMS archive download (firms.modaps.eosdis.nasa.gov/download/): its CSV can be loaded with
`python importer.py <file.csv>` — SP from the archive replaces NRT, never the other way round.

The key is read from `data_pipeline/.env` (`FIRMS_MAP_KEY`). It never leaves the backend: it is not logged,
stored in the database or returned by the API. NASA URLs in errors are replaced with fixed messages.

### By hand

```bash
python updater.py --plan                  # what would be downloaded
python updater.py                         # one update now
python updater.py --max-requests 50       # one update with its own request limit
python updater.py --until-done            # repeat runs until nothing is missing
python updater.py --status                # what is stored and what the last update did
```

`GET /api/updates/` and `GET /status` show the same state over HTTP.
