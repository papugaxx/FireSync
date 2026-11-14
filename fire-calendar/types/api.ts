// API response types. Agreement with the backend (Django), see API.md.
// null = "no data" (the instrument was not working), 0 = data exists, no fires.

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

/** "Year × month" heatmap: harmonized active cells. */
export interface CalendarYear {
  year: number;
  /** 12 values, January..December */
  months: (number | null)[];
}

export interface CalendarResponse {
  region: string;
  years: CalendarYear[];
  /** median for each month across all years */
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
  /** which instrument saw this cell */
  seenBy: "MODIS" | "VIIRS" | "BOTH";
  frp: number;
}

export interface HotspotsResponse {
  region: string;
  from: string;
  to: string;
  hotspots: Hotspot[];
}

/** "Activity by month" chart: both lines on one scale (VIIRS is already harmonized). */
export interface MonthlyResponse {
  region: string;
  year: number;
  months: {
    month: number;
    modis: number | null;
    viirs: number | null;
    /** area of cells with active fire, km² (sum over days) */
    areaKm2: number | null;
    /** mean and maximum fire power, MW */
    frpMean: number | null;
    frpMax: number | null;
  }[];
}
