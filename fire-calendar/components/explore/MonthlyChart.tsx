"use client";
import { MONTHS } from "@/lib/colors";

const CHART = { above: "#f03b20", normal: "#feb24c" }; // TODO: цвета из дизайна

interface Props {
  year: number;
  values: (number | null)[];
  median: number[];
  selectedMonth: number;
}

// Столбики выбранного года + линия медианы. Чистый SVG, без библиотек.
export default function MonthlyChart({ year, values, median, selectedMonth }: Props) {
  const W = 600, H = 220, P = { l: 40, r: 10, t: 10, b: 24 };
  const max = Math.max(1, ...values.map((v) => v ?? 0), ...median) * 1.1;
  const bw = (W - P.l - P.r) / 12;
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / max);
  const ticks = [0, 0.5, 1].map((t) => Math.round(max * t));

  const medPath = median
    .map((m, i) => `${i ? "L" : "M"}${P.l + bw * i + bw / 2},${y(m)}`)
    .join(" ");

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Active fire cells per month in ${year}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} stroke="#ddd" />
            <text x={P.l - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="currentColor">
              {t}
            </text>
          </g>
        ))}
        {values.map((v, i) => {
          if (v === null) return null;
          const above = v > median[i];
          return (
            <rect
              key={i}
              x={P.l + bw * i + bw * 0.18}
              width={bw * 0.64}
              y={y(v)}
              height={y(0) - y(v)}
              rx={3}
              fill={above ? CHART.above : CHART.normal}
              opacity={i + 1 === selectedMonth ? 1 : 0.65}
            >
              <title>{`${MONTHS[i]} ${year}: ${v} (median ${median[i]})`}</title>
            </rect>
          );
        })}
        <path d={medPath} fill="none" stroke="currentColor" strokeWidth={2} strokeDasharray="4 4" />
        {MONTHS.map((m, i) => (
          <text key={m} x={P.l + bw * i + bw / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="currentColor">
            {m}
          </text>
        ))}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-4 text-xs">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5" style={{ background: CHART.above }} /> above median</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5" style={{ background: CHART.normal }} /> at or below median</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-4 border-t-2 border-dashed border-current" /> {"multi-year median"}</span>
      </figcaption>
    </figure>
  );
}
