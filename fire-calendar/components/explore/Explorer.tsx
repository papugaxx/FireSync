"use client";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { api, downloadCsv } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { REGIONS } from "@/lib/mock";
import { MONTHS } from "@/lib/colors";
import RampLegend from "./RampLegend";
import SensorLegend from "./SensorLegend";
import { Button, Card, Field, Placeholder, Select, Stat } from "@/components/ui";
import YearCalendar from "./YearCalendar";
import MonthlyChart from "./MonthlyChart";
import DayStrip from "./DayStrip";

const FireMap = dynamic(() => import("./FireMap"), {
  ssr: false,
  loading: () => <Placeholder className="h-full" label="Loading map…" />,
});

export default function Explorer() {
  const [regionId, setRegionId] = useState(REGIONS[0].id);
  const [sel, setSel] = useState({ year: 2024, month: 8 });
  const [mode, setMode] = useState<"count" | "anomaly">("count");

  const region = REGIONS.find((r) => r.id === regionId)!;
  const monthKey = `${regionId}-${sel.year}-${sel.month}`;

  const cal = useApi(regionId, () => api.calendar(regionId));
  const mon = useApi(monthKey, () => api.month(regionId, sel.year, sel.month));
  const hs = useApi(monthKey, () => api.hotspots(regionId, sel.year, sel.month));

  const calendar = cal.data ?? null;
  const month = mon.data ?? null;
  const hotspots = hs.data ?? null;
  const error = cal.error ?? mon.error ?? hs.error ?? null;

  const stats = useMemo(() => {
    if (!calendar) return null;
    const yearRow = calendar.years.find((y) => y.year === sel.year);
    const value = yearRow?.months[sel.month - 1] ?? null;
    const med = calendar.median[sel.month - 1];
    const totals = calendar.years.map((y) => ({ year: y.year, sum: y.months.reduce<number>((a, v) => a + (v ?? 0), 0) }));
    const topYear = totals.reduce((a, b) => (b.sum > a.sum ? b : a));
    const peakMonth = calendar.median.indexOf(Math.max(...calendar.median));
    return {
      value,
      med,
      diff: value !== null && med ? Math.round((value / med - 1) * 100) : null,
      topYear,
      peakMonth,
      yearValues: yearRow?.months ?? [],
    };
  }, [calendar, sel]);

  function exportCsv() {
    if (!hotspots) return;
    downloadCsv(
      `firesync_${regionId}_${sel.year}-${String(sel.month).padStart(2, "0")}.csv`,
      hotspots.hotspots.map((h) => ({ date: h.date, lat: h.lat.toFixed(4), lon: h.lon.toFixed(4), sensor: h.seenBy, frp: h.frp })),
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      {/* Панель управления */}
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Burning activity calendar</h1>
          <p className="text-sm">Harmonized MODIS + VIIRS active fire cells · sample data</p>
        </div>
        <div className="ml-auto flex flex-wrap items-end gap-3">
          <Field label="Region">
            <Select value={regionId} onChange={(e) => setRegionId(e.target.value)}>
              {REGIONS.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Year">
            <Select value={sel.year} onChange={(e) => setSel({ ...sel, year: +e.target.value })}>
              {calendar?.years.map((y) => <option key={y.year}>{y.year}</option>) ?? <option>{sel.year}</option>}
            </Select>
          </Field>
          <Field label="Month">
            <Select value={sel.month} onChange={(e) => setSel({ ...sel, month: +e.target.value })}>
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </Select>
          </Field>
          <Button onClick={exportCsv} disabled={!hotspots}>
            Download CSV
          </Button>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 border p-3 text-sm">
          Could not load data: {error}
        </div>
      )}

      {/* Ключевые цифры */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={`${MONTHS[sel.month - 1]} ${sel.year}`} value={stats?.value ?? "—"} hint="active fire cells" />
        <Stat
          label="vs historical median"
          value={stats?.diff == null ? "—" : `${stats.diff > 0 ? "+" : ""}${stats.diff}%`}
          hint={`median ${stats?.med ?? "—"}`}
        />
        <Stat label="Peak fire season" value={stats ? MONTHS[stats.peakMonth] : "—"} hint="highest median month" />
        <Stat label="Most active year" value={stats?.topYear.year ?? "—"} hint={stats ? `${stats.topYear.sum} cells total` : ""} />
      </div>

      {/* Карта + дни месяца */}
      <div className="mb-6 grid gap-6 lg:grid-cols-3">
        <Card className="h-[420px] lg:col-span-2">
          <FireMap region={region} hotspots={hotspots?.hotspots ?? []} />
        </Card>
        <Card title={`${MONTHS[sel.month - 1]} ${sel.year} by day`}>
          {month ? <DayStrip days={month.days} /> : <Placeholder className="h-64" />}
          <div className="mt-4 text-sm">
            <SensorLegend />
            <p className="mt-2">{hotspots ? `${hotspots.hotspots.length} hotspots on the map` : "Loading hotspots…"}</p>
          </div>
        </Card>
      </div>

      {/* Календарь лет + график */}
      <div className="grid gap-6 lg:grid-cols-5">
        <Card
          className="lg:col-span-3"
          title="Year × month calendar"
          action={
            <div className="flex gap-1">
              {(["count", "anomaly"] as const).map((m) => (
                <Button key={m} onClick={() => setMode(m)} aria-pressed={mode === m} className={mode === m ? "font-semibold" : ""}>
                  {m === "count" ? "Activity" : "Anomaly"}
                </Button>
              ))}
            </div>
          }
        >
          {calendar ? (
            <>
              <YearCalendar data={calendar} mode={mode} selected={sel} onSelect={(year, month) => setSel({ year, month })} />
              <RampLegend mode={mode} />
            </>
          ) : (
            <Placeholder className="h-96" />
          )}
        </Card>
        <div className="space-y-6 lg:col-span-2">
          <Card title={`${sel.year} vs median`}>
            {stats ? (
              <MonthlyChart year={sel.year} values={stats.yearValues} median={calendar!.median} selectedMonth={sel.month} />
            ) : (
              <Placeholder className="h-52" />
            )}
          </Card>
          <Card title="Harmonization">
            {calendar ? (
              <dl className="grid grid-cols-2 gap-y-2 text-sm">
                <dt>Method</dt>
                <dd>{calendar.harmonization.method}</dd>
                <dt>Validation R²</dt>
                <dd>{calendar.harmonization.r2}</dd>
                <dt>Status</dt>
                <dd>
                  {calendar.harmonization.status}
                </dd>
                <dt>Grid</dt>
                <dd>0.1° cells, daily</dd>
              </dl>
            ) : (
              <Placeholder className="h-24" />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
