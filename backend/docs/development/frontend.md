# Frontend

The website lives in `fire-calendar/` (repository root, next to `backend/`). It is a Next.js application for the
NASA Space Apps Challenge 2026: a harmonized MODIS + VIIRS burning-activity calendar.

!!! warning "Integration status"
    The frontend is currently written against a **different API contract** from the one the FastAPI backend
    serves. It runs on built-in mock data until a backend address is configured. See
    [Connecting the backend](#connecting-the-backend) for the exact differences and a suggested mapping.

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

```text
# fire-calendar/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Restart `npm run dev` after changing it. Remember to add the frontend's address to the backend's `FRONTEND_URLS`
(default `http://localhost:3000`), otherwise the browser blocks the requests with a CORS error.

### The contract mismatch

The frontend's `lib/api.ts` and `types/api.ts` were written for a Django-style API. Their own comments mention
Django and an `API.md` that is not in the repository. The backend that was actually built is FastAPI with
different paths and shapes:

| Frontend calls | Backend equivalent | Notes |
|---|---|---|
| `GET /api/meta/` | [`/regions`](../api/endpoints.md#get-regions) and [`/status`](../api/endpoints.md#get-status) | Explorer does not call `meta()`; it uses `REGIONS` and `YEARS` from `mock.ts`. |
| `GET /api/calendar/?region=` | [`/calendar/monthly`](../api/endpoints.md#get-calendarmonthly) (+ [`/anomaly`](../api/endpoints.md#get-anomaly) for the median) | Frontend expects `years[].months[12]`, a `median[12]` and a `harmonization` block. |
| `GET /api/month/?region&year&month` | [`/calendar`](../api/endpoints.md#get-calendar) with that month's `date_from`/`date_to`, and [`/harmonization`](../api/endpoints.md#get-harmonization) for the merged series | Frontend expects `days[]` of `{date, modis, viirs, harmonized}`. |
| `GET /api/monthly/?region&year` | [`/calendar/monthly`](../api/endpoints.md#get-calendarmonthly) for that year | Frontend expects `months[]` of `{month, modis, viirs}`. |
| `GET /api/hotspots/?region&year&month` | [`/cells`](../api/endpoints.md#get-cells) for a month, or [`/points`](../api/endpoints.md#get-points) (maximum 7 days) | See the notes below. |
| `GET /api/export/?region&year&month` | [`/export.csv`](../api/endpoints.md#get-exportcsv) | A month fits in the 31-day limit. `exportUrl` exists but the Explorer currently builds the CSV client-side. |

Differences to handle in an adapter layer inside `lib/api.ts`:

- **Paths.** The backend has no `/api` prefix and no trailing slashes.
- **Region ids and bbox order.** Frontend `Region.bbox` is `[south, west, north, east]`; the backend uses
  `[west, south, east, north]`. Regions should be loaded from `/regions` instead of `mock.ts`.
- **Months to dates.** The frontend passes `year` and `month`; the backend takes `date_from` and `date_to`.
- **Hotspots.** `/points` is limited to 7 days and `seenBy: "BOTH"` cannot be derived for a single detection
  (see [Data model](../pipeline/data-model.md#reading-from-python)). For a whole month the practical source is the
  `/cells` layer, whose properties carry MODIS and VIIRS counts per cell.
- **`null` semantics.** Both sides use `null` for "not loaded" and `0` for "loaded, nothing detected". Keep that
  distinction in charts so missing months do not look like quiet months.
- **Years.** The UI offers a fixed range (the year calendar is titled "2001–2025"), while the loaded data covers
  far less. Derive the available years from `/status` or the `coverage` fields.

Matching the frontend types to the backend's JSON shapes (or the reverse) is the main remaining integration task.

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
- `fire-calendar/README.md` mentions copying `.env.example`, but no such file is in the tree. Create `.env.local`
  by hand as shown above.
- The base map tiles come from Esri's ArcGIS tile service (`server.arcgisonline.com`); check its terms of use before
  a public launch.
