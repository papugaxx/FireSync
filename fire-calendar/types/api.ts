// Типы ответов API. Договорённость с бэкендом (Django), см. API.md.
// null = "нет данных" (прибор не работал), 0 = данные есть, пожаров нет.

export type Sensor = "MODIS" | "VIIRS";

export interface Region {
  id: string;
  name: string;
  /** [south, west, north, east] */
  bbox: [number, number, number, number];
}

export interface MetaResponse {
  regions: Region[];
  years: number[];
}

/** Тепловая карта "год × месяц": гармонизированные активные ячейки. */
export interface CalendarYear {
  year: number;
  /** 12 значений, январь..декабрь */
  months: (number | null)[];
}

export interface CalendarResponse {
  region: string;
  years: CalendarYear[];
  /** медиана по каждому месяцу за все годы */
  median: number[];
  harmonization: {
    method: string;
    status: "validated" | "draft";
    r2: number;
  };
}

export interface DayValue {
  date: string; // YYYY-MM-DD
  modis: number | null;
  viirs: number | null;
  harmonized: number | null;
}

export interface MonthResponse {
  region: string;
  year: number;
  month: number;
  days: DayValue[];
}

export interface Hotspot {
  id: string;
  lat: number;
  lon: number;
  date: string;
  /** какой прибор видел эту ячейку */
  seenBy: "MODIS" | "VIIRS" | "BOTH";
  frp: number;
}

export interface HotspotsResponse {
  region: string;
  from: string;
  to: string;
  hotspots: Hotspot[];
}

/** График "активность по месяцам": обе линии в одной шкале (VIIRS уже гармонизирован). */
export interface MonthlyResponse {
  region: string;
  year: number;
  months: { month: number; modis: number | null; viirs: number | null }[];
}
