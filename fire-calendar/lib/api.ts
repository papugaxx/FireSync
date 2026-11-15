// Single point of access to data.
// NEXT_PUBLIC_API_URL is the FastAPI backend (backend/frontend_api.py), e.g. http://127.0.0.1:8000.
// `python run.py` in the repository root sets it automatically; for `npm run dev` alone copy
// .env.example to .env.local. While it is empty, the site shows the demo data from lib/mock.ts.
import type {
  BoundaryResponse,
  CalendarResponse,
  HotspotsResponse,
  MetaResponse,
  MonthlyResponse,
  MonthResponse,
  PointsResponse,
  SyncResponse,
} from "@/types/api";
import type { Hotspot } from "@/types/api";
import { mockCalendar, mockHotspots, mockMeta, mockMonth, mockMonthly, mockPoints } from "./mock";

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

  hotspots: (region: string, year: number, month: number) =>
    get<HotspotsResponse>(`/api/hotspots/?region=${region}&year=${year}&month=${month}`, () =>
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

  /** The border the region is counted by (null without a backend: the map draws the rectangle). */
  boundary: (region: string) => get<BoundaryResponse | null>(`/api/boundary/?region=${region}`, () => null),

  /** Which dates are loaded / still downloading (null without a backend). */
  sync: () => get<SyncResponse | null>("/api/sync/", () => null),

  /** link to the CSV; without a backend the CSV is built on the client (see downloadCsv) */
  exportUrl: (region: string, year: number, month: number, day?: string | null, sensor?: "MODIS" | "VIIRS") =>
    API_URL
      ? `${API_URL}/api/export/?region=${region}&year=${year}&month=${month}${day ? `&day=${day}` : ""}${sensor ? `&sensor=${sensor}` : ""}`
      : null,
};

export function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const head = Object.keys(rows[0]);
  const csv = [head.join(","), ...rows.map((r) => head.map((h) => r[h] ?? "").join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}
