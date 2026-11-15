"use client";
import type { DayValue } from "@/types/api";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/**
 * Month calendar by day. Days with fires are split into three equal groups:
 *  High   — turquoise (top third)
 *  Medium — blue
 *  Low    — dark
 * No fill — data, but no fires (a measured zero).
 * Days without a value say why (DAY_STATES): still downloading, not published by NASA yet, or no observations.
 * A dot under the number: partial day (one sensor still to come, or NASA is still adding passes).
 */
export const DAY_LEVELS = [
  { key: "high", label: "High activity", className: "bg-accent text-bg font-semibold" },
  { key: "medium", label: "Medium activity", className: "bg-accent-2 text-white" },
  { key: "low", label: "Low activity", className: "bg-bg" },
] as const;

/** How days WITHOUT a value are drawn: the reason matters (see DayStatus in types/api.ts). */
export const DAY_STATES = [
  // turquoise stripes, the same as a month that is still loading in the year × month calendar
  { key: "pending", label: "Downloading", className: "bg-[repeating-linear-gradient(135deg,rgb(23_182_217/0.45)_0_3px,transparent_3px_7px)] text-white" },
  { key: "unavailable", label: "Not published", className: "text-muted/50 line-through" },
  { key: "no_data", label: "No observations", className: "text-muted/40" },
] as const;

const STATUS_TEXT: Record<string, string> = {
  pending: "NASA has this day; FireSync is still downloading it",
  unavailable: "NASA has not published data for this day (yet)",
  no_data: "no satellite observations",
  not_imported: "the 2000–2025 archive has not been imported",
  partial: "partial: one sensor still to come, or NASA is still adding satellite passes",
  future: "this day has not happened yet",
};

export default function DayCalendar({
  days,
  selected,
  onSelect,
}: {
  days: DayValue[];
  selected: string | null;
  onSelect: (date: string | null) => void;
}) {
  const active = days.map((d) => d.harmonized ?? 0).filter((v) => v > 0).sort((a, b) => a - b);
  const t1 = active[Math.floor(active.length / 3)] ?? 0; // low / medium boundary
  const t2 = active[Math.floor((active.length * 2) / 3)] ?? 0; // medium / high boundary
  const offset = (new Date(days[0].date).getUTCDay() + 6) % 7; // Monday = 0 (dates are UTC days)

  function levelClass(v: number | null) {
    if (!v) return "";
    if (v >= t2) return DAY_LEVELS[0].className;
    if (v >= t1) return DAY_LEVELS[1].className;
    return DAY_LEVELS[2].className;
  }

  return (
    <div className="grid grid-cols-7 gap-x-2 gap-y-1.5 text-center text-sm">
      {WEEKDAYS.map((w) => (
        <span key={w} className="pb-1">
          {w}
        </span>
      ))}
      {Array.from({ length: offset }, (_, i) => (
        <span key={`e${i}`} />
      ))}
      {days.map((d) => {
        const v = d.harmonized;
        const isSel = selected === d.date;
        // a day with only VIIRS (no validated MODIS scale) has no harmonized value but can still be shown on the map
        const hasData = v !== null || d.modis !== null || d.viirs !== null;
        const empty = DAY_STATES.find((s) => s.key === (d.status === "not_imported" || d.status === "future" ? "no_data" : d.status));
        const why = d.status ? STATUS_TEXT[d.status] : undefined;
        return (
          <button
            key={d.date}
            onClick={() => onSelect(isSel ? null : d.date)}
            disabled={!hasData}
            className={`relative h-7 rounded-md 2xl:h-8 transition hover:brightness-125 disabled:cursor-not-allowed ${
              v !== null ? levelClass(v) : hasData ? "" : (empty?.className ?? "text-muted/40")
            } ${isSel ? "ring-2 ring-white ring-offset-2 ring-offset-surface" : ""}`}
            title={
              !hasData
                ? `${d.date}: no data — ${why ?? "not loaded"}`
                : `${d.date}: ${v === null ? "MODIS-scale value unavailable" : `${v} active cells`} · MODIS ${d.modis ?? "—"} · VIIRS ${d.viirs ?? "—"}` +
                  (v === 0 ? " · no fires detected" : "") +
                  (d.status === "partial" && why ? ` · ${why}` : "")
            }
          >
            {Number(d.date.slice(8))}
            {d.status === "partial" && (
              <span aria-hidden className="absolute bottom-0.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-white/80" />
            )}
          </button>
        );
      })}
    </div>
  );
}
