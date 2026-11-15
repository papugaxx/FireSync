"""
reports.py — CALENDAR, MONTHS, MAP CELLS AND POINTS FROM THE DATABASE

Everything the API returns is computed here from store.py:
  * a ready-made region (config.REGIONS) is read from the precomputed region tables — milliseconds;
  * an own rectangle (west/south/east/north) is computed from the stored detections
    day by day, so its period is limited (config.MAX_CUSTOM_AREA_DAYS).

The report formats are the same as before (the partner's grid_calendar format), so
analytics.py and the partner's calibration work on them unchanged.
"""

from datetime import date, timedelta

import numpy as np

import config
import store

METHOD = {
    # The same fields as the partner's report: his calibrate_calendar() checks them
    "id": "common-grid-0p1deg-v1",
    "engine": "firesync-store-v1",
    "harmonized": False,
    "harmonization_status": "not_calibrated",
    "r2": None,
    "grid_degrees": 0.1,
    "grid_crs": "EPSG:4326",
    "time_basis": "UTC",
    "origin": {"longitude": -180, "latitude": -90},
    "coordinate_quantization_degrees": 1e-7,
    "coordinate_rounding": "nearest integer tick; halfway away from zero",
    "daily_unit": "active_cells_per_UTC_day",
    "total_unit": "active_cell_days",
    "modis_platforms": ["Terra", "Aqua"],
    "modis_combination": "union of occupied cells per UTC day",
    "viirs_platforms": ["NOAA-20"],
    "processing_preference": "SP if stored, otherwise NRT, per sensor and UTC day (never both)",
    "confidence_filter": "all",
    "type_filter": "all",
    "wildfire_only": False,
    "equal_area": False,
    "burned_area": False,
    "bbox_semantics": "whole 0.1-degree grid cells; the requested rectangle is expanded outward to grid lines",
    "interpretation": "Observed active cell-days, not unique fires or burned area; platform exposures differ.",
}
WORLD_BBOX = [-180.0, -90.0, 180.0, 90.0]
SOURCE_CODE = {("MODIS", "SP"): "MODIS_SP", ("MODIS", "NRT"): "MODIS_NRT",
               ("VIIRS", "SP"): "VIIRS_NOAA20_SP", ("VIIRS", "NRT"): "VIIRS_NOAA20_NRT"}


def area(region=None, bbox=None):
    """A ready-made region or an own rectangle (west, south, east, north); nothing = the world."""
    if region is not None:
        if region not in config.REGIONS:
            raise ValueError(f"Unknown region '{region}'. See /regions for the list.")
        bbox = config.REGIONS[region]["bbox"]
        if bbox is None:
            return {"region": region, "scope_id": region, "cells": None, "bbox": WORLD_BBOX, "requested_bbox": None}
    elif bbox is None:
        return {"region": "world", "scope_id": "world", "cells": None, "bbox": WORLD_BBOX, "requested_bbox": None}
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Bounds need west < east and south < north (longitude first, then latitude).")
    cells = store.cell_range(bbox)
    return {"region": region, "scope_id": region or "custom", "cells": cells,
            "bbox": store.cells_to_bbox(cells), "requested_bbox": list(bbox)}


def _days(start, end):
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _custom_day_rows(conn, cells, days):
    """region_days-like rows for an own rectangle, computed from the stored detections."""
    stored = store.stored_days(conn, days[0], days[-1])
    rows = {}
    for day in days:
        present = {s: stored[(day, s)] for s in store.SENSORS if (day, s) in stored}
        if not present:
            continue
        row, inside = {"day": day}, {}
        for sensor in store.SENSORS:
            ch = store.CHANNEL[sensor]
            if sensor not in present:
                row.update({f"{ch}_cells": None, f"{ch}_obs": None, f"{ch}_frp_n": None,
                            f"{ch}_frp_sum": None, f"{ch}_frp_max": None, f"{ch}_product": None})
                continue
            s = store.day_cell_summary(conn, day, sensor)
            mask = store.in_cells(s["cell"], cells)
            inside[sensor] = s["cell"][mask]
            frp_max = int(s["frp_max"][mask].max()) if mask.any() else -1
            row.update({f"{ch}_cells": int(mask.sum()), f"{ch}_obs": int(s["obs"][mask].sum()),
                        f"{ch}_frp_n": int(s["frp_n"][mask].sum()), f"{ch}_frp_sum": int(s["frp_sum"][mask].sum()) / 100,
                        f"{ch}_frp_max": frp_max / 100 if frp_max >= 0 else None, f"{ch}_product": present[sensor]})
        row["shared_cells"] = (len(np.intersect1d(inside["MODIS"], inside["VIIRS"], assume_unique=True))
                               if len(inside) == 2 else None)
        rows[day] = row
    return rows


def day_rows(conn, where, start, end):
    """{day: row} with per-sensor cells, detections and FRP for a region or own rectangle."""
    if where["region"]:
        return store.region_day_rows(conn, where["region"], start, end)
    if (end - start).days + 1 > config.MAX_CUSTOM_AREA_DAYS:
        raise ValueError(f"For an own rectangle the period is limited to {config.MAX_CUSTOM_AREA_DAYS} days. "
                         "Use a ready-made region from /regions for longer periods.")
    return _custom_day_rows(conn, where["cells"], _days(start, end))


def calendar(conn, where, start, end):
    """Daily calendar in the partner's grid_calendar format."""
    days = _days(start, end)
    rows = day_rows(conn, where, start, end)
    stored = store.stored_days(conn, start, end)
    daily = []
    for day in days:
        row = rows.get(day, {})
        item = {"date": day}
        for sensor in store.SENSORS:
            ch = store.CHANNEL[sensor]
            ok = (day, sensor) in stored
            item[ch] = {"status": "loaded" if ok else "missing",
                        "product": stored.get((day, sensor)),
                        "observations": int(row.get(f"{ch}_obs") or 0) if ok else None,
                        "active_cells": int(row.get(f"{ch}_cells") or 0) if ok else None}
        both = (day, "MODIS") in stored and (day, "VIIRS") in stored
        item["shared_active_cells"] = int(row.get("shared_cells") or 0) if both else None
        daily.append(item)
    totals, coverage = {}, {}
    for sensor in store.SENSORS:
        ch = store.CHANNEL[sensor]
        loaded = sum(1 for d in daily if d[ch]["status"] == "loaded")
        complete = loaded == len(days)
        coverage[ch] = {"loaded_days": loaded, "requested_days": len(days)}
        totals[ch] = {"observations": sum(d[ch]["observations"] for d in daily) if complete else None,
                      "active_cell_days": sum(d[ch]["active_cells"] for d in daily) if complete else None}
    windows = [{"day": r["day"], "source_code": SOURCE_CODE[(r["sensor"], r["product"])], "origin": r["origin"],
                "row_count": r["observations"], "fetched_at": r["loaded_at"]}
               for r in conn.execute("SELECT day, sensor, product, origin, observations, loaded_at FROM days "
                                     "WHERE day BETWEEN ? AND ? ORDER BY day, sensor", (str(start), str(end)))]
    return {"scope_id": where["scope_id"], "region": where["region"], "date_from": start.isoformat(),
            "date_to": end.isoformat(), "bbox": where["bbox"], "requested_bbox": where["requested_bbox"],
            "method": dict(METHOD), "daily": daily, "coverage": coverage, "totals": totals,
            "input_windows": windows}


def _month_starts(start, end):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        yield cursor, following
        cursor = following


def monthly(conn, where, start, end):
    """
    Per month and sensor: status (complete / partial / missing), cell-days, detections,
    area of the distinct active cells, FRP. Months cut by the period edges have no area.
    """
    rows = day_rows(conn, where, start, end) if not where["region"] else None
    region_months = (store.region_month_rows(conn, where["region"], start.strftime("%Y-%m"), end.strftime("%Y-%m"))
                     if where["region"] else {})
    stored = store.stored_days(conn, start, end)
    shared = {}
    if where["region"]:
        for r in conn.execute("SELECT substr(day, 1, 7) AS m, SUM(shared_cells) AS s, COUNT(shared_cells) AS n "
                              "FROM region_days WHERE region = ? AND day BETWEEN ? AND ? GROUP BY m",
                              (where["region"], str(start), str(end))):
            shared[r["m"]] = r["s"] if r["n"] else None
    months = []
    for first, following in _month_starts(start, end):
        lo, hi = max(first, start), min(following - timedelta(days=1), end)
        key = first.strftime("%Y-%m")
        whole = lo == first and hi == following - timedelta(days=1)
        item = {"month": key, "year": first.year, "month_number": first.month, "days": (hi - lo).days + 1}
        part_rows = None
        if not (where["region"] and whole):
            source = rows if rows is not None else store.region_day_rows(conn, where["region"], lo, hi)
            part_rows = [source[d] for d in _days(lo, hi) if d in source]
        for sensor in store.SENSORS:
            ch = store.CHANNEL[sensor]
            loaded = sum(1 for d in _days(lo, hi) if (d, sensor) in stored)
            entry = {"status": "missing" if not loaded else ("complete" if loaded == item["days"] else "partial"),
                     "loaded_days": loaded, "nrt_days": 0, "active_cell_days": None, "observations": None,
                     "area_km2": None, "cell_day_area_km2": None, "frp_mean": None, "frp_max": None,
                     "frp_observations": None}
            if loaded and part_rows is None:
                m = region_months.get((key, sensor))
                if m:
                    entry.update(nrt_days=m["nrt_days"], active_cell_days=m["cell_days"],
                                 observations=m["observations"], area_km2=m["area_km2"],
                                 cell_day_area_km2=m["cell_day_area_km2"], frp_observations=m["frp_n"],
                                 frp_mean=round(m["frp_sum"] / m["frp_n"], 2) if m["frp_n"] else None,
                                 frp_max=m["frp_max"])
            elif loaded:
                values = [r for r in part_rows if r.get(f"{ch}_cells") is not None]
                frp_n = sum(r[f"{ch}_frp_n"] for r in values)
                frp_sum = sum(r[f"{ch}_frp_sum"] for r in values)
                maxima = [r[f"{ch}_frp_max"] for r in values if r[f"{ch}_frp_max"] is not None]
                entry.update(active_cell_days=sum(r[f"{ch}_cells"] for r in values),
                             observations=sum(r[f"{ch}_obs"] for r in values),
                             nrt_days=sum(1 for r in values if r[f"{ch}_product"] == "NRT"),
                             frp_observations=frp_n, frp_mean=round(frp_sum / frp_n, 2) if frp_n else None,
                             frp_max=max(maxima) if maxima else None)
            item[ch] = entry
        both = item["modis"]["loaded_days"] and item["viirs"]["loaded_days"]
        if part_rows is None:
            item["shared_cell_days"] = shared.get(key) if both else None
        else:
            values = [r["shared_cells"] for r in part_rows if r.get("shared_cells") is not None]
            item["shared_cell_days"] = sum(values) if both and values else (0 if both else None)
        months.append(item)
    return {"scope_id": where["scope_id"], "region": where["region"], "bbox": where["bbox"],
            "requested_bbox": where["requested_bbox"], "date_from": start.isoformat(), "date_to": end.isoformat(),
            "months": months}


def day_cells(conn, day, cells):
    """
    Active cells of one day inside a cell range, both sensors merged (numpy arrays, sorted by cell):
    cell, modis_obs, viirs_obs, frp_max (MW × 100, -1 = no FRP), frp_sum (MW × 100), frp_n.
    """
    parts = {}
    for sensor in store.SENSORS:
        s = store.day_cell_summary(conn, day, sensor)
        if s is not None:
            mask = store.in_cells(s["cell"], cells)
            parts[sensor] = {k: v[mask] for k, v in s.items()}
    if not parts:
        return None
    ids = np.unique(np.concatenate([p["cell"] for p in parts.values()]))
    result = {"cell": ids, "modis_obs": np.zeros(len(ids), np.int64), "viirs_obs": np.zeros(len(ids), np.int64),
              "frp_max": np.full(len(ids), -1, np.int64), "frp_sum": np.zeros(len(ids), np.int64),
              "frp_n": np.zeros(len(ids), np.int64)}
    for sensor, part in parts.items():
        at = np.searchsorted(ids, part["cell"])
        result[f"{store.CHANNEL[sensor]}_obs"][at] = part["obs"]
        result["frp_max"][at] = np.maximum(result["frp_max"][at], part["frp_max"])
        result["frp_sum"][at] += part["frp_sum"]
        result["frp_n"][at] += part["frp_n"]
    return result


def cell_center(cell):
    return round((cell // 3600 + 0.5) / 10 - 90, 2), round((cell % 3600 + 0.5) / 10 - 180, 2)


def map_cells(conn, where, start, end, step=1, limit=20_000):
    """Cells (or blocks of step × step cells) with active days and detections, most active first."""
    if (end - start).days + 1 > config.MAX_MAP_DAYS:
        raise ValueError(f"The map is limited to {config.MAX_MAP_DAYS} days per request.")
    step = int(step)
    columns = 3600 // step + 1
    parts = {"block": [], "day": [], "mobs": [], "vobs": [], "mcell": [], "vcell": []}
    for number, day in enumerate(_days(start, end)):
        for sensor in store.SENSORS:
            s = store.day_cell_summary(conn, day, sensor)
            if s is None:
                continue
            mask = store.in_cells(s["cell"], where["cells"])
            ids = s["cell"][mask]
            block = (ids // 3600 // step) * columns + (ids % 3600) // step
            parts["block"].append(block)
            parts["day"].append(np.full(len(block), number))
            obs = s["obs"][mask]
            zero = np.zeros(len(block), dtype=np.int64)
            parts["mobs"].append(obs if sensor == "MODIS" else zero)
            parts["vobs"].append(obs if sensor == "VIIRS" else zero)
            parts["mcell"].append(np.ones(len(block), dtype=np.int64) if sensor == "MODIS" else zero)
            parts["vcell"].append(np.ones(len(block), dtype=np.int64) if sensor == "VIIRS" else zero)
    if not parts["block"] or not sum(len(b) for b in parts["block"]):
        return {"area": where, "cells": [], "truncated": False}
    data = {k: np.concatenate(v) for k, v in parts.items()}
    blocks, inverse = np.unique(data["block"], return_inverse=True)
    sums = {k: np.bincount(inverse, weights=data[k], minlength=len(blocks)).astype(np.int64)
            for k in ("mobs", "vobs", "mcell", "vcell")}
    active = np.bincount(np.unique(inverse * 100_000 + data["day"]) // 100_000, minlength=len(blocks))
    order = np.lexsort((-(sums["mobs"] + sums["vobs"]), -active))[:limit + 1]
    size = step / 10
    result = []
    for i in order[:limit]:
        gy, gx = int(blocks[i]) // columns, int(blocks[i]) % columns
        result.append({"gy": gy, "gx": gx, "active_days": int(active[i]),
                       "modis_cell_days": int(sums["mcell"][i]), "viirs_cell_days": int(sums["vcell"][i]),
                       "modis_observations": int(sums["mobs"][i]), "viirs_observations": int(sums["vobs"][i]),
                       "lon": round((gx * step + step / 2) / 10 - 180, 4),
                       "lat": round((gy * step + step / 2) / 10 - 90, 4), "cell_size_degrees": size})
    return {"area": where, "cells": result, "truncated": len(order) > limit}


def detection_count(conn, where, start, end, sensor=None):
    """Number of detections in the selection (exact; from the region tables when possible)."""
    sensors = [sensor] if sensor else list(store.SENSORS)
    rows = day_rows(conn, where, start, end)
    return sum(int(r[f"{store.CHANNEL[s]}_obs"] or 0) for r in rows.values() for s in sensors)


def points(conn, where, start, end, sensor=None):
    """Individual detections day by day (a generator, so large exports stream)."""
    for day in _days(start, end):
        for s in ([sensor] if sensor else store.SENSORS):
            yield from store.detections(conn, day, s, where["cells"])


def loaded_summary(conn):
    """What the database holds, in the shape of the old /status answer."""
    coverage = store.coverage(conn)
    result = {"world": {ch: {"first_day": v["first_day"], "last_day": v["last_day"], "loaded_days": v["days"],
                             "nrt_days": v["nrt_days"], "observations": v["observations"]}
                        for ch, v in coverage.items()}}
    return result
