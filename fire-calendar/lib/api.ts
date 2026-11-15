// Single point of access to data.
// NEXT_PUBLIC_API_URL is the FastAPI backend (backend/frontend_api.py), e.g. http://127.0.0.1:8000.
// `python run.py` in the repository root sets it automatically; for `npm run dev` alone copy
// .env.example to .env.local. While it is empty, the site shows the demo data from lib/mock.ts.
import type {
  AreaQuery,
  BoundaryResponse,
  CalendarResponse,
  HotspotsResponse,
  MetaResponse,
  MonthlyResponse,
  MonthResponse,
  PointsResponse,
  RangeCellsResponse,
  RangeReport,
  SyncResponse,
} from "@/types/api";
import type { Hotspot } from "@/types/api";
import { mockCalendar, mockHotspots, mockMeta, mockMonth, mockMonthly, mockPoints, mockRangeCells, mockRangeReport } from "./mock";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
export const USING_DEMO_DATA = !API_URL;

async function get<T>(path: string, fallback: () => T): Promise<T> {
  if (!API_URL) {
    await new Promise((r) => setTimeout(r, 250)); // simulated network delay so the loading state is visible
    return fallback();
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new Error(`the backend at ${API_URL} is not reachable. Is it running?`);
  }
  if (!res.ok) {
    // the backend always answers errors as {"error": "readable text"}
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.error === "string" ? body.error : `API ${res.status}: ${path}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<MetaResponse>("/api/meta/", mockMeta),

  calendar: (region: string) =>
    get<CalendarResponse>(`/api/calendar/?region=${region}`, () => mockCalendar(region)),

  month: (region: string, year: number, month: number) =>
    get<MonthResponse>(`/api/month/?region=${region}&year=${year}&month=${month}`, () =>
      mockMonth(region, year, month),
    ),

  monthly: (region: string, year: number) =>
    get<MonthlyResponse>(`/api/monthly/?region=${region}&year=${year}`, () => mockMonthly(region, year)),

  /** `day` given → the server returns THAT day (the month list may be cut to the strongest cell-days). */
  hotspots: (region: string, year: number, month: number, day?: string | null) =>
    get<HotspotsResponse>(`/api/hotspots/?region=${region}&year=${year}&month=${month}${day ? `&day=${day}` : ""}`, () =>
      mockHotspots(region, year, month),
    ),

  /**
   * The real NASA detections inside one 0.1° map cell on one day (backend `/api/detections/`),
   * only those inside the region's border. Their coordinates are the detections themselves.
   */
  cellPoints: (region: string, cell: Hotspot, sensor?: "MODIS" | "VIIRS") => {
    const q = new URLSearchParams({ region, date: cell.date, cell: String(cell.cell ?? ""), limit: "500" });
    if (sensor) q.set("sensor", sensor);
    return get<PointsResponse>(`/api/detections/?${q}`, () => mockPoints(cell.lat, cell.lon, cell.date, sensor));
  },

  /**
   * Individual detections inside one 0.1° cell over a PERIOD (the "Area & dates" map). The backend's
   * root `/points` gives at most 7 days per request, so the period is asked for in 7-day pieces
   * (in parallel; a 0.1° cell is small, so each piece is quick) and joined, oldest first.
   */
  cellRangePoints: async (lat: number, lon: number, from: string, to: string, sensor?: "MODIS" | "VIIRS"): Promise<PointsResponse> => {
    const pieces: [string, string][] = [];
    for (let t = Date.parse(from); t <= Date.parse(to); t += 7 * 86_400_000) {
      const end = Math.min(t + 6 * 86_400_000, Date.parse(to));
      pieces.push([new Date(t).toISOString().slice(0, 10), new Date(end).toISOString().slice(0, 10)]);
    }
    const h = 0.0499; // just inside the cell, so the neighbours sharing its edges are not included
    const box = `west=${(lon - h).toFixed(4)}&south=${(lat - h).toFixed(4)}&east=${(lon + h).toFixed(4)}&north=${(lat + h).toFixed(4)}`;
    const parts = await Promise.all(
      pieces.map(([a, b]) =>
        get<PointsResponse>(`/points?${box}&date_from=${a}&date_to=${b}&limit=500${sensor ? `&sensor=${sensor}` : ""}`, () =>
          mockPoints(lat, lon, a, sensor),
        ),
      ),
    );
    const points = parts
      .flatMap((p) => p.points)
      .sort((x, y) => (x.acq_date + x.acq_time).localeCompare(y.acq_date + y.acq_time));
    return { count: points.length, has_more: parts.some((p) => p.has_more), points };
  },

  /** The border the region is counted by (null without a backend: the map draws the rectangle). */
  boundary: (region: string) => get<BoundaryResponse | null>(`/api/boundary/?region=${region}`, () => null),

  /** Which dates are loaded / still downloading (null without a backend). */
  sync: () => get<SyncResponse | null>("/api/sync/", () => null),

  /** link to the CSV; without a backend the CSV is built on the client (see downloadCsv) */
  exportUrl: (region: string, year: number, month: number, day?: string | null, sensor?: "MODIS" | "VIIRS") =>
    API_URL
      ? `${API_URL}/api/export/?region=${region}&year=${year}&month=${month}${day ? `&day=${day}` : ""}${sensor ? `&sensor=${sensor}` : ""}`
      : null,

  /**
   * Daily MODIS / VIIRS activity of a region or an own rectangle over any period (backend root `/calendar`).
   * Limits set by the backend: a region up to 3660 days, an own rectangle up to 366 days.
   */
  rangeReport: (area: AreaQuery, from: string, to: string) =>
    get<RangeReport>(`/calendar?${areaParams(area)}&date_from=${from}&date_to=${to}`, () => mockRangeReport(area, from, to)),

  /** Active 0.1° cells of an area over a period, for the map (backend root `/cells`, up to 92 days). */
  rangeCells: (area: AreaQuery, from: string, to: string) =>
    get<RangeCellsResponse>(`/cells?${areaParams(area)}&date_from=${from}&date_to=${to}&resolution=0.1`, () =>
      mockRangeCells(area, from, to),
    ),

  /** Link to the CSV of every detection of an area and period (backend `/export.csv`, up to 31 days). */
  exportRangeUrl: (area: AreaQuery, from: string, to: string, sensor?: "MODIS" | "VIIRS") =>
    API_URL
      ? `${API_URL}/export.csv?${areaParams(area)}&date_from=${from}&date_to=${to}${sensor ? `&sensor=${sensor}` : ""}`
      : null,
};

/** Area as query parameters: `region=…` or `west=…&south=…&east=…&north=…`. */
function areaParams(area: AreaQuery) {
  if ("region" in area) return `region=${encodeURIComponent(area.region)}`;
  const [w, s, e, n] = area.bbox;
  return `west=${w}&south=${s}&east=${e}&north=${n}`;
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const head = Object.keys(rows[0]);
  const csv = [head.join(","), ...rows.map((r) => head.map((h) => r[h] ?? "").join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}
