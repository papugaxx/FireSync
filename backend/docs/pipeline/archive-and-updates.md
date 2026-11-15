# Archive import and NASA updates

## 1. Import the archive (once)

The 2000–2025 archive export lives in `data/raw/NASA_FIRMS_2000_2025.csv` (50 GB, not in git).

```bash
python importer.py                       # data/raw/NASA_FIRMS_2000_2025.csv → data/firesync.sqlite3
python importer.py --max-minutes 10      # stop after ~10 minutes; run again to continue
python importer.py other_export.csv      # any FIRMS archive CSV with the same columns
```

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

When a run stops at the request limit with work left over, the next run starts after 10 minutes instead of
waiting the full interval. Catching up after the archive (2026-01-01 until today) takes about 640 requests and a
few gigabytes of download; it happens over several runs.

The key is read from `data_pipeline/.env` (`FIRMS_MAP_KEY`). It never leaves the backend: it is not logged,
stored in the database or returned by the API. NASA URLs in errors are replaced with fixed messages.

### By hand

```bash
python updater.py --plan      # what would be downloaded
python updater.py             # one update now
python updater.py --status    # what is stored and what the last update did
```

`GET /api/updates/` and `GET /status` show the same state over HTTP.
