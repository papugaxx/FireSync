import { SENSOR_COLORS } from "@/lib/colors";

const LABELS = { MODIS: "MODIS only", VIIRS: "VIIRS only", BOTH: "Detected by both" } as const;

export default function SensorLegend() {
  return (
    <ul className="space-y-1">
      {(Object.keys(LABELS) as (keyof typeof LABELS)[]).map((k) => (
        <li key={k} className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ background: SENSOR_COLORS[k] }} />
          {LABELS[k]}
        </li>
      ))}
    </ul>
  );
}
