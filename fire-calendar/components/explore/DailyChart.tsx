"use client";
// Daily MODIS / VIIRS active cells over any period (the "Area & dates" report). Plain SVG.
import type { RangeDay } from "@/types/api";

const C = { grid: "#2a5bd7", modis: "#f39314", viirs: "#ffd60a", muted: "#8b95a8" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function DailyChart({ days, show }: { days: RangeDay[]; show: { modis: boolean; viirs: boolean } }) {
  const W = 640, H = 260, P = { l: 56, r: 16, t: 16, b: 40 };
  const n = days.length;
  const values = days.flatMap((d) => [show.modis ? (d.modis.active_cells ?? 0) : 0, show.viirs ? (d.viirs.active_cells ?? 0) : 0]);
  const max = Math.max(1, ...values) * 1.12;
  const x = (i: number) => P.l + (n <= 1 ? 0 : ((W - P.l - P.r) * i) / (n - 1));
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / max);
  const baseY = H - P.b;

  // a line per sensor; days that are not stored break the line instead of dropping to zero
  const path = (ch: "modis" | "viirs") => {
    let d = "";
    let pen = false;
    days.forEach((day, i) => {
      const v = day[ch].active_cells;
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  // x labels: about 8, at month starts when the period is long, otherwise evenly spaced days
  const all = days.map((d, i) => ({ d, i }));
  const candidates = n > 62 ? all.filter(({ d }) => d.date.endsWith("-01")) : all;
  const every = Math.max(1, Math.ceil(candidates.length / 8));
  const labels = candidates.filter((_, k) => k % every === 0);
  const longPeriod = n > 400;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]" role="img" aria-label="Active fire cells per day">
      {[0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={y(max * t * 0.89)} y2={y(max * t * 0.89)} stroke={C.grid} strokeWidth={1} strokeDasharray="3 6" />
          <text x={P.l - 8} y={y(max * t * 0.89) + 4} textAnchor="end" fontSize={12} fill={C.muted}>
            {Math.round(max * t * 0.89).toLocaleString("en")}
          </text>
        </g>
      ))}
      <line x1={P.l} x2={P.l} y1={P.t} y2={baseY} stroke={C.grid} strokeWidth={2} />
      <line x1={P.l} x2={W - P.r} y1={baseY} y2={baseY} stroke={C.grid} strokeWidth={2} />
      {show.modis && <path d={path("modis")} fill="none" stroke={C.modis} strokeWidth={n > 120 ? 1.2 : 2} strokeLinejoin="round" />}
      {show.viirs && <path d={path("viirs")} fill="none" stroke={C.viirs} strokeWidth={n > 120 ? 1.2 : 2} strokeLinejoin="round" />}
      {labels.map(({ d, i }) => {
        const [yy, mm, dd] = d.date.split("-").map(Number);
        const text = n > 62 ? (longPeriod ? `${MONTHS[mm - 1]} ${String(yy).slice(2)}` : MONTHS[mm - 1]) : `${dd} ${MONTHS[mm - 1]}`;
        return (
          <text key={d.date} x={x(i)} y={baseY + 22} textAnchor="middle" fontSize={12} fill={C.muted}>
            {text}
          </text>
        );
      })}
    </svg>
  );
}
