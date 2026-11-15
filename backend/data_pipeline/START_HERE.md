# Current stage: a calendar from real data

Working folder: `/Users/andrejkot/Downloads/projectHackaton/data_pipeline`.

- The code that fetches NASA data and reads the database: `fires_data/`.
- Local settings: `.env`.
- The database: `var/fires.sqlite3`.
- Description for Sasha: the repository `README.md` (section "Data pipeline package") and `LIVE_STATUS.md`.

The API has been verified. The database holds 4 893 436 raw observations. August 2024 is fully loaded
for the whole world for MODIS and VIIRS NOAA-20: 31 days for each source.

## Look at the database

Run the commands from the `data_pipeline` folder:

```bash
python3 -m fires_data status
```

## Get the daily calendar indicators

```bash
python3 -m fires_data calendar --scope world --from 2024-08-01 --to 2024-08-31
```

The command reads the local database and outputs JSON. For a rectangular area:

```bash
python3 -m fires_data calendar --scope world --from 2024-08-01 --to 2024-08-31 --bbox 22 44 41 53
```

The result shows MODIS and VIIRS separately: how many observations were received and
how many cells of the common grid were active in each UTC day. The rectangle is
an approximate area, not the exact outline of a country. The method is described in `GRID_METHOD.md`.

The sum of active cells over days is called cell-days. This is not the number of separate
fires. The base calendar remains uncalibrated. A separate experiment on the correction
and its limited check are run with the command below.

## Check the experimental correction

```bash
python3 -m fires_data calibrate --scope world --from 2024-08-01 --to 2024-08-31 --split 2024-08-22 --bbox 22 44 41 53
```

The command fits a scale correction on 1–21 August and checks it on 22–31 August.
The correction is separate, and the source series are kept. The conditions are described in
`CALIBRATION_METHOD.md`; the result is not applied automatically to all territories.

## Next stage

The `grid_calendar` function is available to Sasha for connecting to FastAPI. Reading map points
and raw daily counts is already in the Store. Sasha connects the public HTTP methods.

Multi-year seasonality and a historical norm need further loading of history.
The loader saves progress; its commands are in the repository README.md. The automatic
update scheduler and fetching missing periods from HTTP are not connected yet.
