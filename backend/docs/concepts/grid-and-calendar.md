# Grid and calendar

FireSync does not count fires. It counts **active cells** on a fixed global grid. This page defines exactly
what that means, so the numbers in the API can be interpreted correctly.

## The grid

| Property | Value |
|---|---|
| Coordinate system | EPSG:4326 (latitude/longitude) |
| Cell size | 0.1° (roughly 10 km, but the east-west width shrinks toward the poles) |
| Origin | (-180°, -90°) |
| Size | 3600 columns (`cell_x` 0..3599) by 1800 rows (`cell_y` 0..1799) |
| Time basis | UTC days |

The grid is the same for the whole world and does **not** shift when you choose a region.

Coordinates are first rounded to 0.0000001° (a "tick"), then converted to a cell index:

```text
cell_x = min(3599, floor((longitude + 180) / 0.1))
cell_y = min(1799, floor((latitude  +  90) / 0.1))
```

A point exactly on a grid line belongs to the cell to its right / above. The extreme edges (+180° and +90°)
belong to the last cell. `store.py` (on coordinates stored × 100 000) and the pipeline's `analytics.py` use the same formula,
which is what makes the database match the reference calculation exactly.

## What counts as "active"

A cell is **active** on a UTC day if at least one valid detection from the chosen satellites falls inside it.

- **MODIS series** = Terra + Aqua. Their occupied cells are merged, so a cell seen by both is counted once.
- **VIIRS series** = NOAA-20 only. S-NPP and NOAA-21 are deliberately **not** part of this comparison.
- All confidence levels and detection types are kept. There is no mask for industrial heat sources, so this is
  a measure of *thermal detections*, not strictly of wildfires.

### Units

| Name | Meaning |
|---|---|
| `active_cells` | Number of active cells in one UTC day. This is the main calendar number. |
| `active_cell_days` | Sum of daily `active_cells` over a period. One cell active on 20 days contributes 20. |
| `observations` | Raw number of detections (points) in the loaded slice. |
| `shared_active_cells` | Cells active in **both** series on the same day. This does not prove both satellites saw the same physical fire. |

!!! warning "What these numbers are not"
    An active cell is **not** a number of fires and **not** a burned area. Cell area also changes with latitude,
    so the grid is not equal-area. `method.interpretation` in `/calendar` restates this.

## SP over NRT

NASA provides each product in two processing levels:

- **SP** (standard processing): final, reprocessed data.
- **NRT** (near real time): available within hours but may later be superseded.

For each day and satellite family, FireSync stores exactly one product: SP when NASA has it, otherwise NRT.
When SP appears later, the NRT day is replaced (`updater.py`); the archive import keeps only SP rows when a day
has both. The two are never added together.

## Missing versus zero

This distinction matters throughout the API:

| Value | Meaning |
|---|---|
| `null` / `"status": "missing"` | The day was **not loaded**. Nothing is known. |
| `0` / `"status": "loaded"` | The day was loaded and no detections were found. |

A loaded day with zero detections does not prove that nothing was burning; it only means the satellite
reported nothing there. Likewise, one successful download does not prove complete coverage of the territory.

Totals follow the same rule: if **any** requested day of a series is missing, that series' total is `null`
rather than a misleadingly small number.

## Regions are whole cells

A requested rectangle is expanded **outward** to the nearest 0.1° grid lines. The response carries both
`requested_bbox` (what you sent) and `bbox` (what was actually computed).

```text
requested  west=22.04  south=44.01  east=40.96  north=52.99
computed   west=22.0   south=44.0   east=41.0   north=53.0
```

This is the one deliberate difference from the pipeline's own `grid_calendar()`, which filters raw points by
the exact rectangle. A point on the boundary between two neighbouring regions is therefore counted in exactly
**one** of them, never both, so adjacent regions can be added without double counting. For rectangles that
already lie on grid lines, the two methods give identical numbers.

Regions are rectangles, not administrative borders. "Ukraine" in `/regions` is the box
`[22.1, 44.3, 40.2, 52.4]` (west, south, east, north), which also covers parts of neighbouring countries.
A box may not cross the antimeridian (±180°).

## Calendar levels

For coloring, each daily value is mapped to a level:

| Level | Meaning |
|---|---|
| `null` | No data (day not loaded) |
| `0` | No active cells |
| `1`..`4` | Weak to strong activity |

The level boundaries are the **quartiles of the non-zero values in the requested period**, calculated separately
for MODIS and VIIRS (`analytics.color_breaks`). The boundaries are returned in `color_scale` so a frontend can
draw a matching legend. Because they are computed per request, the same count can receive different levels in
different periods or regions.

## Monthly view

`/calendar/monthly` aggregates days into months. Each month reports its completeness per series:

| Status | Meaning |
|---|---|
| `complete` | Every day of the month was loaded |
| `partial` | Some days were loaded |
| `missing` | No days were loaded |

For a requested period that cuts a month short, "every day" means every day *within the request*.

## Known-event check

Athens-area fire, 11–13 August 2024 (rectangle 23.5–24.2°E, 37.8–38.4°N):

| UTC day | MODIS detections | VIIRS NOAA-20 detections |
|---|---|---|
| Aug 11 | 43 | 179 |
| **Aug 12** | **131** | **256** |
| Aug 13 | 2 | 23 |

On Aug 12 there were 5 MODIS cells and 7 VIIRS cells, with 5 cells seen by both. This supports location and timing
consistency; attributing individual hotspots to the event needs further review.
