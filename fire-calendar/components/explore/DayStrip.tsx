"use client";
import type { DayValue } from "@/types/api";
import { fireColor } from "@/lib/colors";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

// Календарь выбранного месяца по дням (как обычный настенный календарь).
export default function DayStrip({ days }: { days: DayValue[] }) {
  const max = Math.max(1, ...days.map((d) => d.harmonized ?? 0));
  const offset = (new Date(days[0].date).getDay() + 6) % 7; // понедельник = 0

  return (
    <div className="grid grid-cols-7 gap-1 text-xs">
      {WEEKDAYS.map((w) => (
        <span key={w} className="text-center">
          {w}
        </span>
      ))}
      {Array.from({ length: offset }, (_, i) => (
        <span key={`e${i}`} />
      ))}
      {days.map((d) => {
        const v = d.harmonized;
        return (
          <div
            key={d.date}
            className="flex aspect-square flex-col items-center justify-center rounded-md"
            style={{ background: fireColor(v, max), color: v !== null && v > max * 0.35 ? "#fff" : "#17171b" }}
            title={`${d.date}: ${v === null ? "no data" : `${v} cells`} · MODIS ${d.modis ?? "—"} · VIIRS ${d.viirs ?? "—"}`}
          >
            <span className="font-mono">{Number(d.date.slice(8))}</span>
          </div>
        );
      })}
    </div>
  );
}
