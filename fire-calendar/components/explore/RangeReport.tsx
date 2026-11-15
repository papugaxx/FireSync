"use client";
// "Area & dates" window: analyse a ready-made region OR an own rectangle over any period,
// then download the numbers (CSV), every detection (CSV) and the chart (PNG).
// Uses the backend's root endpoints: /calendar (daily activity) and /export.csv (detections).
import { useRef, useState } from "react";
import { api, downloadCsv, USING_DEMO_DATA } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Button, Placeholder, Toggle } from "@/components/ui";
import type { AreaQuery, RangeReport as Report, Region } from "@/types/api";
import DailyChart from "./DailyChart";
import { CsvButton, PngButton } from "./DownloadButtons";

export type Box = [number, number, number, number]; // west, south, east, north

// limits of the backend (config.py): MAX_CALENDAR_DAYS, MAX_CUSTOM_AREA_DAYS, MAX_EXPORT_DAYS
const MAX_REGION_DAYS = 3660;
const MAX_BOX_DAYS = 366;
const MAX_EXPORT_DAYS = 31;

interface Props {
  region: Region;
  /** own rectangle, shared with the map (drawn there or typed here) */
  box: Box | null;
  onBox: (b: Box | null) => void;
  drawing: boolean;
  onDrawing: (on: boolean) => void;
  /** first and last stored day, "YYYY-MM-DD" */
  firstDay: string;
  lastDay: string;
  /** the month selected in the filters, as a default period */
  monthFrom: string;
  monthTo: string;
  sensor?: "MODIS" | "VIIRS";
  /** called on "Analyse": the page then shows this area and period on the map */
  onAnalysed?: (q: AnalysisQuery) => void;
}

export interface AnalysisQuery {
  area: AreaQuery;
  from: string;
  to: string;
  label: string;
  /** the area as a box, for zooming the map to it */
  box: Box;
}

export default function RangeReport(props: Props) {
  const { region, box, onBox, drawing, onDrawing, firstDay, lastDay, monthFrom, monthTo, sensor, onAnalysed } = props;
  const [mode, setMode] = useState<"region" | "box">(box ? "box" : "region");
  const [from, setFrom] = useState(monthFrom);
  const [to, setTo] = useState(monthTo);
  const [query, setQuery] = useState<{ area: AreaQuery; from: string; to: string; label: string } | null>(null);
  const [show, setShow] = useState({ modis: true, viirs: true });
  const chartRef = useRef<HTMLDivElement>(null);

  // the rectangle offered by default: the selected region's extent
  const regionBox: Box = [region.bbox[1], region.bbox[0], region.bbox[3], region.bbox[2]];
  const area: AreaQuery = mode === "region" ? { region: region.id } : { bbox: box ?? regionBox };
  const days = dayCount(from, to);
  const problems = check(mode, mode === "box" ? (box ?? regionBox) : null, from, to, firstDay, lastDay, days);

  const res = useApi(query ? JSON.stringify(query) : "none", () =>
    query ? api.rangeReport(query.area, query.from, query.to) : Promise.resolve(null),
  );
  const report = query ? res.data ?? null : null;

  function run() {
    const label = mode === "region" ? region.name : `Area ${fmtBox(box ?? regionBox)}`;
    if (mode === "box" && !box) onBox(regionBox);
    onDrawing(false);
    setQuery({ area, from, to, label });
    onAnalysed?.({ area, from, to, label, box: mode === "box" ? (box ?? regionBox) : regionBox });
  }

  function preset(kind: "month" | "last30" | "year") {
    if (kind === "month") return (setFrom(monthFrom), setTo(monthTo));
    if (kind === "last30") return (setFrom(addDays(lastDay, -29)), setTo(lastDay));
    const y = monthFrom.slice(0, 4);
    setFrom(maxStr(`${y}-01-01`, firstDay));
    setTo(minStr(`${y}-12-31`, lastDay));
  }

  return (
    <div className="space-y-4">
      {/* ---------- 1. area ---------- */}
      <fieldset>
        <legend className="mb-2 text-sm">1. Area</legend>
        <div className="flex flex-wrap gap-2">
          <Toggle active={mode === "region"} color="#17b6d9" onClick={() => (setMode("region"), onDrawing(false))}>
            {region.name}
          </Toggle>
          <Toggle active={mode === "box"} color="#17b6d9" onClick={() => (setMode("box"), onBox(box ?? regionBox))}>
            Own rectangle
          </Toggle>
        </div>

        {mode === "box" && (
          <div className="mt-3 rounded-2xl bg-bg/60 p-3">
            <BoxInputs key={(box ?? regionBox).join(",")} box={box ?? regionBox} onBox={onBox} />
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
              <button
                onClick={() => onDrawing(!drawing)}
                className={`rounded-full border-2 px-3 py-1 font-medium transition ${
                  drawing ? "border-accent bg-accent text-bg" : "border-accent text-accent hover:bg-accent/10"
                }`}
              >
                {drawing ? "Drag on the map… (click to cancel)" : "Draw on the map"}
              </button>
              <span className="text-muted">Degrees: west / south / east / north. Up to {MAX_BOX_DAYS} days.</span>
            </div>
          </div>
        )}
      </fieldset>

      {/* ---------- 2. dates ---------- */}
      <fieldset>
        <legend className="mb-2 text-sm">2. Dates (UTC)</legend>
        <div className="flex flex-wrap items-center gap-2">
          <DateInput label="From" value={from} min={firstDay} max={lastDay} onChange={setFrom} />
          <span className="text-muted">–</span>
          <DateInput label="To" value={to} min={firstDay} max={lastDay} onChange={setTo} />
          <span className="text-xs text-muted">{days > 0 ? `${days.toLocaleString("en")} days` : ""}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          {(
            [
              ["month", "Selected month"],
              ["last30", "Last 30 days"],
              ["year", "Selected year"],
            ] as const
          ).map(([k, label]) => (
            <button key={k} onClick={() => preset(k)} className="rounded-full border border-line px-3 py-1 text-muted transition hover:border-accent hover:text-white">
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      {/* ---------- 3. run ---------- */}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={run} disabled={problems.length > 0}>
          Analyse
        </Button>
        {problems.length > 0 && <p className="text-xs text-red-300">{problems[0]}</p>}
      </div>

      {/* ---------- results ---------- */}
      {query && (
        <section className="border-t border-line pt-4" aria-live="polite">
          {res.error ? (
            <p className="text-sm text-red-300">Could not analyse: {res.error}</p>
          ) : !report ? (
            <Placeholder className="h-64" label="Analysing…" />
          ) : (
            <Results
              report={report}
              query={query}
              show={show}
              setShow={setShow}
              chartRef={chartRef}
              sensor={sensor}
            />
          )}
        </section>
      )}
    </div>
  );
}

function Results({
  report,
  query,
  show,
  setShow,
  chartRef,
  sensor,
}: {
  report: Report;
  query: { area: AreaQuery; from: string; to: string; label: string };
  show: { modis: boolean; viirs: boolean };
  setShow: (s: { modis: boolean; viirs: boolean }) => void;
  chartRef: React.RefObject<HTMLDivElement | null>;
  sensor?: "MODIS" | "VIIRS";
}) {
  const d = report.daily;
  const sum = (ch: "modis" | "viirs", f: "active_cells" | "observations") => d.reduce((a, x) => a + (x[ch][f] ?? 0), 0);
  const fireDays = d.filter((x) => (x.modis.active_cells ?? 0) > 0 || (x.viirs.active_cells ?? 0) > 0).length;
  const peak = d.reduce<{ date: string; v: number } | null>((best, x) => {
    const v = Math.max(x.modis.active_cells ?? 0, x.viirs.active_cells ?? 0);
    return !best || v > best.v ? { date: x.date, v } : best;
  }, null);
  const cov = report.coverage;
  const incomplete = (["modis", "viirs"] as const).filter((ch) => cov[ch].loaded_days < cov[ch].requested_days);
  const name = fileTag(query);
  const exportUrl = api.exportRangeUrl(query.area, query.from, query.to, sensor);
  const tooLongForExport = d.length > MAX_EXPORT_DAYS;

  return (
    <div className="space-y-4">
      <p className="text-sm">
        <span className="font-medium">{query.label}</span>
        <span className="text-muted">
          {" "}
          · {fmtDate(query.from)} – {fmtDate(query.to)} · {d.length.toLocaleString("en")} days
        </span>
      </p>

      <dl className="grid grid-cols-2 gap-3">
        <Tile label="Days with fire" value={`${fireDays.toLocaleString("en")} / ${d.length.toLocaleString("en")}`} />
        <Tile
          label="MODIS"
          color="text-modis"
          value={`${sum("modis", "active_cells").toLocaleString("en")} cell-days`}
          hint={`${sum("modis", "observations").toLocaleString("en")} detections`}
        />
        <Tile
          label="VIIRS"
          color="text-viirs"
          value={`${sum("viirs", "active_cells").toLocaleString("en")} cell-days`}
          hint={`${sum("viirs", "observations").toLocaleString("en")} detections`}
        />
        <Tile label="Peak day" value={peak && peak.v > 0 ? fmtDate(peak.date) : "—"} hint={peak && peak.v > 0 ? `${peak.v.toLocaleString("en")} active cells` : undefined} />
      </dl>

      {incomplete.length > 0 && (
        <p className="text-xs text-muted">
          Not every day is stored:{" "}
          {incomplete.map((ch) => `${ch.toUpperCase()} ${cov[ch].loaded_days} of ${cov[ch].requested_days} days`).join(", ")}. Totals count
          the stored days only; missing days break the lines below.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Toggle active={show.modis} color="#f39314" onClick={() => setShow({ ...show, modis: !show.modis })}>
          MODIS
        </Toggle>
        <Toggle active={show.viirs} color="#ffd60a" onClick={() => setShow({ ...show, viirs: !show.viirs })}>
          VIIRS
        </Toggle>
        <span className="text-xs text-muted">active 0.1° cells per day</span>
      </div>
      <div ref={chartRef} className="overflow-x-auto">
        <DailyChart days={d} show={show} />
      </div>

      {/* ---------- downloads ---------- */}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <span className="mr-1 text-sm">Download</span>
        <CsvButton
          label="Daily numbers CSV"
          onClick={() =>
            downloadCsv(
              `firesync_${name}_daily.csv`,
              d.map((x) => ({
                date: x.date,
                modis_active_cells: x.modis.active_cells,
                modis_detections: x.modis.observations,
                viirs_active_cells: x.viirs.active_cells,
                viirs_detections: x.viirs.observations,
                cells_seen_by_both: x.shared_active_cells,
              })),
            )
          }
        />
        <CsvButton
          label="All detections CSV"
          disabled={!exportUrl || tooLongForExport}
          title={
            !exportUrl
              ? "Needs the backend (demo mode)"
              : tooLongForExport
                ? `Every detection can be exported for up to ${MAX_EXPORT_DAYS} days; choose a shorter period`
                : "Every NASA detection of this area and period, with coordinates, time, satellite and FRP"
          }
          onClick={() => exportUrl && window.location.assign(exportUrl)}
        />
        <PngButton
          filename={`firesync_${name}_chart.png`}
          title="Active fire cells per day"
          subtitle={`${query.label} · ${fmtDate(query.from)} – ${fmtDate(query.to)} · FireSync, NASA FIRMS (MODIS, VIIRS NOAA-20)`}
          scope={() => chartRef.current}
        />
        {tooLongForExport && exportUrl && (
          <span className="text-xs text-muted">All detections: up to {MAX_EXPORT_DAYS} days at a time.</span>
        )}
        {USING_DEMO_DATA && <span className="text-xs text-muted">Demo data.</span>}
      </div>
    </div>
  );
}

// ---------- small pieces ----------

function Tile({ label, value, hint, color = "" }: { label: string; value: string; hint?: string; color?: string }) {
  return (
    <div className="rounded-2xl bg-bg/60 p-3">
      <dt className={`text-xs ${color || "text-muted"}`}>{label}</dt>
      <dd className="mt-1 text-base font-semibold tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-muted">{hint}</dd>}
    </div>
  );
}

function DateInput({ label, value, min, max, onChange }: { label: string; value: string; min: string; max: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-2 rounded-xl bg-surface-2 py-1.5 pl-3 pr-2 text-sm">
      <span className="text-muted">{label}</span>
      <input
        type="date"
        value={value}
        min={min}
        max={max}
        onChange={(e) => e.target.value && onChange(e.target.value)}
        className="bg-transparent [color-scheme:dark]"
      />
    </label>
  );
}

/** Four coordinate fields. Text drafts so that typing "-" or "4." is possible; applied when valid. */
function BoxInputs({ box, onBox }: { box: Box; onBox: (b: Box) => void }) {
  const [draft, setDraft] = useState(box.map(String));
  const labels = ["West", "South", "East", "North"];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {labels.map((l, i) => (
        <label key={l} className="flex flex-col gap-1 text-xs text-muted">
          {l}
          <input
            inputMode="decimal"
            value={draft[i]}
            onChange={(e) => {
              const next = [...draft];
              next[i] = e.target.value;
              setDraft(next);
              const nums = next.map(Number);
              if (nums.every((v, k) => next[k].trim() !== "" && Number.isFinite(v))) onBox(nums as Box);
            }}
            className="rounded-lg bg-surface-2 px-2 py-1.5 text-sm text-white"
          />
        </label>
      ))}
    </div>
  );
}

function check(mode: "region" | "box", box: Box | null, from: string, to: string, firstDay: string, lastDay: string, days: number) {
  const out: string[] = [];
  if (!from || !to) out.push("Choose both dates.");
  else if (to < from) out.push("“To” is earlier than “From”.");
  else if (from < firstDay || to > lastDay) out.push(`Data exists from ${fmtDate(firstDay)} to ${fmtDate(lastDay)}.`);
  const max = mode === "box" ? MAX_BOX_DAYS : MAX_REGION_DAYS;
  if (days > max) out.push(`At most ${max.toLocaleString("en")} days for ${mode === "box" ? "an own rectangle" : "a region"}; now ${days.toLocaleString("en")}.`);
  if (box) {
    const [w, s, e, n] = box;
    if (!(w >= -180 && e <= 180 && s >= -90 && n <= 90)) out.push("Coordinates are out of range (longitude ±180, latitude ±90).");
    else if (!(w < e && s < n)) out.push("West must be less than east, and south less than north.");
  }
  return out;
}

function dayCount(from: string, to: string) {
  if (!from || !to || to < from) return 0;
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1;
}
function addDays(iso: string, n: number) {
  return new Date(Date.parse(iso) + n * 86_400_000).toISOString().slice(0, 10);
}
const minStr = (a: string, b: string) => (a < b ? a : b);
const maxStr = (a: string, b: string) => (a > b ? a : b);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
export function fmtBox([w, s, e, n]: Box) {
  const lat = (v: number) => `${Math.abs(v)}°${v >= 0 ? "N" : "S"}`;
  const lon = (v: number) => `${Math.abs(v)}°${v >= 0 ? "E" : "W"}`;
  return `${lat(s)}–${lat(n)}, ${lon(w)}–${lon(e)}`;
}
function fileTag(q: { area: AreaQuery; from: string; to: string }) {
  const a = "region" in q.area ? q.area.region : `area_${q.area.bbox.join("_")}`;
  return `${a}_${q.from}_${q.to}`;
}
