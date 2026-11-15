"use client";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { api, downloadCsv } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { REGIONS, YEARS } from "@/lib/mock";
import type { SyncResponse } from "@/types/api";
import { Button, Field, Panel, Placeholder, Select, Toggle } from "@/components/ui";
import FloatingWindow from "@/components/ui/FloatingWindow";
import RangeSlider from "@/components/ui/RangeSlider";
import Checkbox from "@/components/ui/Checkbox";
import { SENSOR_COLORS } from "@/lib/colors";
import DayCalendar, { DAY_LEVELS, DAY_STATES } from "./DayCalendar";
import ActivityChart from "./ActivityChart";
import BarChart, { linearTrend } from "./BarChart";
import YearCalendar from "./YearCalendar";
import RangeReport, { type AnalysisQuery, type Box } from "./RangeReport";
import type { Hotspot } from "@/types/api";
import { CsvButton, PngButton } from "./DownloadButtons";
import RampLegend from "./RampLegend";

const FireMap = dynamic(() => import("./FireMap"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-[#0b2238]" />,
});

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MONTH_NUMS = Array.from({ length: 12 }, (_, i) => i + 1);

const FRP_MAX = 500;
const MAX_MAP_DAYS = 92; // backend /cells: at most 92 days per request
// "Area & dates" sits at the right edge, narrow enough to leave the map visible next to the left panel
const REPORT_WIDTH = 600; // right end of the slider = "500+ MW"

// Chart windows. To add a new chart: add it here and in renderWindow below.
const CHARTS = [
  { id: "monthly", label: "Monthly activity", title: "Monthly activity over the year", width: 820 },
  { id: "surface", label: "Surface", title: "Area with active fire", width: 760 },
  { id: "frp", label: "FRP", title: "Fire Radiative Power", width: 760 },
  { id: "trend", label: "Trend & Anomaly", title: "Trend & Anomaly", width: 880 },
] as const;
// all windows: the charts above + "Area & dates" (own rectangle, any period, downloads), opened from the filter bar
const WINDOWS = [...CHARTS, { id: "report", label: "Area & dates", title: "Area & dates", width: REPORT_WIDTH }] as const;
type ChartId = (typeof WINDOWS)[number]["id"];

export default function Explorer() {
  // --- filters ---
  const [regionId, setRegionId] = useState("world");
  const [sel, setSel] = useState({ year: 2024, month: 8 });
  const [day, setDay] = useState<string | null>(null); // selected day, or the whole month
  const [sensors, setSensors] = useState({ modis: true, viirs: true });
  // exactly one sensor ticked → the telemetry card asks the backend only for that sensor
  const onlySensor = sensors.modis !== sensors.viirs ? (sensors.modis ? "MODIS" : "VIIRS") : undefined;
  const [frp, setFrp] = useState<[number, number]>([0, FRP_MAX]);
  // own rectangle of the "Area & dates" window, and whether it is being drawn on the map right now
  const [customBox, setCustomBox] = useState<Box | null>(null);
  const [drawing, setDrawing] = useState(false);
  // the last "Analyse" of that window: while set, the map shows ITS cells (area + dates) instead of the month
  const [analysis, setAnalysis] = useState<AnalysisQuery | null>(null);

  // --- windows ---
  const [windows, setWindows] = useState<{ id: ChartId; z: number }[]>([]);
  const topZ = Math.max(0, ...windows.map((w) => w.z));
  const isOpen = (id: ChartId) => windows.some((w) => w.id === id);
  const toggleWindow = (id: ChartId) => {
    if (id === "report" && isOpen(id)) {
      // closing the report stops drawing and brings the map back to the selected month
      setDrawing(false);
      setAnalysis(null);
    }
    setWindows(isOpen(id) ? windows.filter((w) => w.id !== id) : [...windows, { id, z: topZ + 1 }]);
  };
  const focusWindow = (id: ChartId) =>
    setWindows(windows.map((w) => (w.id === id && w.z !== topZ ? { ...w, z: topZ + 1 } : w)));

  // --- settings inside the windows ---
  const [show, setShow] = useState({ modis: true, viirs: true });
  const [mode, setMode] = useState<"count" | "anomaly">("count");

  // --- data ---
  // regions and years come from the backend (falls back to the demo list without a backend)
  const meta = useApi("meta", () => api.meta());
  const regions = meta.data?.regions.length ? meta.data.regions : REGIONS;
  const years = meta.data?.years.length ? meta.data.years : YEARS;
  const region = regions.find((r) => r.id === regionId) ?? regions[0];

  // First and last stored month, from the backend's coverage (falls back to the real archive start).
  // Months outside this range have no satellite records at all, so they are not offered.
  const range = useMemo(() => {
    const cov = Object.values(meta.data?.data ?? {});
    const firsts = cov.map((c) => c.first_day).filter((d): d is string => !!d).sort();
    const lasts = cov.map((c) => c.last_day).filter((d): d is string => !!d).sort();
    return {
      firstDay: firsts[0] ?? "2000-11-01",
      first: (firsts[0] ?? "2000-11-01").slice(0, 7), // "YYYY-MM"
      last: (lasts[lasts.length - 1] ?? "2099-12-31").slice(0, 7),
      lastDay: lasts[lasts.length - 1] ?? "2099-12-31", // the real last day comes from /api/meta/
      viirsFirstDay: meta.data?.data?.viirs?.first_day ?? "2018-04-01",
    };
  }, [meta.data]);
  const ym = (y: number, m: number) => `${y}-${String(m).padStart(2, "0")}`; // "YYYY-MM"
  const hasData = (y: number, m: number) => ym(y, m) >= range.first && ym(y, m) <= range.last;
  const monthKey = `${regionId}-${sel.year}-${sel.month}`;
  const cal = useApi(regionId, () => api.calendar(regionId));
  const mon = useApi(monthKey, () => api.month(regionId, sel.year, sel.month));
  const hs = useApi(monthKey, () => api.hotspots(regionId, sel.year, sel.month));
  const yr = useApi(`${regionId}-${sel.year}`, () => api.monthly(regionId, sel.year));
  // state of the NASA synchronisation (read once per page; the backend answers from its database)
  const sync = useApi("sync", () => api.sync());
  const error = meta.error ?? cal.error ?? mon.error ?? hs.error ?? yr.error ?? null;

  // ---- the "Area & dates" result on the map: active cells of that area over that period ----
  const analysisDays = analysis ? Math.round((Date.parse(analysis.to) - Date.parse(analysis.from)) / 86_400_000) + 1 : 0;
  const analysisFits = analysis !== null && analysisDays <= MAX_MAP_DAYS;
  const cellsRes = useApi(analysisFits ? `cells-${JSON.stringify(analysis)}` : "cells-none", () =>
    analysisFits ? api.rangeCells(analysis!.area, analysis!.from, analysis!.to) : Promise.resolve(null),
  );
  const analysisCells = useMemo(() => {
    const info = new Map<string, string>();
    const list: Hotspot[] = [];
    for (const [i, f] of (cellsRes.data?.features ?? []).entries()) {
      const p = f.properties;
      const seenBy = p.modis_cell_days > 0 && p.viirs_cell_days > 0 ? "BOTH" : p.modis_cell_days > 0 ? "MODIS" : "VIIRS";
      if (seenBy === "MODIS" ? !sensors.modis : seenBy === "VIIRS" ? !sensors.viirs : !(sensors.modis || sensors.viirs)) continue;
      const id = `a${i}`;
      list.push({ id, lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0], date: "", seenBy, frp: null });
      info.set(
        id,
        `0.1° cell · active on ${p.active_days} day${p.active_days === 1 ? "" : "s"} · ` +
          `MODIS ${p.modis_observations} / VIIRS ${p.viirs_observations} detections · click for details`,
      );
    }
    return { list, info };
  }, [cellsRes.data, sensors]);
  const showAnalysis = analysisFits && !!cellsRes.data;

  // map points, filtered by day, sensors and FRP range
  const points = useMemo(() => {
    const [lo, hi] = frp;
    return (hs.data?.hotspots ?? []).filter((h) => {
      if (day && h.date !== day) return false;
      const sensorOk = h.seenBy === "BOTH" ? sensors.modis || sensors.viirs : h.seenBy === "MODIS" ? sensors.modis : sensors.viirs;
      // unknown FRP is not a measured zero: such points are shown only while the filter starts at 0
      if (h.frp === null) return sensorOk && lo === 0;
      return sensorOk && h.frp >= lo && (hi >= FRP_MAX || h.frp <= hi);
    });
  }, [hs.data, day, sensors, frp]);

  function pick(next: Partial<typeof sel>) {
    const n = { ...sel, ...next };
    // e.g. switching to 2000 while "August" is selected → November 2000, the first month with data
    if (ym(n.year, n.month) < range.first) n.month = Number(range.first.slice(5));
    if (ym(n.year, n.month) > range.last) n.month = Number(range.last.slice(5));
    setSel(n);
    setDay(null);
  }

  function exportCsv() {
    // with a backend: the real NASA detections (own coordinates, time, satellite, FRP) of the region
    const url = api.exportUrl(regionId, sel.year, sel.month, day, onlySensor);
    if (url) {
      window.location.assign(url);
      return;
    }
    // demo: the map cells — named as cell centres, so nobody takes them for fire locations
    const tag = day ?? `${sel.year}-${String(sel.month).padStart(2, "0")}`;
    downloadCsv(
      `${regionId}_${tag}_active_cells.csv`,
      points.map((h) => ({
        date: h.date,
        cell_centre_latitude: h.lat.toFixed(2),
        cell_centre_longitude: h.lon.toFixed(2),
        cell_size_degrees: 0.1,
        seen_by: h.seenBy,
        max_frp_mw: h.frp,
      })),
    );
  }

  function renderWindow(id: ChartId) {
    const m = yr.data?.months;
    switch (id) {
      case "monthly":
        return {
          actions: (
            <>
              <Toggle active={show.modis} color="#f39314" onClick={() => setShow({ ...show, modis: !show.modis })}>
                MODIS
              </Toggle>
              <Toggle active={show.viirs} color="#ffd60a" onClick={() => setShow({ ...show, viirs: !show.viirs })}>
                VIIRS
              </Toggle>
              <CsvButton
                disabled={!m}
                onClick={() =>
                  m &&
                  downloadCsv(
                    `firesync_${regionId}_${sel.year}_monthly.csv`,
                    m.map((x) => ({ year: sel.year, month: x.month, modis_active_cell_days: x.modis, viirs_active_cell_days: x.viirs, area_km2: x.areaKm2, frp_mean_mw: x.frpMean, frp_max_mw: x.frpMax })),
                  )
                }
              />
              <PngButton filename={`firesync_${regionId}_${sel.year}_monthly.png`} title="Monthly activity over the year" subtitle={`${region.name} · ${sel.year} · FireSync, NASA FIRMS`} />
            </>
          ),
          body: yr.data ? (
            <>
              <ActivityChart data={yr.data} show={show} selectedMonth={sel.month} onSelectMonth={(mm) => pick({ month: mm })} />
              <p className="mt-1 text-xs text-muted">
                Active fire cells per month, {sel.year}. VIIRS is harmonized to the MODIS scale
                .
                {sel.year < Number(range.viirsFirstDay.slice(0, 4)) && ` VIIRS (NOAA-20) data starts in ${fmtMonth(range.viirsFirstDay)}.`}
                {sel.year === Number(range.firstDay.slice(0, 4)) && ` MODIS records start on ${fmtDay(range.firstDay)}.`}
              </p>
            </>
          ) : (
            <Placeholder className="h-60" />
          ),
        };
      case "surface":
        return {
          actions: <PngButton filename={`firesync_${regionId}_${sel.year}_area.png`} title="Area with active fire, km² per month" subtitle={`${region.name} · ${sel.year} · FireSync, NASA FIRMS`} />,
          body: m ? (
            <>
              <BarChart
                labels={MONTH_NUMS}
                values={m.map((x) => x.areaKm2)}
                color="#f39314"
                selected={sel.month - 1}
                onSelect={(i) => pick({ month: i + 1 })}
                format={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`)}
              />
              <p className="mt-1 text-xs text-muted">
                Approximate area of 0.1° grid cells with active fire, km² per month, {sel.year}.
              </p>
            </>
          ) : (
            <Placeholder className="h-60" />
          ),
        };
      case "frp":
        return {
          actions: <PngButton filename={`firesync_${regionId}_${sel.year}_frp.png`} title="Fire Radiative Power per month, MW" subtitle={`${region.name} · ${sel.year} · FireSync, NASA FIRMS`} />,
          body: m ? (
            <>
              <BarChart
                labels={MONTH_NUMS}
                values={m.map((x) => x.frpMean)}
                dots={m.map((x) => x.frpMax)}
                color="#ff2a1a"
                selected={sel.month - 1}
                onSelect={(i) => pick({ month: i + 1 })}
              />
              <p className="mt-1 flex flex-wrap gap-4 text-xs text-muted">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-sm bg-fire" /> mean FRP, MW
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-viirs" /> strongest fire, MW
                </span>
              </p>
            </>
          ) : (
            <Placeholder className="h-60" />
          ),
        };
      case "report": {
        const monthFrom = `${ym(sel.year, sel.month)}-01`;
        const monthTo = `${ym(sel.year, sel.month)}-${String(new Date(Date.UTC(sel.year, sel.month, 0)).getUTCDate()).padStart(2, "0")}`;
        return {
          body: (
            <RangeReport
              region={region}
              box={customBox}
              onBox={setCustomBox}
              drawing={drawing}
              onDrawing={setDrawing}
              firstDay={range.firstDay}
              lastDay={range.lastDay}
              monthFrom={monthFrom < range.firstDay ? range.firstDay : monthFrom}
              monthTo={monthTo > range.lastDay ? range.lastDay : monthTo}
              sensor={onlySensor}
              onAnalysed={setAnalysis}
            />
          ),
        };
      }
      case "trend": {
        // only years with all 12 months complete get a total: a partial year is not a quiet year
        const totals = cal.data?.years.map((y) => (y.months.every((v) => v !== null) ? y.months.reduce<number>((a, v) => a + (v ?? 0), 0) : null)) ?? [];
        return {
          actions: (
            <>
              <Toggle active={mode === "count"} color="#17b6d9" onClick={() => setMode("count")}>
                Activity
              </Toggle>
              <Toggle active={mode === "anomaly"} color="#17b6d9" onClick={() => setMode("anomaly")}>
                Anomaly
              </Toggle>
              <CsvButton
                label="Calendar CSV"
                disabled={!cal.data}
                title="The year × month calendar as numbers (active cell-days per month), plus the median"
                onClick={() => {
                  if (!cal.data) return;
                  const row = (label: string | number, vals: (number | null)[]) =>
                    Object.fromEntries([["year", label], ...MONTH_NAMES.map((mm, i) => [mm.slice(0, 3).toLowerCase(), vals[i]])]);
                  downloadCsv(`firesync_${regionId}_calendar.csv`, [
                    ...cal.data.years.map((y) => row(y.year, y.months)),
                    row("median", cal.data.median),
                  ]);
                }}
              />
              <PngButton
                filename={`firesync_${regionId}_yearly_trend.png`}
                title="Yearly total and trend"
                subtitle={`${region.name} · FireSync, NASA FIRMS`}
              />
            </>
          ),
          body: cal.data ? (
            <>
              <YearCalendar data={cal.data} mode={mode} selected={sel} onSelect={(year, month) => pick({ year, month })} />
              <RampLegend mode={mode} />
              <p className="mt-2 text-xs text-muted">
                MODIS starts on {fmtDay(range.firstDay)}, VIIRS (NOAA-20) on {fmtDay(range.viirsFirstDay)}. Striped = month
                still downloading or incomplete, outlined = not yet happened. Hover a cell for details.
              </p>
              <h4 className="mb-1 mt-6 text-sm">Yearly total and trend</h4>
              <BarChart
                labels={cal.data.years.map((y) => String(y.year).slice(2))}
                values={totals}
                color="#1f6fc0"
                trend={linearTrend(totals)}
                selected={cal.data.years.findIndex((y) => y.year === sel.year)}
                onSelect={(i) => pick({ year: cal.data!.years[i].year })}
                format={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`)}
                labelEvery={4}
              />
            </>
          ) : (
            <Placeholder className="h-96" />
          ),
        };
      }
    }
  }

  return (
    <section className="relative lg:h-[calc(100dvh-8.5rem)] lg:min-h-[640px] lg:overflow-hidden">
      {/* ===== Map ===== */}
      <div className="h-[55vh] lg:absolute lg:inset-0 lg:h-auto">
        <FireMap
          region={region}
          hotspots={showAnalysis ? analysisCells.list : points}
          cardPeriod={showAnalysis && analysis ? { from: analysis.from, to: analysis.to } : null}
          tooltip={showAnalysis ? (h) => analysisCells.info.get(h.id) ?? "" : undefined}
          fitTo={analysis?.box ?? null}
          fitPaddingRight={isOpen("report") ? REPORT_WIDTH + 40 : 40}
          sensor={onlySensor}
          customBox={isOpen("report") ? customBox : null}
          drawing={drawing}
          onDrawn={(b) => (setCustomBox(b), setDrawing(false))}
        />
      </div>

      {/* ===== Filters: Region / Year / Month ===== */}
      <div className="px-4 pt-4 lg:pointer-events-none lg:absolute lg:inset-x-0 lg:top-5 lg:z-[1100] lg:flex lg:justify-center lg:max-[1799px]:pl-[450px] lg:pr-6 min-[1800px]:pl-6 lg:pt-0">
        <Panel className="pointer-events-auto flex flex-wrap gap-3 p-2.5">
          <Field label="Region">
            <Select value={regionId} onChange={(e) => (setRegionId(e.target.value), setDay(null))}>
              {regions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Year">
            <Select value={sel.year} onChange={(e) => pick({ year: +e.target.value })}>
              {years.map((y) => (
                <option key={y}>{y}</option>
              ))}
            </Select>
          </Field>
          <Field label="Month">
            <Select value={sel.month} onChange={(e) => pick({ month: +e.target.value })}>
              {MONTH_NAMES.map((mm, i) => (
                <option key={mm} value={i + 1} disabled={!hasData(sel.year, i + 1)}>
                  {mm}
                  {hasData(sel.year, i + 1) ? "" : " — no data"}
                </option>
              ))}
            </Select>
          </Field>
          <button
            onClick={() => toggleWindow("report")}
            aria-pressed={isOpen("report")}
            title="Own area, any date range, analytics and downloads"
            className={`inline-flex items-center gap-2 rounded-2xl border-2 border-accent px-4 text-sm font-medium transition ${
              isOpen("report") ? "bg-accent text-white" : "text-accent hover:bg-accent/10"
            }`}
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
              <rect x="4" y="5" width="16" height="15" rx="2" />
              <path d="M4 10h16M9 3v4M15 3v4" />
            </svg>
            Area &amp; dates
          </button>
        </Panel>
      </div>

      {/* ===== Left panel ===== */}
      <div className="px-4 py-4 lg:absolute lg:bottom-5 lg:left-0 lg:top-5 lg:z-[1100] lg:w-[430px] lg:p-0">
        <Panel className="flex h-full flex-col overflow-y-auto px-6 py-5 lg:rounded-l-none lg:border-l-0">
          {/* Calendar */}
          <h2 className="text-center font-display text-xl 2xl:text-2xl">Burning activity</h2>
          <p className="mt-1 text-center text-sm text-muted">
            {MONTH_NAMES[sel.month - 1]} {sel.year} · {region.name}
          </p>
          <div className="mb-3 mt-2 flex flex-col items-center gap-1.5">
            {sync.data && <SyncBadge sync={sync.data} />}
            {/* the very first month of the archive: say why nothing exists before it */}
            {ym(sel.year, sel.month) === range.first && (
              <p className="text-center text-xs text-accent">Records begin on {fmtDay(range.firstDay)}, no data before</p>
            )}
          </div>
          {mon.data ? <DayCalendar days={mon.data.days} selected={day} onSelect={setDay} /> : <Placeholder className="h-56" />}

          <ul className="mt-2.5 grid grid-cols-3 gap-x-2 gap-y-1.5 text-[11px] leading-tight text-muted" aria-label="Calendar legend">
            {DAY_LEVELS.map((l) => (
              <li key={l.key} className="flex items-center gap-1.5">
                <span className={`h-3.5 w-3.5 shrink-0 rounded ${l.className} ${l.key === "low" ? "border border-line" : ""}`} />
                {l.label.replace(" activity", "")}
              </li>
            ))}
            {DAY_STATES.map((l) => (
              <li key={l.key} className="flex items-center gap-1.5">
                <span className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded text-[8px] ${l.className}`}>7</span>
                {l.label}
              </li>
            ))}
          </ul>

          <div className="mt-2.5 rounded-xl bg-bg/60 px-3 py-1.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span>
                <span className="font-semibold tabular-nums">{hs.data ? points.length.toLocaleString("en") : "…"}</span> active
                cells · {day ? fmtShort(day) : "whole month"}
              </span>
              {day ? (
                <button onClick={() => setDay(null)} className="text-xs text-accent hover:underline">
                  Whole month
                </button>
              ) : (
                <span className="text-xs text-muted">click a day</span>
              )}
            </div>
            {hs.data?.truncated && (
              <p className="mt-0.5 text-xs text-muted">
                strongest of {hs.data.total?.toLocaleString("en")} cell-days shown
              </p>
            )}
          </div>

          {/* Sensors + what the map colors mean */}
          <div className="mt-3 border-y border-line py-2.5">
            <div className="flex justify-center gap-10">
              <Checkbox label="MODIS" color="#f39314" checked={sensors.modis} onChange={(v) => setSensors({ ...sensors, modis: v })} />
              <Checkbox label="VIIRS" color="#ffd60a" checked={sensors.viirs} onChange={(v) => setSensors({ ...sensors, viirs: v })} />
            </div>
            {/* what the colors of the map cells mean (MODIS and VIIRS colors are on the checkboxes) */}
            <p className="mt-2 text-center text-xs text-muted">
              Squares are 0.1° grid cells,{" "}
              <span className="inline-flex items-center gap-1 align-middle">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SENSOR_COLORS.BOTH }} /> both sensors
              </span>
              . Click one for its detections.
            </p>
          </div>

          {/* FRP */}
          <div className="border-b border-line py-2.5">
            <RangeSlider
              label="Fire Radiative Power"
              min={0}
              max={FRP_MAX}
              step={5}
              value={frp}
              onChange={setFrp}
              format={(v) => (v >= FRP_MAX ? `${FRP_MAX}+ MW` : `${v} MW`)}
            />
          </div>

          {/* Charts */}
          <div className="border-b border-line py-2.5">
            <h3 className="mb-2 text-center font-display text-lg">Charts</h3>
            <div className="flex flex-wrap justify-center gap-2">
              {CHARTS.map((c) => (
                <button
                  key={c.id}
                  onClick={() => toggleWindow(c.id)}
                  aria-pressed={isOpen(c.id)}
                  className={`rounded-full border-2 border-accent px-4 py-1 text-sm transition 2xl:text-base ${isOpen(c.id) ? "bg-accent text-white" : "text-accent hover:bg-accent/10"
                    }`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          {/* the button is always visible: on short screens the panel scrolls and the CSV button sticks to the bottom */}
          <div className="sticky -bottom-5 -mx-6 mt-auto flex justify-center bg-surface px-6 py-3">
            <Button onClick={exportCsv} disabled={!hs.data || points.length === 0} className="inline-flex items-center gap-2">
              <FileIcon /> CSV File
            </Button>
          </div>
        </Panel>
      </div>

      {/* what the map shows while an "Area & dates" result is on it */}
      {analysis && (
        <div className="pointer-events-none px-4 pt-3 lg:absolute lg:bottom-6 lg:left-[450px] lg:right-6 lg:z-[1900] lg:flex lg:justify-start lg:p-0">
          <div className="pointer-events-auto flex flex-wrap items-center gap-3 rounded-2xl border border-accent/50 bg-surface/95 px-4 py-2 text-sm shadow-xl">
            <span className="h-2.5 w-2.5 rounded-full bg-accent" aria-hidden />
            {!analysisFits ? (
              <span>
                The map shows up to {MAX_MAP_DAYS} days at once; your period has {analysisDays}. Showing the selected month instead.
              </span>
            ) : cellsRes.error ? (
              <span className="text-red-300">Could not load the map cells: {cellsRes.error}</span>
            ) : !cellsRes.data ? (
              <span className="text-muted">Loading the cells of {analysis.label}…</span>
            ) : (
              <span>
                Map: <b className="font-semibold">{analysis.label}</b> · {analysis.from} – {analysis.to} ·{" "}
                {analysisCells.list.length.toLocaleString("en")} active cells
                {cellsRes.data.meta.truncated ? " (most active shown)" : ""}
              </span>
            )}
            <button onClick={() => setAnalysis(null)} className="rounded-full border border-accent px-3 py-0.5 text-xs text-accent transition hover:bg-accent hover:text-white">
              Back to {MONTH_NAMES[sel.month - 1]} {sel.year}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="absolute bottom-5 right-5 z-[1100] rounded-2xl border border-red-500/40 bg-red-950/90 p-4 text-sm text-red-200">
          Could not load data: {error}
        </div>
      )}

      {/* ===== Chart windows ===== */}
      {windows.map((w) => {
        const cfg = WINDOWS.find((c) => c.id === w.id)!;
        const idx = WINDOWS.findIndex((c) => c.id === w.id);
        const content = renderWindow(w.id);
        return (
          <FloatingWindow
            key={w.id}
            title={cfg.title}
            actions={content.actions}
            // "Area & dates" is tall: it opens at the top, next to the left panel
            // (a huge x is pulled back to the right edge by the window itself)
            initial={w.id === "report" ? { x: 100_000, y: 100 } : { x: 470 + idx * 40, y: 100 + idx * 30 }}
            width={cfg.width}
            z={1200 + w.z}
            onFocus={() => focusWindow(w.id)}
            onClose={() => toggleWindow(w.id)}
          >
            {content.body}
          </FloatingWindow>
        );
      })}
    </section>
  );
}

/** Small pill with the state of the NASA FIRMS synchronisation; details in the tooltip. */
function SyncBadge({ sync }: { sync: NonNullable<SyncResponse> }) {
  const when = (t: string | null) => (t ? new Date(t).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }) : "never");
  const look =
    sync.status === "up_to_date"
      ? { dot: "bg-emerald-400", text: "NASA data up to date" }
      : sync.status === "catching_up"
        ? { dot: "bg-amber-400 animate-pulse", text: `Syncing NASA data · ${sync.pending_downloads.toLocaleString("en")} days left` }
        : { dot: "bg-muted", text: "NASA data not synced yet" };
  const details = [
    `Last sync: ${when(sync.last_success_at)}`,
    sync.last_error ? `Last error: ${sync.last_error.message}` : null,
    sync.update?.message ?? null,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-line bg-bg/60 px-3 py-1 text-xs text-muted"
      title={details}
    >
      <span className={`h-2 w-2 rounded-full ${look.dot}`} aria-hidden />
      {look.text}
      {sync.last_error && <span className="h-2 w-2 rounded-full bg-red-400" title={sync.last_error.message} aria-label="last sync had an error" />}
    </span>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7" />
      <path d="M14 3v5h5M19 8v5" />
      <path d="M18 15v6m-3-3 3 3 3-3" />
    </svg>
  );
}

/** "2000-11-01" → "1 November 2000" */
function fmtDay(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTH_NAMES[m - 1]} ${y}`;
}

/** "2018-04-01" → "April 2018" */
function fmtMonth(iso: string) {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

/** "2024-08-14" → "14 Aug" */
function fmtShort(iso: string) {
  const [, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTH_NAMES[m - 1].slice(0, 3)}`;
}
