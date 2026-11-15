// Test data until a real API exists.
// Generated deterministically (identical on every reload).
import type {
  Detection,
  PointsResponse,
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

// 2000 … the current year (demo only; with a backend the years come from /api/meta/)
const NOW = new Date();
export const YEARS = Array.from({ length: NOW.getUTCFullYear() - 1999 }, (_, i) => 2000 + i);

/** Same coverage as the real database: MODIS from 1 Nov 2000, VIIRS NOAA-20 from 1 Apr 2018. */
export const MOCK_COVERAGE = {
  modis: { first_day: "2000-11-01", last_day: NOW.toISOString().slice(0, 10) },
  viirs: { first_day: "2018-04-01", last_day: NOW.toISOString().slice(0, 10) },
};

// Seasonality: which month is the fire peak (0 = January) and how strong it is
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
  return { regions: REGIONS, years: YEARS, data: MOCK_COVERAGE };
}

export function mockCalendar(regionId: string): CalendarResponse {
  const r = rng(hash(regionId));
  const years = YEARS.map((year) => {
    const yearFactor = 0.5 + r() * 1.1 + (r() < 0.12 ? 1.2 : 0); // occasionally an anomalous year
    const months = Array.from({ length: 12 }, (_, m) => {
      // there is no data for future months
      if (year > NOW.getUTCFullYear() || (year === NOW.getUTCFullYear() && m >= NOW.getUTCMonth())) return null;
      // and nothing before MODIS started (November 2000)
      if (year === 2000 && m < 10) return null;
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
    const missing = r() < 0.03 || date < MOCK_COVERAGE.modis.first_day;
    const burst = r() < 0.1 ? 3 : 1;
    const modis = missing ? null : Math.round(base * burst * r() * 2);
    const viirs = date < MOCK_COVERAGE.viirs.first_day ? null : Math.round((modis ?? base) * (2.2 + r()));
    const harmonized = modis ?? (viirs !== null ? Math.round(viirs / 2.6) : null);
    return { date, modis, viirs, harmonized, status: (missing ? "no_data" : "complete") as "no_data" | "complete" };
  });
  return { region: regionId, year, month, days };
}

export function mockHotspots(regionId: string, year: number, month: number): HotspotsResponse {
  const region = REGIONS.find((x) => x.id === regionId) ?? REGIONS[0];
  const [s, w, n, e] = region.bbox;
  const r = rng(hash(`hs-${regionId}-${year}-${month}`));
  const isWorld = regionId === "world";
  const count = isWorld ? 2500 : Math.min(400, Math.round(monthWeight(regionId, month - 1) / 6) + 20);
  // fires cluster: several centers, with points around them
  const centers = isWorld
    ? WORLD_FIRE_BELTS
    : Array.from({ length: 6 }, () => [s + r() * (n - s), w + r() * (e - w)]);
  const spread = isWorld ? [6, 9] : [(n - s) * 0.15, (e - w) * 0.15];
  const hotspots = Array.from({ length: count }, (_, i) => {
    const [clat, clon] = centers[Math.floor(r() * centers.length)];
    const roll = r();
    // like the backend: one point per 0.1° cell, placed at the cell centre
    const lat = cellCentre(clat + (r() - 0.5) * spread[0] * (isWorld ? r() * 2 : 1));
    const lon = cellCentre(clon + (r() - 0.5) * spread[1] * (isWorld ? r() * 2 : 1));
    return {
      id: `${regionId}-${i}`,
      kind: "cell" as const,
      lat,
      lon,
      date: `${year}-${String(month).padStart(2, "0")}-${String(1 + Math.floor(r() * 28)).padStart(2, "0")}`,
      seenBy: (year < 2018 ? "MODIS" : roll < 0.15 ? "MODIS" : roll < 0.6 ? "VIIRS" : "BOTH") as
        | "MODIS"
        | "VIIRS"
        | "BOTH",
      frp: Math.round(3 + r() ** 3 * 600), // most fires are weak, rare ones are very powerful
    };
  });
  return { region: regionId, from: `${year}-${month}-01`, to: `${year}-${month}-28`, hotspots };
}

// Approximate centers of the planet's fire belts (only for the mock world map)
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
      // VIIRS after harmonization is close to MODIS; VIIRS NOAA-20 data starts in April 2018
      viirs: v === null || year < 2018 ? null : Math.round(v * (0.85 + r() * 0.3)),
      // area: ~100 km² per 0.1° cell (at mid latitudes)
      areaKm2: v === null ? null : v * 100,
      frpMean: v === null ? null : Math.round(15 + r() * 25 + (v / 1000) * 3),
      frpMax: v === null ? null : Math.round(250 + r() * 900),
    })),
  };
}

/** Centre of the 0.1° cell that contains `v` (e.g. 46.23 → 46.25), same grid as the backend. */
function cellCentre(v: number) {
  return Math.round((Math.floor(v * 10) / 10 + 0.05) * 100) / 100;
}

/** Fake individual detections inside one cell (the backend answers this from NASA data). */
export function mockPoints(lat: number, lon: number, date: string, sensor?: "MODIS" | "VIIRS"): PointsResponse {
  const r = rng(hash(`pts-${lat}-${lon}-${date}`));
  const n = 1 + Math.floor(r() * 5);
  const points = Array.from({ length: n }, (): Detection => {
    const isModis = sensor ? sensor === "MODIS" : r() < 0.35;
    const hh = Math.floor(r() * 24), mm = Math.floor(r() * 60);
    return {
      acq_date: date,
      acq_time: `${String(hh).padStart(2, "0")}${String(mm).padStart(2, "0")}`,
      sensor: isModis ? "MODIS" : "VIIRS",
      satellite: isModis ? (r() < 0.5 ? "Terra" : "Aqua") : "NOAA-20",
      latitude: Math.round((lat - 0.05 + r() * 0.1) * 1e5) / 1e5,
      longitude: Math.round((lon - 0.05 + r() * 0.1) * 1e5) / 1e5,
      frp_mw: Math.round((2 + r() ** 2 * 120) * 100) / 100,
      confidence: isModis ? String(Math.round(30 + r() * 70)) : ["l", "n", "h"][Math.floor(r() * 3)],
      daynight: hh >= 6 && hh < 18 ? "D" : "N",
    };
  }).sort((a, b) => a.acq_time.localeCompare(b.acq_time));
  return { count: points.length, has_more: false, points };
}
