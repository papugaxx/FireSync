"use client";
import type { MonthlyResponse } from "@/types/api";

const C = { grid: "#2a5bd7", modis: "#f39314", viirs: "#ffd60a", accent: "#17b6d9" };

interface Props {
  data: MonthlyResponse;
  show: { modis: boolean; viirs: boolean };
  selectedMonth: number;
  onSelectMonth: (m: number) => void;
}

// Линейный график "Monthly activity over the year". Чистый SVG, без библиотек.
export default function ActivityChart({ data, show, selectedMonth, onSelectMonth }: Props) {
  const W = 1300, H = 400, P = { l: 20, r: 20, t: 30, b: 70 };
  const series = [
    { key: "modis" as const, color: C.modis, on: show.modis },
    { key: "viirs" as const, color: C.viirs, on: show.viirs },
  ];
  const all = data.months.flatMap((m) => [m.modis ?? 0, m.viirs ?? 0]);
  const max = Math.max(1, ...all) * 1.6; // запас сверху, как в макете
  const x = (i: number) => P.l + 30 + ((W - P.l - P.r - 50) / 11) * i;
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / max);
  const baseY = H - P.b;

  const path = (key: "modis" | "viirs") => {
    let d = "";
    data.months.forEach((m, i) => {
      const v = m[key];
      if (v === null) return;
      d += `${d ? "L" : "M"}${x(i)},${y(v)}`;
    });
    return d;
  };

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Monthly fire activity in ${data.year}`}>
      {/* пунктирные уровни */}
      {[0.25, 0.5, 0.75].map((t) => (
        <line key={t} x1={P.l + 10} x2={W - P.r} y1={y(max * t)} y2={y(max * t)} stroke={C.grid} strokeWidth={2} strokeDasharray="4 8" />
      ))}
      {/* оси */}
      <line x1={P.l} x2={P.l} y1={P.t - 20} y2={baseY} stroke={C.grid} strokeWidth={2} />
      <line x1={P.l} x2={W - P.r} y1={baseY} y2={baseY} stroke={C.grid} strokeWidth={2} />

      {series.map((s) => (s.on ? <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth={3} strokeLinejoin="round" /> : null))}

      {/* точки выбранного месяца */}
      {series.map((s) => {
        const v = data.months[selectedMonth - 1]?.[s.key];
        if (!s.on || v === null || v === undefined) return null;
        return (
          <circle key={s.key} cx={x(selectedMonth - 1)} cy={y(v)} r={8} fill={s.color} stroke="#111827" strokeWidth={3}>
            <title>{`${s.key.toUpperCase()}: ${v}`}</title>
          </circle>
        );
      })}

      {/* подписи месяцев, кликабельные */}
      {data.months.map((m, i) => {
        const isSel = m.month === selectedMonth;
        return (
          <g key={m.month} onClick={() => onSelectMonth(m.month)} className="cursor-pointer">
            <title>{`MODIS ${m.modis ?? "—"} · VIIRS ${m.viirs ?? "—"}`}</title>
            <rect x={x(i) - 26} y={baseY + 12} width={52} height={50} rx={8} fill={isSel ? C.accent : "transparent"} />
            <text x={x(i)} y={baseY + 45} textAnchor="middle" fontSize={26} fill="#fff">
              {m.month}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
