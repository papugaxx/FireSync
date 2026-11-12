// Цветовые шкалы. Последовательная шкала "жёлтый → тёмно-красный" (на основе
// ColorBrewer YlOrRd) различима при дальтонизме, т.к. меняется и яркость, а не только оттенок.

export const FIRE_RAMP = ["#fff3c4", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026", "#6b0019"];
export const NO_DATA = "#cccccc";
export const ZERO = "#f2f2f2";

/** Цвет ячейки по значению относительно максимума. */
export function fireColor(value: number | null, max: number) {
  if (value === null) return NO_DATA;
  if (value === 0 || max === 0) return ZERO;
  const t = Math.min(1, Math.sqrt(value / max)); // sqrt: малые значения тоже видны
  return FIRE_RAMP[Math.min(FIRE_RAMP.length - 1, Math.floor(t * FIRE_RAMP.length))];
}

/** Аномалия относительно медианы: синий ниже нормы, красный выше. */
export const ANOMALY_RAMP = ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"];

export function anomalyColor(value: number | null, med: number) {
  if (value === null) return NO_DATA;
  const ratio = Math.log2((value + 1) / (med + 1)); // -1 = вдвое меньше, +1 = вдвое больше
  const idx = Math.round(Math.max(-1.5, Math.min(1.5, ratio)) * 2) + 3;
  return ANOMALY_RAMP[idx];
}

export const SENSOR_COLORS = { MODIS: "#3b82f6", VIIRS: "#f97316", BOTH: "#a855f7" } as const;

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
