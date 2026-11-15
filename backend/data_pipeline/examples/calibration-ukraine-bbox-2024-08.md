# Result of the first reconciliation experiment

The correction reduced the mean discrepancy from the chosen MODIS reference on the held-out
dates. At the same time the daily dynamics are conveyed weakly: R² is only about 0.014.
This is a limited experiment, not a confirmed harmonization of the whole history.

## Area and data

- Rectangle: west=22, south=44, east=41, north=53. This is an area around Ukraine,
  not the exact border of the country.
- Grid: 0.1°, UTC days, all valid confidence/type values.
- Reference: the union of active MODIS Terra and Aqua cells.
- Second series: active VIIRS NOAA-20 cells.
- Fitting the coefficient: 1–21 August 2024, 21 paired days.
- Check independent of the fit: 22–31 August 2024, 10 paired days.
- There are no missing pairs.

## Calculation

The coefficient, fitted only on the first part of the month: **0.3342303670**.
The estimate of the index on the MODIS scale = VIIRS index × coefficient.
This is a fractional calculated index, not the actually detected number of cells.

## Check on 22–31 August

| Variant | MAE | RMSE | Mean bias | R² |
|---|---:|---:|---:|---:|
| Raw VIIRS | 223.30 | 235.14 | 223.30 | -30.191 |
| VIIRS with the scale correction | 34.52 | 41.80 | -12.38 | 0.014 |
| Mean of MODIS over the training period | 46.64 | 59.43 | -41.94 | -0.992 |

MAE shows the mean absolute discrepancy from MODIS in units of the daily index.
Lower is closer to the chosen reference. MODIS is not the true number of fires.
The mean bias is computed as estimate minus MODIS: a negative value means an underestimate.

The candidate met the criterion set in advance: its MAE is lower than raw VIIRS and than the
constant mean computed on the training dates. The status of the experiment:
`improved_on_holdout`. The low R² shows that the agreement of the day-to-day fluctuations is weak.

## Practical use

The source series remain separate. The correction is not applied automatically to other
regions, seasons, platforms or separate map points. `apply_automatically=false`.
Ten adjacent days of one month do not prove the transferability of the method.
The next scientific check requires another period that was not used in the fit.

The code passed 52 checks. The coefficient and the MAE/RMSE/bias were separately cross-checked with an independent
calculation using a standard statistical function. The source database was not changed.

The full parameters, the raw daily values and the checksums of the slices are in the neighboring
JSON file `calibration-ukraine-bbox-2024-08.json`. The method is described in `CALIBRATION_METHOD.md`.
