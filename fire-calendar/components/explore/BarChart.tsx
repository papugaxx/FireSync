"use client";
// Универсальный столбчатый график в стиле макета (оси и пунктир синие).
// Используется в окнах Surface, FRP и Trend & Anomaly.

const C = { grid: "#2a5bd7", accent: "#17b6d9" };

export interface BarChartProps {
  labels: (string | number)[];
  values: (number | null)[];
  color: string;
  /** необязательная вторая серия точками (например максимум FRP) */
  dots?: (number | null)[];
  dotColor?: string;
  /** необязательная прямая (линия тренда): значения в начале и в конце */
  trend?: [number, number];
  selected?: number; // индекс
  onSelect?: (i: number) => void;
  format?: (v: number) => string;
  /** показывать подпись каждой n-й метки (для 25 лет удобно 4) */
  labelEvery?: number;
}

export default function BarChart({
  labels,
  values,
  color,
  dots,
  dotColor = "#ffd60a",
  trend,
  selected,
  onSelect,
  format = (v) => Math.round(v).toLocaleString("en"),
  labelEvery = 1,
}: BarChartProps) {
  const W = 900, H = 300, P = { l: 70, r: 15, t: 20, b: 50 };
  const n = values.length;
  const max = Math.max(1, ...values.map((v) => v ?? 0), ...(dots ?? []).map((v) => v ?? 0)) * 1.15;
  const step = (W - P.l - P.r) / n;
  const x = (i: number) => P.l + step * i + step / 2;
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / max);
  const baseY = H - P.b;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[560px]" role="img">
      {[0.33, 0.66, 1].map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={y(max * t * 0.87)} y2={y(max * t * 0.87)} stroke={C.grid} strokeWidth={1.5} strokeDasharray="3 6" />
          <text x={P.l - 8} y={y(max * t * 0.87) + 4} textAnchor="end" fontSize={13} fill="#8b95a8">
            {format(max * t * 0.87)}
          </text>
        </g>
      ))}
      <line x1={P.l} x2={P.l} y1={P.t} y2={baseY} stroke={C.grid} strokeWidth={2} />
      <line x1={P.l} x2={W - P.r} y1={baseY} y2={baseY} stroke={C.grid} strokeWidth={2} />

      {values.map((v, i) =>
        v === null ? null : (
          <rect
            key={i}
            x={x(i) - step * 0.32}
            width={step * 0.64}
            y={y(v)}
            height={baseY - y(v)}
            rx={3}
            fill={color}
            opacity={selected === undefined || selected === i ? 1 : 0.55}
          >
            <title>{`${labels[i]}: ${format(v)}${dots?.[i] != null ? ` · max ${format(dots[i]!)}` : ""}`}</title>
          </rect>
        ),
      )}

      {dots?.map((v, i) =>
        v === null ? null : <circle key={i} cx={x(i)} cy={y(v)} r={5} fill={dotColor} stroke="#111827" strokeWidth={2} />,
      )}

      {trend && (
        <line x1={x(0)} x2={x(n - 1)} y1={y(trend[0])} y2={y(trend[1])} stroke="#fff" strokeWidth={2} strokeDasharray="8 6" />
      )}

      {labels.map((l, i) => {
        const isSel = selected === i;
        if (!isSel && i % labelEvery !== 0) return null;
        return (
          <g key={i} onClick={() => onSelect?.(i)} className={onSelect ? "cursor-pointer" : ""}>
            <rect x={x(i) - 22} y={baseY + 8} width={44} height={30} rx={6} fill={isSel ? C.accent : "transparent"} />
            <text x={x(i)} y={baseY + 28} textAnchor="middle" fontSize={15} fill="#fff">
              {l}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Линейная регрессия: значения прямой тренда в первой и последней точке. */
export function linearTrend(values: number[]): [number, number] {
  const n = values.length;
  const mx = (n - 1) / 2;
  const my = values.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  values.forEach((v, i) => {
    num += (i - mx) * (v - my);
    den += (i - mx) ** 2;
  });
  const k = den ? num / den : 0;
  return [my - k * mx, my + k * (n - 1 - mx)];
}
