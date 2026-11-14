"use client";

interface Props {
  min: number;
  max: number;
  step?: number;
  value: [number, number];
  onChange: (v: [number, number]) => void;
  /** label for the rightmost value, e.g. "500+" */
  format?: (v: number) => string;
  label: string;
}

/** Slider with two thumbs (a "from–to" range). Thumb styles are in globals.css (.range-dual). */
export default function RangeSlider({ min, max, step = 1, value, onChange, format = String, label }: Props) {
  const [lo, hi] = value;
  const pct = (v: number) => ((v - min) / (max - min)) * 100;

  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <span>{label}</span>
        <span className="text-accent">
          {format(lo)} – {format(hi)}
        </span>
      </div>
      <div className="range-dual relative h-8">
        {/* track and the highlighted segment */}
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-surface-2" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-accent"
          style={{ left: `${pct(lo)}%`, right: `${100 - pct(hi)}%` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={lo}
          aria-label={`${label} minimum`}
          onChange={(e) => onChange([Math.min(+e.target.value, hi - step), hi])}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={hi}
          aria-label={`${label} maximum`}
          onChange={(e) => onChange([lo, Math.max(+e.target.value, lo + step)])}
        />
      </div>
      <div className="flex justify-between text-xs text-muted">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
    </div>
  );
}
