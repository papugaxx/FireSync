# Frontend

The website lives in `fire-calendar/` (repository root, next to `backend/`). It is a Next.js application for the
NASA Space Apps Challenge 2026: a harmonized MODIS + VIIRS burning-activity calendar.

!!! note "Integration status"
    The backend serves exactly the `/api/...` addresses and shapes that `lib/api.ts` and `types/api.ts` expect
    (`frontend_api.py`). The frontend runs on built-in mock data until `NEXT_PUBLIC_API_URL` is set; after that
    every number comes from the database. See [Connecting the backend](#connecting-the-backend).

## Stack

| Piece | Version (from `package.json`) |
|---|---|
| Next.js | 16.4.6 (App Router) |
| React | 19.3.0 |
| TypeScript | 5.9.3 |
| Tailwind CSS | 4.3.3 |
| Leaflet | 1.9.4, used directly (not through `react-leaflet`) |

!!! note "Next.js has breaking changes"
    `fire-calendar/AGENTS.md` warns that this Next.js version differs from older releases. Read the guides in
    `node_modules/next/dist/docs/` before changing framework-level code.

## Run it

```bash
cd fire-calendar
npm install
npm run dev
```

| URL | Page |
|---|---|
| <http://localhost:3000> | Landing page |
| <http://localhost:3000/explore> | The calendar explorer (the main application) |

Other scripts: `npm run build`, `npm start` and `npm run lint`.

## Structure

```text
fire-calendar/
├── app/
│   ├── page.tsx              landing page
│   ├── explore/page.tsx      calendar page (renders Explorer)
│   ├── layout.tsx
│   └── globals.css           colors and fonts (the @theme block)
├── components/
│   ├── ui/index.tsx          Section, Card, Panel, Button, Select, Field, Toggle, Stat, Placeholder
│   ├── layout/               Header, Footer
│   └── explore/              Explorer (page logic), YearCalendar, DayCalendar, DayStrip,
│                             ActivityChart, MonthlyChart, FireMap, RampLegend, SensorLegend
├── lib/
│   ├── api.ts                the single place that talks to the API (or returns mocks)
│   ├── useApi.ts             data-loading hook
│   ├── mock.ts               test data, regions and years
│   ├── colors.ts             color scales for data (calendar, map)
│   └── site.ts               site name and tagline
└── types/api.ts              TypeScript types of the API responses
```

### How the Explorer page works

`components/explore/Explorer.tsx` holds the page state (region, year, month, selected day, which sensors are
shown, `count` or `anomaly` mode) and requests four datasets through `useApi`:

| Call in `lib/api.ts` | Used for |
|---|---|
| `api.calendar(region)` | The year × month heatmap (`YearCalendar`) |
| `api.month(region, year, month)` | The day-by-day calendar panel (`DayCalendar`) |
| `api.hotspots(region, year, month)` | Points on the map. Selecting a day filters them client-side |
| `api.monthly(region, year)` | The monthly activity chart (`ActivityChart`) |

The map (`FireMap`) is built on plain Leaflet and loaded with `next/dynamic` and `ssr: false`. It is created when
the page appears and removed when it leaves, because `react-leaflet` crashed when returning to a kept-alive page in
Next.js 16. The CSV button builds a file **in the browser** from the hotspots currently shown.

`useApi(key, load)` reloads whenever `key` changes and returns `data` or `error`; while a new key is loading,
`data` is `undefined` and the UI shows a placeholder.

## Connecting the backend

`lib/api.ts` reads `NEXT_PUBLIC_API_URL`. While it is empty, every call returns data from `lib/mock.ts` after a
short simulated delay. Once it is set, requests go to that address and the components do not change.

- **Everything at once:** `python3 run.py` in the repository root starts the API and the website and sets the
  variable itself.
- **Only the website:** `cp .env.example .env.local` (it contains `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`),
  then `npm run dev`. Restart it after changing the file.
- **Server:** the address is built into the site at build time:
  `NEXT_PUBLIC_API_URL=https://YOUR-DOMAIN npm run build` (done by `backend/deploy/setup_server.sh`).

The Explorer takes its regions and years from `/api/meta/` (the demo lists in `mock.ts` are used only without a
backend), so newly downloaded years appear by themselves. Remember to add the frontend's address to the backend's `FRONTEND_URLS`
(default `http://localhost:3000`), otherwise the browser blocks the requests with a CORS error.

### What the backend answers

| Frontend calls | Answer |
|---|---|
| `GET /api/meta/` | All regions of `config.REGIONS` (bbox in the frontend's `[south, west, north, east]` order) and the years that have data. The Explorer still uses `REGIONS`/`YEARS` from `mock.ts`; the five ids there exist in the backend with the same rectangles. |
| `GET /api/calendar/?region=` | `years[].months[12]`: active cell-days per **complete** month on the MODIS scale (`null` = missing or incomplete), `median[12]` (needs 3 complete years, else `null`), and `harmonization` with the real fitted `k`, `r2`, fit and holdout periods. |
| `GET /api/month/?region&year&month` | `days[]` of `{date, modis, viirs, harmonized}`: observed active cells per sensor (VIIRS = NOAA-20, unscaled) and the MODIS-scale value. `null` = no data, `0` = observed, no fire. |
| `GET /api/monthly/?region&year` | `months[]` of `{month, modis, viirs, areaKm2, frpMean, frpMax}` for complete months. `viirs` is NOAA-20 × `k` (MODIS scale), `viirs_raw` the observed value; `areaKm2` is the area of the distinct MODIS cells (latitude-corrected, not burned area). |
| `GET /api/hotspots/?region&year&month` | One point per active 0.1° cell and day with the real date, `seenBy` (`MODIS`, `VIIRS` or `BOTH`) and `frp` (strongest detection, MW). Up to 10 000; above that the strongest cells of every day are kept and `truncated`/`total` say so. |
| `GET /api/export/?region&year&month` | A CSV of the individual detections (optional `day`, `sensor`). |

Extra fields (coverage, units, products, raw values) are added next to the expected ones; the frontend ignores them.

## Styling

There are no finished styles yet, only layout and placeholder frames. Where to change things:

1. Colors and fonts: the `@theme` block in `app/globals.css`.
2. Buttons, cards, inputs: `components/ui/index.tsx` (used by every page).
3. Header and footer: `components/layout/`.
4. Data colors (heat scale, MODIS and VIIRS colors): `lib/colors.ts`.
5. Places marked `TODO` in the code are waiting for content from the design (logo, hero image, team).

## Housekeeping notes

- The repository root has its own `package.json` listing `react-leaflet` and `geist`, which `fire-calendar` does
  not use (the map uses plain Leaflet). It looks like a stray install and can probably be removed.
- The yearly total in the trend chart counts only years whose 12 months are all complete, so a partial year is not
  shown as a quiet year.
- The base map tiles come from Esri's ArcGIS tile service (`server.arcgisonline.com`); check its terms of use before
  a public launch.
