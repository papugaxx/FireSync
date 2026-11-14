// Тестовые данные, пока нет реального API.
// Генерируются детерминированно (одинаковые при каждой перезагрузке).
import type {
  CalendarResponse,
  HotspotsResponse,
  MetaResponse,
  MonthlyResponse,
  MonthResponse,
  Region,
} from "@/types/api";

export const REGIONS: Region[] = [
  { id: "world", name: "World", bbox: [-58, -170, 75, 180] },
  { id: "ukraine", name: "Ukraine", bbox: [44.3, 22.1, 52.4, 40.2] },
  { id: "argentina", name: "Argentina", bbox: [-55.1, -73.6, -21.8, -53.6] },
  { id: "california", name: "California, USA", bbox: [32.5, -124.4, 42.0, -114.1] },
  { id: "amazonas", name: "Amazonas, Brazil", bbox: [-9.8, -73.8, 2.2, -56.1] },
];

export const YEARS = Array.from({ length: 25 }, (_, i) => 2001 + i); // 2001..2025

// Сезонность: в каком месяце пик пожаров (0 = январь) и его сила
const SEASON: Record<string, { peak: number; second?: number; scale: number }> = {
  world: { peak: 7, second: 1, scale: 60000 },
  ukraine: { peak: 7, second: 3, scale: 900 },
  argentina: { peak: 8, second: 0, scale: 1400 },
  california: { peak: 7, scale: 700 },
  amazonas: { peak: 8, scale: 2200 },
};

function rng(seed: number) {
  // mulberry32
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(s: string) {
  let h = 2166136261;
  for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return h >>> 0;
}

function monthWeight(regionId: string, m: number) {
  const s = SEASON[regionId] ?? SEASON.ukraine;
  const d = (a: number, b: number) => Math.min(Math.abs(a - b), 12 - Math.abs(a - b));
  let w = Math.exp(-(d(m, s.peak) ** 2) / 3);
  if (s.second !== undefined) w += 0.6 * Math.exp(-(d(m, s.second) ** 2) / 1.5);
  return w * s.scale;
}

function median(xs: number[]) {
  const a = [...xs].sort((x, y) => x - y);
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
}

export function mockMeta(): MetaResponse {
  return { regions: REGIONS, years: YEARS };
}

export function mockCalendar(regionId: string): CalendarResponse {
  const r = rng(hash(regionId));
  const years = YEARS.map((year) => {
    const yearFactor = 0.5 + r() * 1.1 + (r() < 0.12 ? 1.2 : 0); // иногда аномальный год
    const months = Array.from({ length: 12 }, (_, m) => {
      // данных за будущие месяцы нет
      if (year === 2025 && m > 9) return null;
      return Math.round(monthWeight(regionId, m) * yearFactor * (0.6 + r() * 0.8));
    });
    return { year, months };
  });
  const med = Array.from({ length: 12 }, (_, m) =>
    Math.round(median(years.map((y) => y.months[m]).filter((v): v is number => v !== null))),
  );
  return {
    region: regionId,
    years,
    median: med,
    harmonization: { method: "linear (VIIRS → MODIS scale)", status: "draft", r2: 0.87 },
  };
}

export function mockMonth(regionId: string, year: number, month: number): MonthResponse {
  const r = rng(hash(`${regionId}-${year}-${month}`));
  const daysInMonth = new Date(year, month, 0).getDate();
  const base = monthWeight(regionId, month - 1) / 30;
  const days = Array.from({ length: daysInMonth }, (_, i) => {
    const date = `${year}-${String(month).padStart(2, "0")}-${String(i + 1).padStart(2, "0")}`;
    const missing = r() < 0.03;
    const burst = r() < 0.1 ? 3 : 1;
    const modis = missing ? null : Math.round(base * burst * r() * 2);
    const viirs = year < 2012 ? null : Math.round((modis ?? base) * (2.2 + r()));
    const harmonized = modis ?? (viirs !== null ? Math.round(viirs / 2.6) : null);
    return { date, modis, viirs, harmonized };
  });
  return { region: regionId, year, month, days };
}

export function mockHotspots(regionId: string, year: number, month: number): HotspotsResponse {
  const region = REGIONS.find((x) => x.id === regionId) ?? REGIONS[0];
  const [s, w, n, e] = region.bbox;
  const r = rng(hash(`hs-${regionId}-${year}-${month}`));
  const isWorld = regionId === "world";
  const count = isWorld ? 2500 : Math.min(400, Math.round(monthWeight(regionId, month - 1) / 6) + 20);
  // пожары кучкуются: несколько центров, вокруг них точки
  const centers = isWorld
    ? WORLD_FIRE_BELTS
    : Array.from({ length: 6 }, () => [s + r() * (n - s), w + r() * (e - w)]);
  const spread = isWorld ? [6, 9] : [(n - s) * 0.15, (e - w) * 0.15];
  const hotspots = Array.from({ length: count }, (_, i) => {
    const [clat, clon] = centers[Math.floor(r() * centers.length)];
    const roll = r();
    return {
      id: `${regionId}-${i}`,
      lat: clat + (r() - 0.5) * spread[0] * (isWorld ? r() * 2 : 1),
      lon: clon + (r() - 0.5) * spread[1] * (isWorld ? r() * 2 : 1),
      date: `${year}-${String(month).padStart(2, "0")}-${String(1 + Math.floor(r() * 28)).padStart(2, "0")}`,
      seenBy: (year < 2012 ? "MODIS" : roll < 0.15 ? "MODIS" : roll < 0.6 ? "VIIRS" : "BOTH") as
        | "MODIS"
        | "VIIRS"
        | "BOTH",
      frp: Math.round(5 + r() * 120),
    };
  });
  return { region: regionId, from: `${year}-${month}-01`, to: `${year}-${month}-28`, hotspots };
}

// Примерные центры пожарных поясов планеты (только для мок-карты мира)
const WORLD_FIRE_BELTS: number[][] = [
  [10, -5], [9, 10], [8, 22], [6, 30], [-12, 25], [-15, 35], [-20, 30], [-19, 47],
  [-8, -50], [-12, -45], [-18, -55], [-5, -62], [-28, -60], [5, -72],
  [22, 80], [18, 77], [15, 100], [12, 105], [-2, 113], [50, 128], [55, 95],
  [35, -85], [33, -95], [40, -120], [55, -115], [48, 35], [52, 55],
  [-25, 135], [-15, 130], [-32, 145], [38, 0], [42, 20],
];

export function mockMonthly(regionId: string, year: number): MonthlyResponse {
  const cal = mockCalendar(regionId);
  const row = cal.years.find((y) => y.year === year) ?? cal.years[cal.years.length - 1];
  const r = rng(hash(`monthly-${regionId}-${year}`));
  return {
    region: regionId,
    year,
    months: row.months.map((v, i) => ({
      month: i + 1,
      modis: v,
      // VIIRS после гармонизации близок к MODIS; до 2012 года VIIRS ещё не летал
      viirs: v === null || year < 2012 ? null : Math.round(v * (0.85 + r() * 0.3)),
    })),
  };
}
