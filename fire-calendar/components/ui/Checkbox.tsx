"use client";

/** Квадратная галочка как в макете (MODIS / VIIRS). */
export default function Checkbox({
  checked,
  onChange,
  label,
  color,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  /** цвет квадрата, когда отмечено */
  color: string;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-3 font-display text-lg">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
      <span
        className="flex h-6 w-6 items-center justify-center rounded-[3px] border-2 border-white transition peer-focus-visible:ring-2 peer-focus-visible:ring-accent"
        style={checked ? { background: color, borderColor: color } : undefined}
      >
        {checked && (
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="#111827" strokeWidth={3.5} aria-hidden>
            <path d="m5 12 5 5 9-10" />
          </svg>
        )}
      </span>
      {label}
    </label>
  );
}
