"use client";
// Map built on plain Leaflet (no react-leaflet): Next.js 16 keeps pages alive when navigating away,
// and react-leaflet crashes on return. Here the map is created when shown and removed when leaving.
// Loaded through next/dynamic with ssr: false (see Explorer.tsx).
//
// What is drawn: /api/hotspots/ sends ONE record per active 0.1° GRID CELL and day (its centre),
// not fire locations. Each cell is drawn as a square covering the cell, colored by the sensor that saw
// it (MODIS / VIIRS / both); zoomed out, the square keeps a minimum size on screen. Clicking a cell opens
// the "Hotspot Telemetry" card with the real NASA detections inside it, and those are drawn as white
// dots at their own coordinates. The region outline is the real border it is counted by.
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useRef, useState } from "react";
import type { Detection, Hotspot, Region } from "@/types/api";
import { api } from "@/lib/api";
import { SENSOR_COLORS } from "@/lib/colors";
import HotspotCard from "./HotspotCard";

const SENSOR_LABEL = { MODIS: "MODIS", VIIRS: "VIIRS", BOTH: "MODIS + VIIRS" } as const;
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
const HALF = 0.05; // half of a 0.1° cell
const MIN_SQUARE_PX = 5; // a cell is never drawn smaller than this on screen
const CARD_SPACE = 300; // px needed above a cell to open the card upwards

interface Props {
  region: Region;
  hotspots: Hotspot[];
  /** only one sensor ticked → the card asks the backend only for that sensor */
  sensor?: "MODIS" | "VIIRS";
}

export default function FireMap({ region, hotspots, sensor }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const [zoom, setZoom] = useState(0);
  const [selected, setSelected] = useState<Hotspot | null>(null);
  const [detections, setDetections] = useState<{ points: Detection[]; current: number }>({ points: [], current: 0 });
  // where the selected cell is on screen, plus the map width (to keep the card inside the map)
  const [pos, setPos] = useState<{ x: number; y: number; w: number } | null>(null);

  // the card stays open only while its cell is still on the map (filters may hide it)
  const active = selected && hotspots.some((h) => h.id === selected.id) ? selected : null;

  // 1. create the map when it appears, remove it when leaving the page
  useEffect(() => {
    if (!containerRef.current) return;
    // Latitude: only the real map (±85°); longitude has extra room so the world can be dragged around
    const worldBounds = L.latLngBounds([-85, -540], [85, 540]);
    const map = L.map(containerRef.current, {
      scrollWheelZoom: true,
      wheelPxPerZoomLevel: 120,
      zoomControl: false,
      worldCopyJump: true,
      preferCanvas: true, // thousands of cells are drawn faster
      maxBounds: worldBounds,
      maxBoundsViscosity: 1.0, // the map hits the edge, so there is no empty space at the top or bottom
      maxZoom: 13,
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);

    // minimum zoom: the world's height covers the whole map window
    const updateMinZoom = () => {
      const minZoom = Math.max(2, Math.ceil(Math.log2(map.getSize().y / 256)));
      map.setMinZoom(minZoom);
      if (map.getZoom() < minZoom) map.setZoom(minZoom);
    };
    map.on("resize", updateMinZoom);
    map.on("zoomend", () => setZoom(map.getZoom()));
    map.on("click", () => setSelected(null)); // a click on empty map closes the card

    // satellite basemap + country borders (Esri, free, attribution required)
    L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics",
      maxZoom: 13,
    }).addTo(map);
    L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, {
      maxZoom: 13,
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

  // 2. when the region changes: zoom to it and outline the border it is counted by (none for the world)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const [s, w, n, e] = region.bbox;
    const bounds = L.latLngBounds([s, w], [n, e]);
    map.fitBounds(bounds, { padding: [20, 20] });
    map.fire("resize"); // recalculate the minimum zoom after the initial view is set
    if (region.id === "world") return;
    const style = { color: "#17b6d9", weight: 2, fill: false, dashArray: "6 6", interactive: false };
    let outline: L.Layer = L.rectangle(bounds, style).addTo(map); // until the real border has arrived
    let alive = true;
    api
      .boundary(region.id)
      .then((b) => {
        if (!alive || !b) return;
        outline.remove();
        outline = L.geoJSON(b as GeoJSON.Feature, { style: () => ({ ...style, dashArray: undefined }), interactive: false }).addTo(map);
      })
      .catch(() => {}); // keep the rectangle
    return () => {
      alive = false;
      outline.remove();
    };
  }, [region]);

  // 3. when the data or the zoom changes: redraw the cells
  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const half = squareHalf(map.getZoom());

    for (const h of hotspots) {
      const color = SENSOR_COLORS[h.seenBy];
      L.rectangle(
        [
          [h.lat - half, h.lon - half],
          [h.lat + half, h.lon + half],
        ],
        { stroke: false, fillColor: color, fillOpacity: 0.85 },
      )
        .bindTooltip(
          `0.1° cell · ${h.date} · ${SENSOR_LABEL[h.seenBy]} · max FRP ${h.frp === null ? "unknown" : `${h.frp} MW`}` +
            `${h.edge ? " · border cell" : ""} · click for the real detections`,
        )
        .on("click", (e) => {
          L.DomEvent.stopPropagation(e); // do not let the map's own click close the card again
          setSelected(h);
          setPos(screenPos(map, h));
        })
        .addTo(layer);
    }
  }, [hotspots, zoom]);

  // 4. outline the selected cell and keep the card attached to it while the map moves
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !active) return;
    const half = squareHalf(map.getZoom());
    const outline = L.rectangle(
      [
        [active.lat - half, active.lon - half],
        [active.lat + half, active.lon + half],
      ],
      { color: "#ffffff", weight: 2, fill: false, interactive: false },
    ).addTo(map);
    const follow = () => setPos(screenPos(map, active));
    map.on("move zoom resize", follow);
    return () => {
      outline.remove();
      map.off("move zoom resize", follow);
    };
  }, [active, zoom]);

  // 5. the real detections of the selected cell, at their own coordinates (the shown one is larger)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !active || !detections.points.length) return;
    const group = L.layerGroup(
      detections.points.map((p, k) =>
        L.circleMarker([p.latitude, p.longitude], {
          radius: k === detections.current ? 6 : 3.5,
          color: "#ffffff",
          weight: k === detections.current ? 2 : 1,
          fillColor: SENSOR_COLORS[p.sensor],
          fillOpacity: 1,
          interactive: false,
        }),
      ),
    ).addTo(map);
    return () => {
      group.remove();
    };
  }, [active, detections]);

  // the card opens above the cell, or below it when there is no room at the top;
  // horizontally it is kept inside the map, while the tail always points at the cell
  const below = pos !== null && pos.y < CARD_SPACE;
  const mapWidth = pos?.w ?? 0;
  const cardHalf = Math.min(190, mapWidth / 2 - 8);
  const cardX = pos ? Math.min(Math.max(pos.x, cardHalf + 8), mapWidth - cardHalf - 8) : 0;

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      {active && pos && (
        <>
          <div
            className="absolute z-[1150]"
            style={{ left: cardX, top: pos.y, transform: `translate(-50%, ${below ? "18px" : "calc(-100% - 18px)"})` }}
          >
            <HotspotCard
              key={`${region.id}-${active.id}-${sensor ?? "all"}`}
              region={region.id}
              cell={active}
              sensor={sensor}
              onClose={() => setSelected(null)}
              onPoints={(points, current) => setDetections({ points, current })}
            />
          </div>
          {/* little tail pointing at the cell */}
          <span
            aria-hidden
            className={`absolute z-[1151] h-4 w-4 rotate-45 border-accent bg-surface ${
              below ? "border-l-2 border-t-2" : "border-b-2 border-r-2"
            }`}
            style={{ left: pos.x - 8, top: below ? pos.y + 11 : pos.y - 27 }}
          />
        </>
      )}
    </div>
  );
}

function screenPos(map: L.Map, h: Hotspot) {
  const p = map.latLngToContainerPoint([h.lat, h.lon]);
  return { x: p.x, y: p.y, w: map.getSize().x };
}

/**
 * Half-size of the drawn square, in degrees: the real 0.1° cell, or more when zoomed out so the
 * square stays at least MIN_SQUARE_PX wide (one degree of longitude = 256·2^zoom / 360 px).
 */
function squareHalf(zoom: number) {
  const pxPerDegree = (256 * 2 ** zoom) / 360;
  return Math.max(HALF, MIN_SQUARE_PX / 2 / pxPerDegree);
}
