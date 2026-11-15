"use client";
// "Hotspot Telemetry" card: the individual NASA detections inside one clicked 0.1° map cell.
// The map shows one square per active cell and day (/api/hotspots/) — a grid cell, not a fire. This card
// asks the backend for the real detections in that cell (/api/detections/, only those inside the
// region's border), shows their own coordinates and hands them to the map, which marks them as dots.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { SENSOR_COLORS } from "@/lib/colors";
import type { Detection, Hotspot } from "@/types/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface Props {
  /** region id: in a region with a real border only the detections inside it are listed */
  region: string;
  cell: Hotspot;
  /** only one sensor ticked in the panel → ask only for that sensor */
  sensor?: "MODIS" | "VIIRS";
  onClose: () => void;
  /** the detections (real coordinates) and which one is shown, for the dots on the map */
  onPoints?: (points: Detection[], current: number) => void;
}

export default function HotspotCard({ region, cell, sensor, onClose, onPoints }: Props) {
  const res = useApi(`${region}-${cell.id}-${sensor ?? "all"}`, () => api.cellPoints(region, cell, sensor));
  const [i, setI] = useState(0);
  const list = res.data?.points ?? [];
  const current = Math.min(i, list.length - 1);
  const d: Detection | undefined = list[current];
  useEffect(() => {
    onPoints?.(list, current);
    // list changes identity only when the data arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res.data, current]);

  return (
    <div className="w-[min(380px,calc(100vw-2rem))] rounded-3xl border-2 border-accent bg-surface p-5 shadow-2xl shadow-black/60">
      {/* header */}
      <div className="mb-4 flex items-center gap-3">
        <h3 className="mr-auto font-display text-lg">Hotspot Telemetry</h3>
        {d && (
          <span
            className="rounded-full px-3 py-0.5 text-sm font-medium text-bg"
            style={{ background: SENSOR_COLORS[d.sensor] }}
          >
            {d.sensor}
          </span>
        )}
        <button onClick={onClose} aria-label="Close" className="rounded-md p-1 transition hover:bg-surface-2">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden>
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      </div>

      {res.error ? (
        <p className="text-sm text-red-300">Could not load the detections: {res.error}</p>
      ) : !res.data ? (
        <div className="h-36 animate-pulse rounded-2xl bg-surface-2/60" />
      ) : !d ? (
        <p className="text-sm text-muted">No individual detections for the selected sensors in this cell.</p>
      ) : (
        <>
          {/* where and when */}
          <dl className="grid grid-cols-[1.3fr_1fr_0.8fr] divide-x divide-line text-sm">
            <Item label="Detection at">
              {fmtLat(d.latitude)},<br />
              {fmtLon(d.longitude)}
            </Item>
            <Item label="Date">{fmtDate(d.acq_date)}</Item>
            <Item label="Time">
              {d.acq_time.slice(0, 2)}:{d.acq_time.slice(2)}
              <br />
              UTC
            </Item>
          </dl>

          <hr className="my-4 border-line" />

          {/* how strong and how sure */}
          <dl className="grid grid-cols-2 divide-x divide-line">
            <Item label="FRP Intensity" big className="text-modis">
              {d.frp_mw === null ? "—" : `${d.frp_mw.toLocaleString("en", { maximumFractionDigits: 1 })} MW`}
            </Item>
            <Item label="Confidence" big className="text-accent">
              {fmtConfidence(d)}
            </Item>
          </dl>

          {/* footer: satellite and paging */}
          <div className="mt-4 flex items-center justify-between gap-3 text-xs text-muted">
            <span>
              {d.satellite} · {d.daynight === "D" ? "day" : d.daynight === "N" ? "night" : "—"} pass
            </span>
            {list.length > 1 && (
              <span className="flex items-center gap-2">
                <PagerButton label="Previous detection" disabled={i === 0} onClick={() => setI(i - 1)} dir="left" />
                <span className="tabular-nums text-white">
                  {i + 1} / {list.length}
                  {res.data.has_more ? "+" : ""}
                </span>
                <PagerButton
                  label="Next detection"
                  disabled={i >= list.length - 1}
                  onClick={() => setI(i + 1)}
                  dir="right"
                />
              </span>
            )}
          </div>
          <p className="mt-2 text-xs text-muted">
            {list.length} detection{list.length === 1 ? "" : "s"} in this 0.1° grid cell on this day
            {d.product === "NRT" ? " · preliminary (NRT) data" : ""}
            {cell.edge ? " · the border crosses this cell: only detections inside the region are counted" : ""}
          </p>
        </>
      )}
    </div>
  );
}

function Item({
  label,
  big,
  className = "",
  children,
}: {
  label: string;
  big?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="px-3 first:pl-0 last:pr-0">
      <dt className="mb-1 text-sm">{label}</dt>
      <dd className={big ? `text-xl font-semibold ${className}` : `leading-snug text-muted ${className}`}>{children}</dd>
    </div>
  );
}

function PagerButton({ label, dir, disabled, onClick }: { label: string; dir: "left" | "right"; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="rounded-md border border-line p-1 text-white transition hover:bg-surface-2 disabled:opacity-30"
    >
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden>
        <path d={dir === "left" ? "m15 6-6 6 6 6" : "m9 6 6 6-6 6"} />
      </svg>
    </button>
  );
}

// ---------- formatting ----------

function fmtLat(v: number) {
  return `${Math.abs(v).toFixed(4)}°${v >= 0 ? "N" : "S"}`;
}
function fmtLon(v: number) {
  return `${Math.abs(v).toFixed(4)}°${v >= 0 ? "E" : "W"}`;
}
function fmtDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/**
 * MODIS reports a percentage; NASA groups it as low < 30, nominal 30–79, high ≥ 80.
 * VIIRS reports only the level (l / n / h).
 */
function fmtConfidence(d: Detection) {
  const c = d.confidence;
  if (c === null) return "—";
  if (d.sensor === "MODIS") {
    const p = Number(c);
    return `${p}% ${p >= 80 ? "High" : p >= 30 ? "Nominal" : "Low"}`;
  }
  return { l: "Low", n: "Nominal", h: "High" }[c] ?? c;
}
