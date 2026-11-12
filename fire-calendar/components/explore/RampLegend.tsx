import { ANOMALY_RAMP, FIRE_RAMP, NO_DATA } from "@/lib/colors";

export default function RampLegend({ mode }: { mode: "count" | "anomaly" }) {
  const ramp = mode === "count" ? FIRE_RAMP : ANOMALY_RAMP;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
      <span>{mode === "count" ? "Fewer" : "Below median"}</span>
      <div className="flex">
        {ramp.map((c) => (
          <span key={c} className="h-3 w-6" style={{ background: c }} />
        ))}
      </div>
      <span>{mode === "count" ? "More" : "Above median"}</span>
      <span className="ml-3 inline-flex items-center gap-1">
        <span className="h-3 w-3" style={{ background: NO_DATA }} /> no data
      </span>
    </div>
  );
}
