"use client";
// Карта на чистом Leaflet (без react-leaflet): Next.js 16 сохраняет страницы при уходе,
// и react-leaflet при возврате падает. Здесь карта создаётся при показе и удаляется при уходе.
// Подключается через next/dynamic с ssr: false (см. Explorer.tsx).
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Hotspot, Region } from "@/types/api";

const FIRE_COLOR = "#ff2a1a";
const SENSOR_LABEL = { MODIS: "MODIS", VIIRS: "VIIRS", BOTH: "MODIS + VIIRS" } as const;
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";

export default function FireMap({ region, hotspots }: { region: Region; hotspots: Hotspot[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  // 1. создать карту при появлении, удалить при уходе со страницы
  // 1. создать карту при появлении, удалить при уходе со страницы
  useEffect(() => {
    if (!containerRef.current) return;

    // Границы мира: по широте только реальная карта (±85°), по долготе с запасом,
    // чтобы можно было крутить мир влево-вправо
    const worldBounds = L.latLngBounds([-85, -540], [85, 540]);

    const map = L.map(containerRef.current, {
      scrollWheelZoom: false,
      zoomControl: false,
      worldCopyJump: true,
      preferCanvas: true,
      maxBounds: worldBounds,
      maxBoundsViscosity: 1.0, // 1 = карта упирается в край и дальше не тянется
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);

    // Минимальный зум: мир по высоте должен закрывать всё окно карты,
    // иначе сверху и снизу видно пустое место
    const updateMinZoom = () => {
      const h = map.getSize().y;
      const minZoom = Math.max(2, Math.ceil(Math.log2(h / 256)));
      map.setMinZoom(minZoom);
      if (map.getZoom() < minZoom) map.setZoom(minZoom);
    };
    updateMinZoom();
    map.on("resize", updateMinZoom);

    // спутниковая подложка + границы стран (Esri, бесплатно, нужна подпись)
    L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics",
      maxZoom: 18,
    }).addTo(map);
    L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, {
      maxZoom: 18,
      opacity: 0.8,
    }).addTo(map);

    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  // 2. при смене региона: приблизиться к нему (для мира рамку не рисуем)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const [s, w, n, e] = region.bbox;
    const bounds = L.latLngBounds([s, w], [n, e]);
    map.fitBounds(bounds, { padding: [20, 20] });
    if (region.id === "world") return;
    const rect = L.rectangle(bounds, { color: "#17b6d9", weight: 2, fill: false, dashArray: "6 6" }).addTo(map);
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
      L.circleMarker([h.lat, h.lon], {
        radius: 2.5,
        stroke: false,
        fillColor: FIRE_COLOR,
        fillOpacity: 0.9,
      })
        .bindTooltip(`${h.date} · ${SENSOR_LABEL[h.seenBy]} · FRP ${h.frp} MW`)
        .addTo(layer);
    }
  }, [hotspots]);

  return <div ref={containerRef} className="h-full w-full" />;
}
