# Harmonization

VIIRS detects smaller and cooler fires than MODIS, so on the same day it reports many more active cells.
For August 2024 worldwide, MODIS (Terra + Aqua) reported about 0.77 million detections and VIIRS (NOAA-20) about
3.53 million. That gap comes from the observing system (resolution of about 1 km for MODIS and 375 m for VIIRS,
sensitivity and overpass timing), not from more fire on the ground.
The two series cannot be compared directly. Harmonization estimates how to express VIIRS in "MODIS units"
and, just as importantly, **checks honestly whether that works**.

!!! info "Status"
    This is an experimental method chosen for the prototype. It is **not** a NASA-published standard.
    The result is never applied automatically (`apply_automatically` is `false`), and the raw series always
    stay available next to the harmonized one.

## The model

For each day, let `x` be the VIIRS NOAA-20 active-cell count and `y` the MODIS (Terra + Aqua) count. The model
is a single scale factor with no intercept:

```text
y ≈ k × x          k = max(0, Σ(x·y) / Σ(x²))
```

MODIS is the *reference for comparison*, not the truth. A difference between the instruments does not mean
that extra VIIRS detections are errors.

## Train and test split

The factor `k` is fitted **only** on days before `split_date`. Days from `split_date` onward are held out and
never influence `k`. The split is chronological, because neighbouring days are correlated and a random split
would be over-optimistic.

- You can set `split_date` explicitly.
- Otherwise the first two thirds of the period are for training and the last third is for testing
  (`analytics.default_split`). For 1-31 August this is a 21-day training period and a 10-day test period,
  with 22 August as the first test day.

Only days where **both** series are loaded form a pair. Genuine zeros are kept; missing days are excluded from
the pairs but are reported.

## Three candidates are compared

On the held-out days the method compares, using predefined candidates and without tuning anything after
looking at the test result:

1. Raw VIIRS with no scaling.
2. VIIRS multiplied by `k`.
3. A constant: the training-period mean of MODIS.

Metrics are **MAE**, **RMSE** and **bias** (estimate minus MODIS), reported separately for train and test.
**R²** is reported when the reference has variation and is absent otherwise.

## Status values

| `status` | Meaning |
|---|---|
| `improved_on_holdout` | The scaled VIIRS has a lower test MAE than **both** raw VIIRS and the constant baseline. |
| `not_improved` | That criterion was not met. |
| `insufficient_data` | Fewer than 14 training pairs or 7 test pairs, or no signal or variation in the training series. No coefficient or metrics are produced. |

The minimum pair counts are engineering safeguards for the prototype, not a guarantee of statistical reliability.

## The `series` field

`/harmonization` also returns one combined series in MODIS units. Per day:

| Condition | `harmonized` | `harmonized_source` |
|---|---|---|
| MODIS is available | the MODIS value | `MODIS` |
| Only VIIRS is available | `k × VIIRS` | `VIIRS_NOAA20 x k` |
| Neither | `null` | `null` |

Each point is also labeled `train` or `test`, so a chart can show which part of the line the model has
actually been validated on.

## Reading the headline numbers

For the reference experiment (Ukraine rectangle `22,44,41,53`, August 2024, 21 days training, 10 days test):

| Quantity | Value |
|---|---|
| Coefficient `k` | 0.3342 |
| Test MAE, raw VIIRS | 223.30 |
| Test MAE, scaled VIIRS | 34.52 |
| Test MAE, constant training mean | 46.64 |
| Test R² | 0.0143 |

The scale factor removes most of the *level* difference, but the R² is close to zero. In other words, `k × VIIRS`
gets the average right and does **not** explain day-to-day variation well on this short sample. The status
`improved_on_holdout` refers only to this short experiment.

!!! warning "Limits of the evidence"
    Ten adjacent days of one August do not show that `k` transfers to other months, years, regions or
    seasons. The VIIRS/MODIS ratio may well differ between them, and this has not been tested. More independent
    periods must be loaded before treating `k` as general. `k` is also fitted per request, so it differs between regions.

## Anomalies

`/anomaly` compares one month with the same calendar month in earlier years, using a chosen series.

- Only months with `complete` data are used, so partial months are never compared.
- It needs at least **3** earlier years with complete data (`MIN_HISTORY_YEARS`). Otherwise the status is
  `insufficient_history`.
- The "normal" is the **median** of those earlier years.
- `anomaly_percent = (value - median) / median × 100`.
- Verdict: `above_normal` at +25% or more, `below_normal` at -25% or less, otherwise `normal`.
- `rank` is the position of the month among the requested year and the earlier years (1 = most active).

With the 2000–2025 archive imported (MODIS from 2000, VIIRS NOAA-20 from 2018), `/anomaly` has enough history
for most regions and months. If the database is incomplete it answers `insufficient_history`; see
[Archive import and NASA updates](../pipeline/archive-and-updates.md).
