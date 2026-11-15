"use client";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { api, downloadCsv } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { REGIONS, YEARS } from "@/lib/mock";
import { Button, Field, Panel, Placeholder, Select, Toggle } from "@/components/ui";
import FloatingWindow from "@/components/ui/FloatingWindow";
import RangeSlider from "@/components/ui/RangeSlider";
import Checkbox from "@/components/ui/Checkbox";
import { SENSOR_COLORS } from "@/lib/colors";
import DayCalendar, { DAY_LEVELS } from "./DayCalendar";
import ActivityChart from "./ActivityChart";
import BarChart, { linearTrend } from "./BarChart";
import YearCalendar from "./YearCalendar";
import RampLegend from "./RampLegend";

const FireMap = dynamic(() => import("./FireMap"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-[#0b2238]" />,
});

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MONTH_NUMS = Array.from({ length: 12 }, (_, i) => i + 1);

const FRP_MAX = 500; // right end of the slider = "500+ MW"

// Chart windows. To add a new chart: add it here and in renderWindow below.
const CHARTS = [
  { id: "monthly", label: "Monthly activity", title: "Monthly activity over the year", width: 820 },
  { id: "surface", label: "Surface", title: "Area with active fire", width: 760 },
  { id: "frp", label: "FRP", title: "Fire Radiative Power", width: 760 },
  { id: "trend", label: "Trend & Anomaly", title: "Trend & Anomaly", width: 880 },
] as const;
type ChartId = (typeof CHARTS)[number]["id"];

export default function Explorer() {
  // --- filters ---
  const [regionId, setRegionId] = useState("world");
  const [sel, setSel] = useState({ year: 2024, month: 8 });
  const [day, setDay] = useState<string | null>(null); // selected day, or the whole month
  const [sensors, setSensors] = useState({ modis: true, viirs: true });
  // exactly one sensor ticked → the telemetry card asks the backend only for that sensor
  const onlySensor = sensors.modis !== sensors.viirs ? (sensors.modis ? "MODIS" : "VIIRS") : undefined;
  const [frp, setFrp] = useState<[number, number]>([0, FRP_MAX]);

  // --- windows ---
  const [windows, setWindows] = useState<{ id: ChartId; z: number }[]>([]);
  const topZ = Math.max(0, ...windows.map((w) => w.z));
  const isOpen = (id: ChartId) => windows.some((w) => w.id === id);
  const toggleWindow = (id: ChartId) =>
    setWindows(isOpen(id) ? windows.filter((w) => w.id !== id) : [...windows, { id, z: topZ + 1 }]);
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
  const monthKey = `${regionId}-${sel.year}-${sel.month}`;
  const cal = useApi(regionId, () => api.calendar(regionId));
  const mon = useApi(monthKey, () => api.month(regionId, sel.year, sel.month));
  const hs = useApi(monthKey, () => api.hotspots(regionId, sel.year, sel.month));
  const yr = useApi(`${regionId}-${sel.year}`, () => api.monthly(regionId, sel.year));
  const error = meta.error ?? cal.error ?? mon.error ?? hs.error ?? yr.error ?? null;

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
    setSel({ ...sel, ...next });
    setDay(null);
  }

  function exportCsv() {
    const tag = day ?? `${sel.year}-${String(sel.month).padStart(2, "0")}`;
    downloadCsv(
      `${regionId}_${tag}_hotspots.csv`,
      points.map((h) => ({ date: h.date, latitude: h.lat.toFixed(4), longitude: h.lon.toFixed(4), sensor: h.seenBy, frp_mw: h.frp })),
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
            </>
          ),
          body: yr.data ? (
            <>
              <ActivityChart data={yr.data} show={show} selectedMonth={sel.month} onSelectMonth={(mm) => pick({ month: mm })} />
              <p className="mt-1 text-xs text-muted">
                Active fire cells per month, {sel.year}. VIIRS is harmonized to the MODIS scale
                {sel.year < 2012 ? "; VIIRS data starts in 2012." : "."}
              </p>
            </>
          ) : (
            <Placeholder className="h-60" />
          ),
        };
      case "surface":
        return {
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
            </>
          ),
          body: cal.data ? (
            <>
              <YearCalendar data={cal.data} mode={mode} selected={sel} onSelect={(year, month) => pick({ year, month })} />
              <RampLegend mode={mode} />
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
        <FireMap region={region} hotspots={points} sensor={onlySensor} />
      </div>

      {/* ===== Filters: Region / Year / Month ===== */}
      <div className="px-4 pt-4 lg:pointer-events-none lg:absolute lg:inset-x-0 lg:top-5 lg:z-[1100] lg:flex lg:justify-center lg:pl-[450px] lg:pr-6 min-[1800px]:px-6 lg:pt-0">
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
                <option key={mm} value={i + 1}>
                  {mm}
                </option>
              ))}
            </Select>
          </Field>
        </Panel>
      </div>

      {/* ===== Left panel ===== */}
      <div className="px-4 py-4 lg:absolute lg:bottom-5 lg:left-0 lg:top-5 lg:z-[1100] lg:w-[430px] lg:p-0">
        <Panel className="flex h-full flex-col overflow-y-auto px-6 py-5 lg:rounded-l-none lg:border-l-0">
          {/* Calendar */}
          <h2 className="text-center font-display text-xl 2xl:text-2xl">Burning activity</h2>
          <p className="mb-3 mt-1 text-center text-sm text-muted">
            {MONTH_NAMES[sel.month - 1]} {sel.year} · {region.name}
          </p>
          {mon.data ? <DayCalendar days={mon.data.days} selected={day} onSelect={setDay} /> : <Placeholder className="h-56" />}

          <div className="mt-3 flex flex-wrap justify-between gap-x-3 gap-y-1 text-xs text-muted">
            {DAY_LEVELS.map((l) => (
              <span key={l.key} className="inline-flex items-center gap-1.5">
                <span className={`h-3.5 w-3.5 rounded-full ${l.className} ${l.key === "low" ? "border border-line" : ""}`} />
                {l.label}
              </span>
            ))}
          </div>
          <p className="mt-2 text-sm">
            {hs.data ? `${points.length.toLocaleString("en")} hotspots on the map` : "Loading hotspots…"}
            {hs.data?.truncated ? ` (strongest of ${hs.data.total?.toLocaleString("en")} active cell-days)` : ""}
            {day ? ` · ${day}` : " · whole month"}
          </p>
          {day ? (
            <button onClick={() => setDay(null)} className="mt-1 self-start text-sm text-accent underline">
              Show whole month
            </button>
          ) : (
            <p className="mt-1 text-sm text-muted">Click a day to show it on the map</p>
          )}

          {/* Sensors + what the map colors mean */}
          <div className="mt-3 border-y border-line py-3">
            <div className="flex justify-center gap-10">
              <Checkbox label="MODIS" color="#f39314" checked={sensors.modis} onChange={(v) => setSensors({ ...sensors, modis: v })} />
              <Checkbox label="VIIRS" color="#ffd60a" checked={sensors.viirs} onChange={(v) => setSensors({ ...sensors, viirs: v })} />
            </div>
            {/* what the colors of the map cells mean */}
            <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-muted">
              {(["MODIS", "VIIRS", "BOTH"] as const).map((k) => (
                <span key={k} className="inline-flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-sm" style={{ background: SENSOR_COLORS[k] }} />
                  {k === "BOTH" ? "Both" : k}
                </span>
              ))}
              <span>· click a cell for details</span>
            </div>
          </div>

          {/* FRP */}
          <div className="border-b border-line py-3">
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
          <div className="border-b border-line py-3">
            <h3 className="mb-3 text-center font-display text-lg">Charts</h3>
            <div className="flex flex-wrap justify-center gap-3">
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
          <div className="sticky -bottom-5 -mx-6 mt-auto flex justify-center bg-surface px-6 py-4">
            <Button onClick={exportCsv} disabled={!hs.data || points.length === 0} className="inline-flex items-center gap-2">
              <FileIcon /> CSV File
            </Button>
          </div>
        </Panel>
      </div>

      {error && (
        <div role="alert" className="absolute bottom-5 right-5 z-[1100] rounded-2xl border border-red-500/40 bg-red-950/90 p-4 text-sm text-red-200">
          Could not load data: {error}
        </div>
      )}

      {/* ===== Chart windows ===== */}
      {windows.map((w) => {
        const cfg = CHARTS.find((c) => c.id === w.id)!;
        const idx = CHARTS.findIndex((c) => c.id === w.id);
        const content = renderWindow(w.id);
        return (
          <FloatingWindow
            key={w.id}
            title={cfg.title}
            actions={content.actions}
            initial={{ x: 470 + idx * 40, y: 100 + idx * 30 }}
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

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7" />
      <path d="M14 3v5h5M19 8v5" />
      <path d="M18 15v6m-3-3 3 3 3-3" />
    </svg>
  );
}
