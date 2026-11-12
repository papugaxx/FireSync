"use client";
import type { CalendarResponse } from "@/types/api";
import { anomalyColor, fireColor, MONTHS } from "@/lib/colors";

interface Props {
  data: CalendarResponse;
  mode: "count" | "anomaly";
  selected: { year: number; month: number };
  onSelect: (year: number, month: number) => void;
}

// Главный "календарь горения": строки = годы, столбцы = месяцы.
export default function YearCalendar({ data, mode, selected, onSelect }: Props) {
  const max = Math.max(...data.years.flatMap((y) => y.months.map((v) => v ?? 0)));

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-separate border-spacing-[3px] text-xs">
        <thead>
          <tr >
            <th />
            {MONTHS.map((m) => (
              <th key={m} className="font-normal">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.years.map((y) => (
            <tr key={y.year}>
              <td className="pr-2 text-right font-mono">{y.year}</td>
              {y.months.map((v, i) => {
                const isSel = selected.year === y.year && selected.month === i + 1;
                const bg = mode === "count" ? fireColor(v, max) : anomalyColor(v, data.median[i]);
                const pct = v !== null && data.median[i] ? Math.round((v / data.median[i] - 1) * 100) : null;
                return (
                  <td key={i} className="p-0">
                    <button
                      onClick={() => onSelect(y.year, i + 1)}
                      disabled={v === null}
                      className={`block h-5 w-full disabled:cursor-not-allowed ${
                        isSel ? "outline outline-2 outline-black" : ""
                      }`}
                      style={{ background: bg }}
                      title={
                        v === null
                          ? `${MONTHS[i]} ${y.year}: no data`
                          : `${MONTHS[i]} ${y.year}: ${v} active cells (${pct !== null && pct >= 0 ? "+" : ""}${pct}% vs median)`
                      }
                      aria-label={`${MONTHS[i]} ${y.year}`}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
          <tr>
            <td className="pr-2 pt-2 text-right">median</td>
            {data.median.map((m, i) => (
              <td key={i} className="pt-2 text-center font-mono">
                {m}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
