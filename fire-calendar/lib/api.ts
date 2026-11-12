// Единая точка доступа к данным.
// Пока NEXT_PUBLIC_API_URL не задан, отдаём моки. Когда бэкенд готов,
// достаточно прописать адрес в .env.local, компоненты менять не нужно.
import type {
  CalendarResponse,
  HotspotsResponse,
  MetaResponse,
  MonthResponse,
} from "@/types/api";
import { mockCalendar, mockHotspots, mockMeta, mockMonth } from "./mock";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

async function get<T>(path: string, fallback: () => T): Promise<T> {
  if (!API_URL) {
    await new Promise((r) => setTimeout(r, 250)); // имитация сети, чтобы видеть загрузку
    return fallback();
  }
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
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

  hotspots: (region: string, year: number, month: number) =>
    get<HotspotsResponse>(`/api/hotspots/?region=${region}&year=${year}&month=${month}`, () =>
      mockHotspots(region, year, month),
    ),

  /** ссылка на CSV; без бэкенда CSV собирается на клиенте (см. downloadCsv) */
  exportUrl: (region: string, year: number, month: number) =>
    API_URL ? `${API_URL}/api/export/?region=${region}&year=${year}&month=${month}` : null,
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
