// API response types. Agreement with the backend: backend/frontend_api.py (FastAPI).
// null = "no data" (not observed / month incomplete), 0 = data exists, no fires.
// The backend sends a few extra fields (coverage, units, raw values); only the ones used are typed here.

export type Sensor = "MODIS" | "VIIRS";

export interface Region {
  id: string;
  name: string;
  /** [south, west, north, east] — the view the map zooms to (not what is counted) */
  bbox: [number, number, number, number];
  /** how the region is counted: by its real border, a border cut by a rectangle, a rectangle, or the world */
  boundary?: { kind: "border" | "border_part" | "rectangle" | "world"; id?: string };
}

/**
 * Why a day has (or has no) value — so "no fires", "no observations" and "not downloaded yet"
 * are never confused:
 *  complete     every sensor that observed the day is loaded
 *  partial      one sensor loaded, the other still to come — or NASA is still adding passes (last days)
 *  pending      NASA has the day; FireSync has not downloaded it yet
 *  unavailable  NASA does not offer the day (yet)
 *  no_data      no satellite observations for that day
 *  not_imported archive years while the archive has not been imported
 *  future       the day has not happened yet
 */
export type DayStatus = "complete" | "partial" | "pending" | "unavailable" | "no_data" | "not_imported" | "future";

export interface MetaResponse {
  regions: Region[];
  years: number[];
  /** what the database holds per sensor ("modis", "viirs"): first and last stored UTC day */
  data?: Record<string, { first_day: string | null; last_day: string | null }>;
}

/** "Year × month" heatmap: harmonized active cells. */
export interface CalendarYear {
  year: number;
  /** 12 values, January..December */
  months: (number | null)[];
  /** why a month has no value: complete | partial | pending | future | unavailable | no_data | not_imported */
  status?: string[];
}

export interface CalendarResponse {
  region: string;
  years: CalendarYear[];
  /** median for each month across all complete years; null when fewer than 3 years */
  median: (number | null)[];
  harmonization: {
    method: string;
    status: "validated" | "draft";
    r2: number | null;
  };
}

export interface DayValue {
  date: string; // YYYY-MM-DD
  modis: number | null;
  viirs: number | null;
  harmonized: number | null;
  status?: DayStatus;
}

export interface MonthResponse {
  region: string;
  year: number;
  month: number;
  days: DayValue[];
}

/**
 * One active 0.1° GRID CELL on one day — not a fire. lat/lon is the centre of the cell;
 * the real detections inside it come from /api/detections/ (Detection below).
 */
export interface Hotspot {
  id: string;
  /** always "cell" from the backend */
  kind?: "cell";
  /** cell number on the 0.1° grid (row × 3600 + column) */
  cell?: number;
  /** the region's border passes through this cell; only detections inside the border are counted */
  edge?: boolean;
  /** centre of the 0.1° cell */
  lat: number;
  lon: number;
  date: string;
  /** which instrument saw this cell */
  seenBy: "MODIS" | "VIIRS" | "BOTH";
  /** strongest detection in the cell that day, MW; null if NASA gave no FRP */
  frp: number | null;
}

export interface HotspotsResponse {
  region: string;
  from: string;
  to: string;
  hotspots: Hotspot[];
  /** all active cell-days of the selection (hotspots may hold only the strongest of them) */
  total?: number;
  truncated?: boolean;
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

/**
 * One detection exactly as NASA reported it (backend `GET /api/detections/`), with its real coordinates.
 * Used by the "Hotspot Telemetry" card when a map cell is clicked.
 */
export interface Detection {
  acq_date: string; // YYYY-MM-DD, UTC
  acq_time: string; // HHMM, UTC
  sensor: Sensor;
  satellite: string; // Terra, Aqua, NOAA-20
  latitude: number;
  longitude: number;
  frp_mw: number | null;
  /** MODIS: "0".."100" (percent); VIIRS: "l" | "n" | "h"; null if unknown */
  confidence: string | null;
  daynight: "D" | "N" | null;
  /** SP (final) or NRT (preliminary) */
  product?: "SP" | "NRT" | null;
}

export interface PointsResponse {
  count: number;
  has_more: boolean;
  points: Detection[];
}

/** The real border of a region (GeoJSON Feature, MultiPolygon of [lon, lat]). */
export interface BoundaryResponse {
  type: "Feature";
  properties: { region: string; kind: string; id?: string };
  geometry: { type: "MultiPolygon"; coordinates: [number, number][][][] };
}

/** Synchronisation with NASA FIRMS (backend `GET /api/sync/`). */
export interface SyncResponse {
  status: "never_synced" | "catching_up" | "up_to_date";
  from: string | null;
  today: string;
  pending_downloads: number;
  days: Record<string, number>;
  last_success_at: string | null;
  last_complete_at: string | null;
  last_error: { at: string; message: string } | null;
  update?: { state: string; message: string; enabled: boolean };
}

// ---------- Own area + date range (backend root endpoints /calendar and /export.csv) ----------

/** What to analyse: a ready-made region, or an own rectangle [west, south, east, north] in degrees. */
export type AreaQuery = { region: string } | { bbox: [number, number, number, number] };

/** One sensor on one day: `null` values = the day is not stored for this sensor. */
export interface RangeSensorDay {
  status: "loaded" | "missing";
  /** individual NASA detections that day */
  observations: number | null;
  /** distinct active 0.1° cells that day */
  active_cells: number | null;
}

export interface RangeDay {
  date: string; // YYYY-MM-DD, UTC
  modis: RangeSensorDay;
  viirs: RangeSensorDay;
  /** cells both sensors saw (only when both are stored) */
  shared_active_cells: number | null;
}

/** Backend `GET /calendar?date_from&date_to&(region | west,south,east,north)`. */
export interface RangeReport {
  date_from: string;
  date_to: string;
  daily: RangeDay[];
  coverage: Record<"modis" | "viirs", { loaded_days: number; requested_days: number }>;
  /** null when not every day of the period is stored */
  totals: Record<"modis" | "viirs", { observations: number | null; active_cell_days: number | null }>;
}

/** Backend `GET /cells?date_from&date_to&(region | west,south,east,north)&resolution=0.1`: active cells of a period. */
export interface RangeCellsResponse {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] }; // [lon, lat] of the cell centre
    properties: {
      active_days: number;
      modis_cell_days: number;
      viirs_cell_days: number;
      modis_observations: number;
      viirs_observations: number;
    };
  }[];
  meta: { cells: number; truncated: boolean; resolution_degrees: number };
}
