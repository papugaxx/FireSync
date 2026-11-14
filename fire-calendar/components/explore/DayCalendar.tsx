"use client";
import type { DayValue } from "@/types/api";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/**
 * Календарь месяца по дням. Дни с пожарами делятся на три равные группы:
 *  High   — бирюзовый (верхняя треть)
 *  Medium — синий
 *  Low    — тёмный
 * Без фона — пожаров не было; тусклая цифра — нет данных.
 */
export const DAY_LEVELS = [
  { key: "high", label: "High activity", className: "bg-accent" },
  { key: "medium", label: "Medium activity", className: "bg-accent-2" },
  { key: "low", label: "Low activity", className: "bg-bg" },
] as const;

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
  const t1 = active[Math.floor(active.length / 3)] ?? 0; // граница low / medium
  const t2 = active[Math.floor((active.length * 2) / 3)] ?? 0; // граница medium / high
  const offset = (new Date(days[0].date).getDay() + 6) % 7; // понедельник = 0

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
        return (
          <button
            key={d.date}
            onClick={() => onSelect(isSel ? null : d.date)}
            disabled={v === null}
            className={`h-7 rounded-md 2xl:h-8 transition hover:brightness-125 disabled:cursor-not-allowed disabled:text-muted/40 ${levelClass(v)} ${
              isSel ? "ring-2 ring-white ring-offset-2 ring-offset-surface" : ""
            }`}
            title={
              v === null
                ? `${d.date}: no data`
                : `${d.date}: ${v} active cells · MODIS ${d.modis ?? "—"} · VIIRS ${d.viirs ?? "—"}`
            }
          >
            {Number(d.date.slice(8))}
          </button>
        );
      })}
    </div>
  );
}
