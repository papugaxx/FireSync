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
  /** own rectangle of the "Area & dates" window, [west, south, east, north] */
  customBox?: [number, number, number, number] | null;
  /** true → the next mouse drag on the map draws a rectangle instead of moving the map */
  drawing?: boolean;
  onDrawn?: (box: [number, number, number, number]) => void;
  /** false: cells only show a tooltip, no card */
  clickable?: boolean;
  /** cells cover a period (the "Area & dates" result): the card lists the detections of that period */
  cardPeriod?: { from: string; to: string } | null;
  /** own tooltip text per cell; by default date · sensor · FRP */
  tooltip?: (h: Hotspot) => string;
  /** zoom the map to this box once when it changes, [west, south, east, north] */
  fitTo?: [number, number, number, number] | null;
  /** px kept free on the right when zooming to `fitTo` (a window may cover that side) */
  fitPaddingRight?: number;
}

export default function FireMap({
  region,
  hotspots,
  sensor,
  customBox = null,
  drawing = false,
  onDrawn,
  clickable = true,
  cardPeriod = null,
  tooltip,
  fitTo = null,
  fitPaddingRight = 40,
}: Props) {
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

  // the tooltip function may be a new one on every render: keep the latest in a ref
  const tooltipRef = useRef(tooltip);
  useEffect(() => {
    tooltipRef.current = tooltip;
  }, [tooltip]);

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
          tooltipRef.current?.(h) ??
            `0.1° cell · ${h.date} · ${SENSOR_LABEL[h.seenBy]} · max FRP ${h.frp === null ? "unknown" : `${h.frp} MW`}` +
              `${h.edge ? " · border cell" : ""} · click for the real detections`,
        )
        .on("click", (e) => {
          L.DomEvent.stopPropagation(e); // do not let the map's own click close the card again
          if (!clickable) return;
          setSelected(h);
          setPos(screenPos(map, h));
        })
        .addTo(layer);
    }
  }, [hotspots, zoom, clickable]);

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

  // 6. the own rectangle of the "Area & dates" window
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !customBox) return;
    const [w, s, e, n] = customBox;
    const rect = L.rectangle(
      [
        [s, w],
        [n, e],
      ],
      { color: "#ffffff", weight: 2, dashArray: "8 6", fillColor: "#17b6d9", fillOpacity: 0.08, interactive: false },
    ).addTo(map);
    return () => {
      rect.remove();
    };
  }, [customBox]);

  // 6b. zoom to the analysed area
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !fitTo) return;
    map.fitBounds(
      [
        [fitTo[1], fitTo[0]],
        [fitTo[3], fitTo[2]],
      ],
      // on a wide screen the left panel covers ~450 px on the left and the "Area & dates" window the right side;
      // on a phone the panels are below the map, so a small margin is enough
      map.getSize().x >= 1200
        ? { paddingTopLeft: [470, 120], paddingBottomRight: [fitPaddingRight, 80] }
        : { padding: [20, 20] },
    );
    // fit only when the analysed box changes, not when the window moves
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitTo]);

  // 7. drawing mode: press, drag and release on the map to draw the rectangle
  const onDrawnRef = useRef(onDrawn);
  useEffect(() => {
    onDrawnRef.current = onDrawn;
  }, [onDrawn]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !drawing) return;
    const el = map.getContainer();
    el.style.cursor = "crosshair";
    map.dragging.disable();
    let start: L.LatLng | null = null;
    let preview: L.Rectangle | null = null;

    const down = (e: L.LeafletMouseEvent) => {
      start = e.latlng;
      preview = L.rectangle(L.latLngBounds(start, start), { color: "#17b6d9", weight: 2, fillOpacity: 0.1, interactive: false }).addTo(map);
    };
    const move = (e: L.LeafletMouseEvent) => {
      if (start && preview) preview.setBounds(L.latLngBounds(start, e.latlng));
    };
    const up = (e: L.LeafletMouseEvent) => {
      if (!start) return;
      const b = L.latLngBounds(start, e.latlng);
      preview?.remove();
      preview = null;
      start = null;
      const r = (v: number) => Math.round(v * 100) / 100;
      const clampLon = (v: number) => Math.min(180, Math.max(-180, v));
      const box: [number, number, number, number] = [
        r(clampLon(b.getWest())),
        r(Math.max(-90, b.getSouth())),
        r(clampLon(b.getEast())),
        r(Math.min(90, b.getNorth())),
      ];
      if (box[0] < box[2] && box[1] < box[3]) onDrawnRef.current?.(box); // a plain click draws nothing
    };
    map.on("mousedown", down);
    map.on("mousemove", move);
    map.on("mouseup", up);
    return () => {
      map.off("mousedown", down);
      map.off("mousemove", move);
      map.off("mouseup", up);
      preview?.remove();
      map.dragging.enable();
      el.style.cursor = "";
    };
  }, [drawing]);

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
              key={`${region.id}-${active.id}-${sensor ?? "all"}-${cardPeriod ? `${cardPeriod.from}_${cardPeriod.to}` : ""}`}
              period={cardPeriod ?? undefined}
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
