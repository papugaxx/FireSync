"use client";
// Карта на чистом Leaflet (без react-leaflet).
// Next.js 16 сохраняет открытые страницы и "будит" их при возврате;
// react-leaflet в этот момент пытается использовать уже удалённую карту и падает.
// Здесь карта создаётся при каждом показе и удаляется при уходе, так что ошибки нет.
// Подключается через next/dynamic с ssr: false (см. Explorer.tsx).
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Hotspot, Region } from "@/types/api";
import { SENSOR_COLORS } from "@/lib/colors";

const SENSOR_LABEL = { MODIS: "MODIS", VIIRS: "VIIRS", BOTH: "MODIS + VIIRS" } as const;

export default function FireMap({ region, hotspots }: { region: Region; hotspots: Hotspot[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  // 1. создать карту при появлении, удалить при уходе со страницы
  useEffect(() => {
    if (!containerRef.current) return;
    const map = L.map(containerRef.current, { scrollWheelZoom: false });
    // TODO: под дизайн можно сменить подложку (например тёмную CARTO dark_all)
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  // 2. при смене региона: рамка области и приближение к ней
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const [s, w, n, e] = region.bbox;
    const bounds = L.latLngBounds([s, w], [n, e]);
    const rect = L.rectangle(bounds, { color: "#000", weight: 1, fill: false, dashArray: "4 4" }).addTo(map);
    map.fitBounds(bounds, { padding: [20, 20] });
    return () => {
      rect.remove();
    };
  }, [region]);

  // 3. при смене данных: перерисовать точки
  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    layer.clearLayers();
    for (const h of hotspots) {
      const color = SENSOR_COLORS[h.seenBy];
      L.circleMarker([h.lat, h.lon], {
        radius: Math.min(9, 3 + h.frp / 30),
        color,
        fillColor: color,
        fillOpacity: 0.7,
        weight: 1,
      })
        .bindTooltip(`${h.date} · ${SENSOR_LABEL[h.seenBy]} · FRP ${h.frp} MW`)
        .addTo(layer);
    }
  }, [hotspots]);

  return <div ref={containerRef} className="h-full w-full" />;
}
