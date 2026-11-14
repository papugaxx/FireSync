"use client";
// Map built on plain Leaflet (no react-leaflet): Next.js 16 keeps pages alive when navigating away,
// and react-leaflet crashes on return. Here the map is created when shown and removed when leaving.
// Loaded through next/dynamic with ssr: false (see Explorer.tsx).
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

  // 1. create the map when it appears, remove it when leaving the page
  useEffect(() => {
    if (!containerRef.current) return;
    // Latitude: only the real map (±85°); longitude has extra room so the world can be dragged around
    const worldBounds = L.latLngBounds([-85, -540], [85, 540]);
    const map = L.map(containerRef.current, {
      scrollWheelZoom: false,
      zoomControl: false,
      worldCopyJump: true,
      preferCanvas: true, // thousands of points are drawn faster
      maxBounds: worldBounds,
      maxBoundsViscosity: 1.0, // the map hits the edge, so there is no empty space at the top or bottom
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);

    // minimum zoom: the world's height covers the whole map window
    const updateMinZoom = () => {
      const minZoom = Math.max(2, Math.ceil(Math.log2(map.getSize().y / 256)));
      map.setMinZoom(minZoom);
      if (map.getZoom() < minZoom) map.setZoom(minZoom);
    };
    map.on("resize", updateMinZoom);

    // satellite basemap + country borders (Esri, free, attribution required)
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

  // 2. when the region changes: zoom to it (no outline for the world)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const [s, w, n, e] = region.bbox;
    const bounds = L.latLngBounds([s, w], [n, e]);
    map.fitBounds(bounds, { padding: [20, 20] });
    map.fire("resize"); // recalculate the minimum zoom after the initial view is set
    if (region.id === "world") return;
    const rect = L.rectangle(bounds, { color: "#17b6d9", weight: 2, fill: false, dashArray: "6 6" }).addTo(map);
    return () => {
      rect.remove();
    };
  }, [region]);

  // 3. when the data changes: redraw the points
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
