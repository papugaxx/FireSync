"use client";
import type { DayValue } from "@/types/api";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/**
 * Календарь месяца по дням. Цвет дня:
 *  бирюзовый — высокая активность (выше медианы дней месяца)
 *  синий     — пожары есть, но меньше
 *  без фона  — пожаров не было; тусклый текст — нет данных
 */
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
  const threshold = active.length ? active[Math.floor(active.length / 2)] : 0;
  const offset = (new Date(days[0].date).getDay() + 6) % 7; // понедельник = 0

  return (
    <div className="grid grid-cols-7 gap-x-2 gap-y-3 text-center text-sm">
      {WEEKDAYS.map((w) => (
        <span key={w} className="pb-2 text-base">
          {w}
        </span>
      ))}
      {Array.from({ length: offset }, (_, i) => (
        <span key={`e${i}`} />
      ))}
      {days.map((d) => {
        const v = d.harmonized;
        const bg = !v ? "" : v >= threshold ? "bg-accent" : "bg-accent-2";
        const isSel = selected === d.date;
        return (
          <button
            key={d.date}
            onClick={() => onSelect(isSel ? null : d.date)}
            disabled={v === null}
            className={`h-9 rounded-md transition hover:brightness-125 disabled:cursor-not-allowed disabled:text-muted/50 ${bg} ${
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
