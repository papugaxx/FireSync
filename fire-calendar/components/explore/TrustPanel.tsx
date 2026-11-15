"use client";
// "Data & method" window (Scientific Trust Layer): where the numbers come from, how complete the
// selected month is, whether the MODIS ↔ VIIRS harmonization passed its independent check, and
// what the numbers do NOT mean. Everything shown is read from the backend responses; no scores are invented.
import type { CalendarResponse, DayValue } from "@/types/api";

interface Props {
  harmonization: CalendarResponse["harmonization"] | null;
  days: DayValue[] | null;
  monthLabel: string;
  regionName: string;
  firstDay: string;
  lastDay: string;
  viirsFirstDay: string;
}

export default function TrustPanel({ harmonization: h, days, monthLabel, regionName, firstDay, lastDay, viirsFirstDay }: Props) {
  // ---- completeness of the selected month, from the per-day status the backend sends ----
  const count = (pred: (d: DayValue) => boolean) => (days ?? []).filter(pred).length;
  const total = days?.length ?? 0;
  const future = count((d) => d.status === "future");
  const past = total - future;
  const withData = count((d) => d.harmonized !== null || d.modis !== null || d.viirs !== null);
  const partial = count((d) => d.status === "partial");
  const missing = past - withData;
  const obsState = !days ? null : missing === 0 && partial === 0 ? "complete" : withData === 0 ? "none" : "partial";

  // ---- harmonization state, by plain rules ----
  const harmState = !h
    ? null
    : h.status === "validated"
      ? "validated"
      : h.experiment_status === "insufficient_data"
        ? "insufficient"
        : "experimental";
  const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));

  return (
    <div className="space-y-5 text-sm">
      {/* 1. sources */}
      <section>
        <h4 className="mb-2 font-display text-sm">Sources</h4>
        <ul className="space-y-1 text-muted">
          <li>
            <span className="text-modis">MODIS</span> Terra + Aqua (≈1 km pixels), NASA FIRMS, from {firstDay}
          </li>
          <li>
            <span className="text-viirs">VIIRS</span> NOAA-20 (375 m pixels), NASA FIRMS, from {viirsFirstDay}
          </li>
          <li>Latest stored day: {lastDay} (UTC). Recent days come from NASA&apos;s near-real-time (NRT) feed and are preliminary.</li>
        </ul>
      </section>

      {/* 2. completeness */}
      <section>
        <h4 className="mb-2 font-display text-sm">
          Observations · {regionName}, {monthLabel}
        </h4>
        {!days ? (
          <p className="text-muted">Loading…</p>
        ) : (
          <>
            <State
              tone={obsState === "complete" ? "good" : obsState === "none" ? "bad" : "warn"}
              text={obsState === "complete" ? "Complete observations" : obsState === "none" ? "No observations" : "Partial observations"}
            />
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-muted sm:grid-cols-4">
              <Item k="Days with data" v={`${withData} / ${past}`} />
              <Item k="Missing days" v={String(missing)} />
              <Item k="Partial days" v={String(partial)} />
              <Item k="Not yet happened" v={String(future)} />
            </dl>
          </>
        )}
      </section>

      {/* 3. harmonization */}
      <section>
        <h4 className="mb-2 font-display text-sm">MODIS ↔ VIIRS harmonization · {regionName}</h4>
        {!h ? (
          <p className="text-muted">Loading…</p>
        ) : (
          <>
            <State
              tone={harmState === "validated" ? "good" : harmState === "insufficient" ? "bad" : "warn"}
              text={
                harmState === "validated"
                  ? "Validated for this region: k is applied"
                  : harmState === "insufficient"
                    ? "Insufficient evidence: not enough paired days"
                    : "Experimental: did not beat the check, not applied"
              }
            />
            <p className="mt-2 text-muted">
              Method: on days when both sensors observed, MODIS active cells ≈ k × VIIRS active cells. k is fitted on the
              earlier two thirds of the paired days and tested on the last third, which it never saw.
              {harmState === "validated"
                ? " Days without MODIS are shown on the MODIS scale as k × VIIRS."
                : " Without a validated k, VIIRS is shown only as its own raw series, never as MODIS-scale values."}
            </p>
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-muted sm:grid-cols-3">
              <Item k="k" v={fmt(h.coefficient, 3)} />
              <Item k="R² (held-out)" v={fmt(h.r2)} />
              <Item k="MAE raw VIIRS" v={fmt(h.holdout_mae?.raw_viirs, 1)} />
              <Item k="MAE scaled VIIRS" v={fmt(h.holdout_mae?.scaled_viirs, 1)} />
              <Item k="Fit period" v={period(h.fit_period)} />
              <Item k="Test period" v={period(h.holdout_period)} />
            </dl>
            <p className="mt-1 text-xs text-muted">MAE in active cells per day; lower is better. Check status: {h.experiment_status ?? h.status}.</p>
          </>
        )}
      </section>

      {/* 4. limits */}
      <section>
        <h4 className="mb-2 font-display text-sm">What the numbers mean, and do not</h4>
        <ul className="list-disc space-y-1 pl-5 text-muted">
          <li>A hotspot is a satellite thermal detection, not necessarily a separate wildfire.</li>
          <li>An active cell is a 0.1° grid square (≈ 11 km) with at least one detection that day; active cell-days are not a count of fire events.</li>
          <li>FRP is radiated power in MW, not burned area.</li>
          <li>Medians use complete months only and need at least 3 years; missing data is never counted as zero.</li>
          <li>This is historical and comparative analysis, not a fire forecast.</li>
        </ul>
      </section>
    </div>
  );
}

function State({ tone, text }: { tone: "good" | "warn" | "bad"; text: string }) {
  const c = tone === "good" ? "bg-emerald-400" : tone === "warn" ? "bg-amber-400" : "bg-red-400";
  return (
    <p className="inline-flex items-center gap-2 rounded-full border border-line bg-bg/60 px-3 py-1">
      <span className={`h-2.5 w-2.5 rounded-full ${c}`} aria-hidden />
      {text}
    </p>
  );
}

function Item({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-xs">{k}</dt>
      <dd className="text-white tabular-nums">{v}</dd>
    </div>
  );
}

function period(p?: [string | null, string | null]) {
  return p && p[0] && p[1] ? `${p[0]} – ${p[1]}` : "—";
}
