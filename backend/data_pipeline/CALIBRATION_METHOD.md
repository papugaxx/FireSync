# Experiment on reconciling the daily indices

## Goal

To test a simple scale correction that brings the daily VIIRS NOAA-20 index closer to the
chosen MODIS Terra+Aqua index for one area and period.
MODIS here is a reference for comparison, not the true number of fires. The differences between the instruments
do not mean that the additional VIIRS detections are errors.

## Input data

The result of `grid_calendar`: one fixed 0.1° grid, UTC days, unchanged
platforms and filters. Only days where both sources are loaded are used.
Real zeros are kept; missing days are excluded from the pairs but are marked.
The report keeps the profile, bbox, dates and versions of the input slices.

The first planned run: bbox (22,44,41,53), 1–31 August 2024.
This is a rectangular area around Ukraine, not an administrative border.

## The method is fixed before evaluation

The first 21 days, 1–21 August, are used to fit the coefficient.
The last 10 days, 22–31 August, are held out for checking and do not take part in the fit.
The border is set by the parameter `--split 2024-08-22`.

Let x be the daily VIIRS index and y the daily MODIS index.
The candidate: y_estimate = a × x, where a = max(0, sum(x×y) / sum(x²)).
The intercept is zero. The coefficient is computed only on the training pairs.
The output can be fractional: it is an estimate of the index on the MODIS scale, not the actually
detected number of cells and not a value for separate map points.

## Checking

On the training part and, separately, on the held-out part we compute MAE, RMSE and the mean
bias (estimate minus MODIS). R² is absent if the variation of the reference is zero.

We compare three variants chosen in advance:

- Raw VIIRS without scaling.
- VIIRS with the coefficient a.
- The constant mean of MODIS, computed only on the training dates.

The correction gets `improved_on_holdout` only if its MAE on the held-out dates
is lower than both comparison variants, allowing for numeric tolerance.
Otherwise — `not_improved`. The parameters are not changed after looking at the check.

With fewer than 14 training or 7 held-out pairs, or with no signal/variability
in the training series, `insufficient_data` is returned. These minimums are engineering
safeguards of the prototype, not a guarantee of statistical reliability.

## How to use the result

The result is always experimental: `apply_automatically=false`.
It does not replace the source series and is not applied automatically to other territories,
satellites or seasons. An improvement on 10 adjacent days of one August does not prove
transferability to another month or year. Adjacent days may be dependent.
A historical norm, anomalies and a combined multi-year series are not built here.
The next check will need other periods that were not used in the fit.

## Sources of the limitations

[NASA FIRMS Important Notes](https://firms.modaps.eosdis.nasa.gov/alerts/notes.php)
explains the differences in sensitivity, the experimental nature of MODIS confidence and possible
missed detections. The candidate itself, the 21/10 split and the acceptance criterion are our
transparent experiment; this is not a harmonization standard published by NASA.
