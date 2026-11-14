"""Read-only common-grid summaries, not a calibrated harmonization model."""

from datetime import timedelta

from .store import _bbox_filter, _bbox_values, _canonical_cte, _period, _scope_id


_SOURCES = ("MODIS_SP", "MODIS_NRT", "VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT")


def grid_calendar(store, scope_id, start, end, *, bbox=None):
    """Count occupied 0.1-degree cells per UTC day for a bounded cached area.

    Each coordinate is rounded to an integer number of 1e-7 degrees before
    assignment to the fixed world grid. Raw observations are filtered by bbox
    before grouping, so partial edge cells do not include observations outside
    the requested rectangle. No observation objects are loaded into Python.
    """
    _scope_id(scope_id)
    start_text, end_text = _period(start, end)
    requested_days = (end - start).days + 1
    if requested_days > 366:
        raise ValueError("Grid analysis is limited to 366 UTC days per request.")
    bounds = _bbox_values(bbox)

    with store._connection() as conn:
        scope = store._require_scope(conn, scope_id)
        scope_bounds = tuple(scope[key] for key in ("west", "south", "east", "north"))
        if bounds is not None:
            west, south, east, north = bounds
            if not (scope["west"] <= west < east <= scope["east"]
                    and scope["south"] <= south < north <= scope["north"]):
                raise ValueError("Analysis bbox must fit completely inside the saved scope.")

        cte, base_params = _canonical_cte(scope_id, start_text, end_text)
        input_rows = conn.execute(
            cte + """SELECT w.day,w.source_code,fw.checksum,fw.fetched_at,
                            fw.row_count,fw.last_error
                     FROM canonical_windows AS w
                     JOIN fetch_windows AS fw ON fw.id=w.id
                     WHERE w.source_code IN (?,?,?,?)
                     ORDER BY w.day,w.source_code""",
            [*base_params, *_SOURCES],
        ).fetchall()
        input_windows = [dict(row) for row in input_rows]
        loaded = {"modis": set(), "viirs": set()}
        for row in input_windows:
            channel = "modis" if row["source_code"].startswith("MODIS_") else "viirs"
            loaded[channel].add(row["day"])

        bbox_sql, bbox_params = _bbox_filter(bounds)
        # Integer operands make the division a floor because the shifted world
        # coordinates are non-negative. Clamp the inclusive +180/+90 borders.
        sql = cte + """, grid_points AS (
            SELECT w.day,d.sensor,
                   MIN(3599, (CAST(ROUND(d.longitude*10000000.0) AS INTEGER)
                              +1800000000)/1000000) AS cell_x,
                   MIN(1799, (CAST(ROUND(d.latitude*10000000.0) AS INTEGER)
                              +900000000)/1000000) AS cell_y
            FROM detections AS d
            JOIN canonical_windows AS w ON w.id=d.window_id
            WHERE ((w.source_code IN (?,?) AND d.satellite IN ('Terra','Aqua'))
                OR (w.source_code IN (?,?) AND d.satellite='NOAA-20'))
            """ + bbox_sql + """
        ), cell_counts AS (
            SELECT day,cell_x,cell_y,
                   SUM(CASE WHEN sensor='MODIS' THEN 1 ELSE 0 END) AS modis_observations,
                   SUM(CASE WHEN sensor='VIIRS' THEN 1 ELSE 0 END) AS viirs_observations
            FROM grid_points GROUP BY day,cell_x,cell_y
        )
        SELECT day,SUM(modis_observations) AS modis_observations,
                   SUM(viirs_observations) AS viirs_observations,
                   SUM(CASE WHEN modis_observations>0 THEN 1 ELSE 0 END) AS modis_cells,
                   SUM(CASE WHEN viirs_observations>0 THEN 1 ELSE 0 END) AS viirs_cells,
                   SUM(CASE WHEN modis_observations>0 AND viirs_observations>0
                            THEN 1 ELSE 0 END) AS shared_cells
        FROM cell_counts GROUP BY day ORDER BY day
        """
        grouped = {row["day"]: dict(row) for row in conn.execute(
            sql, [*base_params, *_SOURCES, *bbox_params]
        )}

    daily = []
    for offset in range(requested_days):
        day_text = (start + timedelta(days=offset)).isoformat()
        values = grouped.get(day_text, {})
        result = {"date": day_text}
        for channel in ("modis", "viirs"):
            available = day_text in loaded[channel]
            result[channel] = {
                "status": "loaded" if available else "missing",
                "observations": int(values.get(f"{channel}_observations", 0)) if available else None,
                "active_cells": int(values.get(f"{channel}_cells", 0)) if available else None,
            }
        result["shared_active_cells"] = (
            int(values.get("shared_cells", 0))
            if day_text in loaded["modis"] and day_text in loaded["viirs"] else None
        )
        daily.append(result)

    totals = {}
    for channel in ("modis", "viirs"):
        complete = len(loaded[channel]) == requested_days
        totals[channel] = {
            "observations": sum(row[channel]["observations"] for row in daily) if complete else None,
            "active_cell_days": sum(row[channel]["active_cells"] for row in daily) if complete else None,
        }

    return {
        "scope_id": scope_id,
        "date_from": start_text,
        "date_to": end_text,
        "bbox": list(bounds if bounds is not None else scope_bounds),
        "method": {
            "id": "common-grid-0p1deg-v1",
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
            "processing_preference": "loaded SP, otherwise loaded NRT, per family and UTC day",
            "confidence_filter": "all",
            "type_filter": "all",
            "wildfire_only": False,
            "equal_area": False,
            "burned_area": False,
            "bbox_semantics": "inclusive rectangle; observations filtered before cell grouping",
            "interpretation": "Observed active cell-days, not unique fires or burned area; platform exposures differ.",
        },
        "daily": daily,
        "coverage": {
            channel: {"loaded_days": len(loaded[channel]), "requested_days": requested_days}
            for channel in ("modis", "viirs")
        },
        "totals": totals,
        "input_windows": input_windows,
    }
