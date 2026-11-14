"use client";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { api, downloadCsv } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { REGIONS, YEARS } from "@/lib/mock";
import { MONTHS } from "@/lib/colors";
import { Button, Card, Field, Panel, Placeholder, Select, Toggle } from "@/components/ui";
import DayCalendar from "./DayCalendar";
import ActivityChart from "./ActivityChart";
import YearCalendar from "./YearCalendar";
import RampLegend from "./RampLegend";

const FireMap = dynamic(() => import("./FireMap"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-[#0b2238]" />,
});

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export default function Explorer() {
  const [regionId, setRegionId] = useState("world");
  const [sel, setSel] = useState({ year: 2024, month: 8 });
  const [day, setDay] = useState<string | null>(null); // выбранный день в календаре или весь месяц
  const [show, setShow] = useState({ modis: true, viirs: true });
  const [mode, setMode] = useState<"count" | "anomaly">("count");

  const region = REGIONS.find((r) => r.id === regionId)!;
  const monthKey = `${regionId}-${sel.year}-${sel.month}`;

  const cal = useApi(regionId, () => api.calendar(regionId));
  const mon = useApi(monthKey, () => api.month(regionId, sel.year, sel.month));
  const hs = useApi(monthKey, () => api.hotspots(regionId, sel.year, sel.month));
  const yr = useApi(`${regionId}-${sel.year}`, () => api.monthly(regionId, sel.year));
  const error = cal.error ?? mon.error ?? hs.error ?? yr.error ?? null;

  // точки на карте: за весь месяц или за выбранный день
  const points = useMemo(() => {
    const all = hs.data?.hotspots ?? [];
    return day ? all.filter((h) => h.date === day) : all;
  }, [hs.data, day]);

  function pick(next: Partial<typeof sel>) {
    setSel({ ...sel, ...next });
    setDay(null);
  }

  function exportCsv() {
    const tag = day ?? `${sel.year}-${String(sel.month).padStart(2, "0")}`;
    downloadCsv(
      `${regionId}_${tag}_hotspots.csv`,
      points.map((h) => ({ date: h.date, latitude: h.lat.toFixed(4), longitude: h.lon.toFixed(4), sensor: h.seenBy, frp: h.frp })),
    );
  }

  return (
    <div className="pb-16">
      {/* ===== Карта с плавающими панелями ===== */}
      <section className="relative lg:h-[calc(100vh-5rem)] lg:min-h-[720px]">
        <div className="h-[60vh] lg:absolute lg:inset-0 lg:h-auto">
          <FireMap region={region} hotspots={points} />
        </div>

        {/* Фильтры: Region / Year / Month */}
        <div className="px-4 pt-4 lg:pointer-events-none lg:absolute lg:inset-x-0 lg:top-5 lg:z-[1100] lg:flex lg:justify-center lg:pl-[440px] lg:pr-6 lg:pt-0">
          <Panel className="pointer-events-auto flex flex-wrap gap-3 p-2.5">
            <Field label="Region">
              <Select value={regionId} onChange={(e) => (setRegionId(e.target.value), setDay(null))}>
                {REGIONS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Year">
              <Select value={sel.year} onChange={(e) => pick({ year: +e.target.value })}>
                {YEARS.map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </Select>
            </Field>
            <Field label="Month">
              <Select value={sel.month} onChange={(e) => pick({ month: +e.target.value })}>
                {MONTH_NAMES.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>
          </Panel>
        </div>

        {/* Левая панель: Burning activity */}
        <div className="px-4 pt-4 lg:absolute lg:bottom-24 lg:left-0 lg:top-5 lg:z-[1100] lg:w-[410px] lg:p-0">
          <Panel className="flex h-full flex-col p-6 lg:rounded-l-none lg:border-l-0">
            <h2 className="mb-6 text-center font-display text-2xl">Burning activity</h2>
            <p className="-mt-4 mb-5 text-center text-sm text-muted">
              {MONTH_NAMES[sel.month - 1]} {sel.year} · {region.name}
            </p>

            {mon.data ? <DayCalendar days={mon.data.days} selected={day} onSelect={setDay} /> : <Placeholder className="h-64" />}

            <div className="mt-6 space-y-2 text-sm text-muted">
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <LegendChip className="bg-accent" label="High activity" />
                <LegendChip className="bg-accent-2" label="Fires detected" />
                <LegendChip className="border border-line" label="No fires" />
              </div>
              <p>
                {hs.data ? `${points.length} hotspots on the map` : "Loading hotspots…"}
                {day ? ` · ${day}` : " · whole month"}
              </p>
              {day ? (
                <button onClick={() => setDay(null)} className="text-accent underline">
                  Show whole month
                </button>
              ) : (
                <p>Click a day to show it on the map.</p>
              )}
            </div>

            <div className="mt-auto flex justify-center pt-6">
              <Button onClick={exportCsv} disabled={!hs.data} className="inline-flex items-center gap-2">
                <FileIcon /> CSV File
              </Button>
            </div>
          </Panel>
        </div>
      </section>

      {error && (
        <div role="alert" className="mx-auto mt-6 max-w-5xl rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          Could not load data: {error}
        </div>
      )}

      {/* ===== График по месяцам ===== */}
      <div className="mx-auto mt-10 max-w-6xl px-4">
        <Card
          title="Monthly activity over the year"
          action={
            <div className="flex gap-4">
              <Toggle active={show.modis} color="#f39314" onClick={() => setShow({ ...show, modis: !show.modis })}>
                MODIS
              </Toggle>
              <Toggle active={show.viirs} color="#ffd60a" onClick={() => setShow({ ...show, viirs: !show.viirs })}>
                VIIRS
              </Toggle>
            </div>
          }
        >
          {yr.data ? (
            <ActivityChart data={yr.data} show={show} selectedMonth={sel.month} onSelectMonth={(m) => pick({ month: m })} />
          ) : (
            <Placeholder className="h-72" />
          )}
          {yr.data && sel.year < 2012 && <p className="mt-2 text-sm text-muted">VIIRS data starts in 2012.</p>}
        </Card>
      </div>

      {/* ===== Календарь лет (в макете пока нет, но это главное по заданию) ===== */}
      <div className="mx-auto mt-8 max-w-6xl px-4">
        <Card
          title="Burning calendar 2001–2025"
          action={
            <div className="flex gap-3">
              <Toggle active={mode === "count"} color="#17b6d9" onClick={() => setMode("count")}>
                Activity
              </Toggle>
              <Toggle active={mode === "anomaly"} color="#17b6d9" onClick={() => setMode("anomaly")}>
                Anomaly
              </Toggle>
            </div>
          }
        >
          {cal.data ? (
            <>
              <YearCalendar data={cal.data} mode={mode} selected={sel} onSelect={(year, month) => pick({ year, month })} />
              <RampLegend mode={mode} />
            </>
          ) : (
            <Placeholder className="h-96" />
          )}
          <p className="mt-3 text-sm text-muted">
            Click a cell to open that month. {MONTHS[sel.month - 1]} {sel.year} is selected.
          </p>
        </Card>
      </div>
    </div>
  );
}

function LegendChip({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-3 w-3 rounded-sm ${className}`} />
      {label}
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
