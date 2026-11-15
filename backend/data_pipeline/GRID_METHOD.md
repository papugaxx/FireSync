# Calculating active cells: the first comparative indicator

## What we count

For each UTC day we take the valid records from the loaded NASA slice. When both variants
of one family exist, SP is preferred, otherwise NRT is used.
One successful API slice does not prove full observation of the territory by the satellite.

The fixed composition of the first comparison:

- MODIS: Terra and Aqua; the cells are merged, and the same cell is not counted twice.
- VIIRS: NOAA-20 only. S-NPP and NOAA-21 are not added to this series.

The grid is common for the whole world: EPSG:4326, step 0.1°, origin at (-180°, -90°).
It does not shift when an area is chosen. Before the cell index is determined, the coordinates
are rounded to 0.0000001°. Borders inside the grid belong to the cell to the right/above;
the extreme +180°/+90° belong to the last cells. The selection rectangle filters
the raw points before aggregation and includes its own borders.

A cell is active if there is at least one selected record in it during the day.
All valid confidence/type values are kept in the calculation.

## Units and gaps

The daily value is the number of active cells. The sum over days is cell-days.
One cell with detections on 20 days gives 20 cell-days. This is not the number of separate
fires and not a burned area. The area of geographic cells changes with latitude.

If a slice is not loaded, the value is `null`. A loaded empty slice gives 0 detections;
this is not proof of the absence of fire. The total for a source becomes `null` if
at least one requested day is not loaded.

A "both" cell means the presence of both selected sets in the same cell and day.
This does not establish a simultaneous observation of one physical fire.

## What this stage does not calculate

The grid does not remove the different sensitivity of the instruments. A separate experiment with a scale correction and a check on held-out dates
is described in CALIBRATION_METHOD.md. The historical median, anomalies and confirmation of
transferability to other periods remain for the next stages. `harmonized: false`; the R² value is absent for now.

The result is read from one database snapshot. The loaded input windows and parameters
must be saved together with the report for reproducibility.

## Primary sources

- [NASA FIRMS Important Notes](https://firms.modaps.eosdis.nasa.gov/alerts/notes.php):
  detection limitations and MODIS/VIIRS differences.
- [NASA MODIS Active Fire product](https://modaps.modaps.eosdis.nasa.gov/services/about/products/c61-nrt/MCD14DL-NRT.html):
  the meaning of a detection point and thermal anomalies.

The 0.1° grid and the fixed composition of the comparison are a transparent choice of our prototype,
not a harmonization standard announced by NASA.
