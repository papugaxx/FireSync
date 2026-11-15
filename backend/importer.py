"""
importer.py — LOAD A NASA FIRMS ARCHIVE CSV INTO THE FIRESYNC DATABASE

    python importer.py                         # data/raw/NASA_FIRMS_2000_2025.csv
    python importer.py path/to/export.csv      # any FIRMS archive export with the same columns
    python importer.py --workers 4             # parallel reading (default: CPU cores - 1)
    python importer.py --max-minutes 10        # stop after ~10 minutes; run again to continue

What happens
------------
1. The file is split into pieces that several processes read at the same time.
   Rows of MODIS (Terra/Aqua) and VIIRS NOAA-20 are kept; other sources
   (VIIRS S-NPP, NOAA-21) are counted and skipped — the FireSync VIIRS series
   is NOAA-20 only. Rows with impossible values are counted and skipped.
2. All detections of one UTC day and one sensor are saved as one compressed
   block (store.py). If a day has both final (SP) and near-real-time (NRT) rows,
   only SP is kept.
3. The region tables (calendar numbers for config.REGIONS) are rebuilt.

It is safe to stop (Ctrl+C) and start again: progress is saved together with
the data (about once per year of the file), and the next run continues there.
`--max-minutes 10` stops on its own after about ten minutes. Use --replace
to import the whole file again. A day that the NASA updater stored as NRT is
replaced by the archive's final SP data; other stored days are kept.

The CSV itself is only read, never changed. After a successful import the API
does not need it any more.
"""

import argparse
import json
import os
import shutil
import sys
import time
from array import array
from collections import Counter
from contextlib import closing
from datetime import date
from multiprocessing import get_context
from pathlib import Path

import numpy as np

import config
import store

CHUNK_BYTES = 64 * 1024 ** 2          # one piece for one worker
SEGMENT_BYTES = 2 * 1024 ** 3        # progress is saved at the next year change after this much
MAX_BUFFERED = 40_000_000           # detections kept in memory before an intermediate save

SOURCES = {b"MODIS": "MODIS", b"VIIRS_NOAA20": "VIIRS"}
SATELLITE_CODES = {
    "MODIS": {b"Terra": 0, b"T": 0, b"TERRA": 0, b"Aqua": 1, b"A": 1, b"AQUA": 1},
    "VIIRS": {b"N20": 2, b"NOAA-20": 2, b"NOAA20": 2, b"J1": 2, b"1": 2},
}
CONFIDENCE_VIIRS = {k.encode(): v for k, v in store.VIIRS_CONFIDENCE.items()}
DAYNIGHT = {b"D": 1, b"N": 2, b"": 0}
INT_COLUMNS = ("lat", "lon", "time", "frp", "bright", "bright2", "scan", "track",
               "confidence", "satellite", "daynight", "type", "version")
# array.array type codes wide enough for every column before numpy narrows them
ARRAY_CODES = {"lat": "i", "lon": "i", "time": "H", "frp": "I", "bright": "I", "bright2": "I",
               "scan": "H", "track": "H", "confidence": "B", "satellite": "B", "daynight": "B",
               "type": "B", "version": "B"}


def _header(path):
    with open(path, "rb") as handle:
        names = handle.readline().decode("utf-8-sig").strip().lower().split(",")
    required = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence",
                "version", "frp", "source_product"}
    missing = required - set(names)
    if missing:
        raise SystemExit(f"The CSV is missing columns: {', '.join(sorted(missing))}")
    return names


def _chunks(path, size):
    total = os.path.getsize(path)
    return [(str(path), start, min(start + size, total)) for start in range(0, total, size)]


def _read_piece(path, start, end):
    """The lines whose first byte lies in [start, end)."""
    with open(path, "rb") as handle:
        if start > 0:
            handle.seek(start - 1)
            if handle.read(1) != b"\n":
                handle.readline()          # the rest of a line that belongs to the previous piece
        begin = handle.tell()
        data = handle.read(max(0, end - begin))
        if data and not data.endswith(b"\n"):
            data += handle.readline()
    if b"\r" in data:
        data = data.replace(b"\r", b"")
    return data


def _scaled(text, factor, missing):
    return round(float(text) * factor) if text else missing


def parse_piece(args):
    """Worker: parse one piece of the file into per-(sensor, day, product) column arrays."""
    path, start, end, names = args
    col = {name: i for i, name in enumerate(names)}
    i_lat, i_lon, i_date, i_time = col["latitude"], col["longitude"], col["acq_date"], col["acq_time"]
    i_sat, i_conf, i_ver, i_frp = col["satellite"], col["confidence"], col["version"], col["frp"]
    i_scan, i_track, i_dn, i_type = col.get("scan"), col.get("track"), col.get("daynight"), col.get("type")
    i_src = col["source_product"]
    bright = {"MODIS": (col.get("brightness"), col.get("bright_t31")),
              "VIIRS": (col.get("bright_ti4"), col.get("bright_ti5"))}
    width = len(names)
    source_last = i_src == width - 1
    groups, appenders, versions = {}, {}, {}
    other, stats = Counter(), Counter()
    kept = 0
    U32, U16 = 0xFFFFFFFF, 0xFFFF
    for line in _read_piece(path, start, end).split(b"\n"):
        if not line:
            continue
        if source_last:   # fast path: the source is the last value of the line
            if line.endswith(b",MODIS"):
                sensor = "MODIS"
            elif line.endswith(b",VIIRS_NOAA20"):
                sensor = "VIIRS"
            else:
                if not line.startswith(b"latitude,"):
                    other[line[line.rfind(b",") + 1:]] += 1
                continue
            fields = line.split(b",")
        else:
            fields = line.split(b",")
            sensor = SOURCES.get(fields[i_src]) if len(fields) == width else None
            if sensor is None:
                if len(fields) == width and not line.startswith(b"latitude,"):
                    other[fields[i_src]] += 1
                elif len(fields) != width:
                    stats["rejected_malformed"] += 1
                continue
        if len(fields) != width:
            stats["rejected_malformed"] += 1
            continue
        try:
            satellite = SATELLITE_CODES[sensor].get(fields[i_sat])
            if satellite is None:
                stats["rejected_satellite"] += 1
                continue
            lat = round(float(fields[i_lat]) * 100000)
            lon = round(float(fields[i_lon]) * 100000)
            hhmm = int(fields[i_time])
            text = fields[i_conf]
            if sensor == "MODIS":
                confidence = int(text) if text else 255
            else:
                confidence = CONFIDENCE_VIIRS.get(text.lower(), 255) if text else 255
            b1, b2 = bright[sensor]
            frp = _scaled(fields[i_frp], 100, U32)
            br1 = _scaled(fields[b1], 100, U32) if b1 is not None else U32
            br2 = _scaled(fields[b2], 100, U32) if b2 is not None else U32
            scan = _scaled(fields[i_scan], 100, U16) if i_scan is not None else U16
            track = _scaled(fields[i_track], 100, U16) if i_track is not None else U16
            daynight = DAYNIGHT.get(fields[i_dn], 0) if i_dn is not None else 0
            kind = int(fields[i_type]) if i_type is not None and fields[i_type] else 255
        except (ValueError, OverflowError):
            stats["rejected_value"] += 1
            continue
        if not (-9_000_000 <= lat <= 9_000_000 and -18_000_000 <= lon <= 18_000_000
                and 0 <= hhmm <= 2359 and hhmm % 100 < 60 and 0 <= confidence <= 255
                and 0 <= frp <= U32 and 0 <= br1 <= U32 and 0 <= br2 <= U32
                and 0 <= scan <= U16 and 0 <= track <= U16 and 0 <= kind <= 255
                and (confidence <= 100 or sensor != "MODIS" or confidence == 255)):
            stats["rejected_value"] += 1
            continue
        version = fields[i_ver]
        v = versions.get(version)
        if v is None:
            v = versions[version] = len(versions)
        key = (sensor, fields[i_date], "NRT" if version.upper().endswith(b"RT") else "SP")
        add = appenders.get(key)
        if add is None:
            group = groups[key] = {name: array(ARRAY_CODES[name]) for name in INT_COLUMNS}
            add = appenders[key] = [group[name].append for name in INT_COLUMNS]
        add[0](lat); add[1](lon); add[2](hhmm); add[3](frp); add[4](br1); add[5](br2)  # noqa: E702
        add[6](scan); add[7](track); add[8](confidence); add[9](satellite); add[10](daynight)  # noqa: E702
        add[11](kind); add[12](v)  # noqa: E702
        kept += 1
    stats["kept"] = kept
    for source, count in other.items():
        stats["skipped:" + source.decode("ascii", "replace")[:30]] += count
    order = [v.decode("ascii", "replace") for v, _ in sorted(versions.items(), key=lambda kv: kv[1])]
    return {key: {name: a.tobytes() for name, a in g.items()} for key, g in groups.items()}, order, stats


class Importer:
    def __init__(self, conn, started_at, replace=False):
        self.conn, self.started_at, self.replace = conn, started_at, replace
        self.pending = {}            # (sensor, day bytes) -> {product: [(columns, versions)]}
        self.months = set()          # months written since the last region rebuild
        self.stats = Counter()
        self.buffered = 0            # detections held in memory

    def add(self, groups, versions):
        """
        Keep the rows in memory per (sensor, day, product) until the file has moved on
        to another year: NASA archive exports are ordered by source and year, but the
        rows of one day are spread over that year's block. Each day is then written once.
        """
        current = set()
        for (sensor, day, product), columns in groups.items():
            self.pending.setdefault((sensor, day), {}).setdefault(product, []).append((columns, versions))
            self.buffered += len(columns["lat"]) // 4
            current.add((sensor, day[:4]))
        for key in [k for k in self.pending if (k[0], k[1][:4]) not in current]:
            self._finish(key, self.pending.pop(key))

    def finish_all(self):
        """Write everything that is still in memory (the caller commits)."""
        for key in list(self.pending):
            self._finish(key, self.pending.pop(key))
        self.buffered = 0

    @staticmethod
    def _columns(parts):
        """Join the pieces of one group into numpy arrays with one shared version list."""
        names, merged = [], {name: [] for name in INT_COLUMNS}
        for columns, versions in parts:
            mapping = np.array([names.index(v) if v in names else (names.append(v) or len(names) - 1)
                                for v in versions] or [0], dtype=np.uint8)
            for name in INT_COLUMNS:
                values = np.frombuffer(columns[name], dtype=np.dtype(ARRAY_CODES[name]))
                merged[name].append(mapping[values] if name == "version" else values)
        return {name: np.concatenate(v) for name, v in merged.items()}, names

    def _finish(self, key, products):
        sensor, day_bytes = key
        self.buffered -= sum(len(c["lat"]) // 4 for parts in products.values() for c, _ in parts)
        try:
            day = date.fromisoformat(day_bytes.decode("ascii")).isoformat()
        except ValueError:
            self.stats["rejected_date_rows"] += sum(len(c["lat"]) // 4 for parts in products.values()
                                                   for c, _ in parts)
            return
        product = "SP" if "SP" in products else "NRT"
        if len(products) == 2:
            self.stats["nrt_rows_replaced_by_sp"] += sum(len(c["lat"]) // 4 for c, _ in products["NRT"])
        columns, versions = self._columns(products[product])
        existing = store.stored_day(self.conn, day, sensor)
        if existing and existing["origin"] == "archive" and existing["loaded_at"] >= self.started_at:
            # Written earlier in this same import: the file is not sorted by day, so the
            # same day appears again. Add the rows (same product) or keep the better product.
            if store.PRODUCT_RANK[product] < store.PRODUCT_RANK[existing["product"]]:
                self.stats["nrt_rows_replaced_by_sp"] += len(columns["lat"])
                return
            if product == existing["product"]:
                old, old_versions = store.decode_block(self.conn.execute(
                    "SELECT block FROM day_data WHERE id = ?", (existing["id"],)).fetchone()[0])
                columns, versions = self._columns([
                    ({n: old[n].astype(ARRAY_CODES_NP[n]).tobytes() for n in INT_COLUMNS}, old_versions),
                    ({n: columns[n].astype(ARRAY_CODES_NP[n]).tobytes() for n in INT_COLUMNS}, versions)])
                self.stats["days_merged"] += 1
        elif existing:
            rank, old_rank = store.PRODUCT_RANK[product], store.PRODUCT_RANK[existing["product"]]
            if not (rank > old_rank or self.replace or (existing["origin"] == "api" and rank >= old_rank)):
                self.stats["days_already_stored"] += 1
                return
        result = store.write_day(self.conn, day, sensor, product, "archive", columns, versions)
        self.months.add(day[:7])
        self.stats["days_written"] += 1
        self.stats["bytes_written"] += result["bytes"]


ARRAY_CODES_NP = {name: np.dtype(code) for name, code in ARRAY_CODES.items()}


def _free_gb(path):
    return shutil.disk_usage(path).free / 1024 ** 3


def _ordered(pool, function, items, ahead):
    """Like pool.imap, but with at most `ahead` pieces read in advance (bounded memory)."""
    waiting = []
    for item in items:
        waiting.append((item, pool.apply_async(function, (item,))))
        if len(waiting) >= ahead:
            first, result = waiting.pop(0)
            yield first, result.get()
    for item, result in waiting:
        yield item, result.get()


def run(path, workers=None, replace=False, db=None, log=print, chunk_bytes=CHUNK_BYTES,
        segment_bytes=SEGMENT_BYTES, max_seconds=None):
    """Import (or continue importing) a FIRMS archive CSV. Returns a report dict."""
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    db = Path(db or store.db_path())
    db.parent.mkdir(parents=True, exist_ok=True)
    if _free_gb(db.parent) < 1:
        raise SystemExit("Less than 1 GB of free disk space next to the database. Free some space first.")
    names = _header(path)
    total = os.path.getsize(path)
    workers = workers or max(1, min(8, (os.cpu_count() or 2) - 1))
    clock = run_started = time.monotonic()
    conn = store.connect(db, create=True)
    identity = {"file": path.name, "bytes": total, "modified": int(path.stat().st_mtime)}
    progress = json.loads(store.get_meta(conn, "archive_progress") or "null")
    if replace or not progress or progress.get("identity") != identity:
        progress = {"identity": identity, "started_at": store.utc_now_text(), "done_until": 0,
                    "seconds": 0.0, "stats": {}, "replace": replace}
    if progress["done_until"] >= total:
        log(f"{path.name} is already imported. Use --replace to import it again.")
        conn.close()
        return json.loads(store.get_meta(store.connect(db), "archive_import") or "{}")
    importer = Importer(conn, progress["started_at"], progress.get("replace", False))
    counts = Counter(progress["stats"])
    offset = progress["done_until"]
    pending_months = set(json.loads(store.get_meta(conn, "archive_months_pending") or "[]"))
    if offset:
        log(f"Continuing {path.name} from {offset / total:.1%}.")
    log(f"Reading {path.name} ({total / 1024 ** 3:.1f} GB) with {workers} processes…")

    def save_point(pool, until):
        """Write what is in memory and remember the position — in one transaction."""
        nonlocal clock
        importer.finish_all()
        counts.update(importer.stats)
        importer.stats.clear()
        pending_months.update(importer.months)
        importer.months.clear()
        progress.update(done_until=until, seconds=progress["seconds"] + time.monotonic() - clock, stats=dict(counts))
        clock = time.monotonic()
        store.set_meta(conn, archive_progress=json.dumps(progress),
                       archive_months_pending=json.dumps(sorted(pending_months)))
        conn.commit()
        if pending_months:
            store.rebuild_months(conn, pending_months, path=db, pool=pool)
            pending_months.clear()
            with conn:
                store.set_meta(conn, archive_months_pending="[]")
        log(f"  {until / total:6.1%}  {counts['kept']:>12,} detections  "
            f"{counts['days_written']:>6,} day blocks written  {progress['seconds'] / 60:5.1f} min", flush=True)

    try:
        with get_context("spawn").Pool(workers) as pool:
            if pending_months:   # an earlier run stopped before the region tables were rebuilt
                save_point(pool, offset)
            pieces = [(str(path), s, min(s + chunk_bytes, total), names) for s in range(offset, total, chunk_bytes)]
            since_save, years = 0, None
            for (_, start, end, _), (groups, versions, stats) in _ordered(pool, parse_piece, pieces, workers * 2):
                importer.add(groups, versions)
                counts.update(stats)
                since_save += end - start
                piece_years = {(sensor, day[:4]) for sensor, day, _ in groups}
                year_changed = years is not None and bool(years - piece_years)
                years = piece_years or years
                out_of_time = max_seconds and time.monotonic() - run_started > max_seconds
                if (end >= total or (year_changed and since_save >= segment_bytes) or out_of_time
                        or importer.buffered > MAX_BUFFERED):
                    save_point(pool, end)
                    since_save = 0
                    if _free_gb(db.parent) < config.UPDATE_MIN_FREE_GB:
                        raise SystemExit("Stopped: the disk is almost full. Everything stored so far is kept; "
                                         "free some space and run the importer again to continue.")
                    if out_of_time:
                        break
            offset = progress["done_until"]
    except KeyboardInterrupt:
        log("Stopped. Everything up to the last saved point is stored; run the importer again to continue.")
        raise SystemExit(1)
    finally:
        conn.close()
    if offset < total:
        log(f"Paused at {offset / total:.1%}. Run the same command again to continue.")
        return {"status": "paused", "done_until": offset, "file_bytes": total}
    report = {
        "status": "completed", "file": path.name, "file_bytes": total,
        "finished_at": store.utc_now_text(), "minutes": round(progress["seconds"] / 60, 1),
        "rows_read": counts.pop("kept", 0),     # MODIS + NOAA-20 rows read from the file
        "skipped_other_sources": {k.split(":", 1)[1]: v for k, v in counts.items() if k.startswith("skipped:")},
        "rejected_rows": {k: v for k, v in counts.items() if k.startswith("rejected")},
        **{k: v for k, v in counts.items() if not k.startswith(("skipped:", "rejected"))},
    }
    with closing(store.connect(db)) as conn, conn:
        report["detections_stored"] = conn.execute(
            "SELECT COALESCE(SUM(observations), 0) FROM days WHERE origin = 'archive'").fetchone()[0]
        store.set_meta(conn, archive_import=json.dumps(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load a NASA FIRMS archive CSV into the FireSync database.")
    parser.add_argument("csv", nargs="?", default=str(config.ARCHIVE_CSV), help="path to the CSV file")
    parser.add_argument("--workers", type=int, default=None, help="reading processes (default: CPU cores - 1)")
    parser.add_argument("--replace", action="store_true", help="import the whole file again")
    parser.add_argument("--max-minutes", type=float, default=None, help="stop after about this many minutes")
    parser.add_argument("--db", default=None, help="database file (default: data/firesync.sqlite3)")
    args = parser.parse_args(argv)
    report = run(args.csv, args.workers, args.replace, args.db,
                 max_seconds=args.max_minutes * 60 if args.max_minutes else None)
    print(json.dumps(report, indent=2))
    with closing(store.connect(args.db)) as conn:
        print("Stored:", json.dumps(store.coverage(conn), indent=2))


if __name__ == "__main__":
    sys.exit(main())
