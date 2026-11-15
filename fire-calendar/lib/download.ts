// Saving charts as PNG images. The charts are plain SVG, so they are drawn onto a canvas,
// with a dark background and a short header (title + what was selected), and downloaded.

const BG = "#111827"; // --color-surface
const TEXT = "#e8ecf3";
const MUTED = "#8b95a8";

/**
 * Download an <svg> as a PNG file.
 * @param title    big line at the top, e.g. "Monthly activity over the year"
 * @param subtitle small line under it, e.g. "Ukraine · 2024 · FireSync, NASA FIRMS"
 */
export async function downloadSvgAsPng(svg: SVGSVGElement, filename: string, title: string, subtitle: string) {
  const box = svg.viewBox.baseVal;
  const width = box?.width || svg.clientWidth || 900;
  const height = box?.height || svg.clientHeight || 300;

  // the SVG uses "currentColor" in places: give the copy an explicit text color
  const copy = svg.cloneNode(true) as SVGSVGElement;
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", String(width));
  copy.setAttribute("height", String(height));
  copy.style.color = TEXT;
  // the SVG text has no font of its own: use the site's font, otherwise the image falls back to a serif font
  copy.style.fontFamily = getComputedStyle(svg).fontFamily || "sans-serif";
  copy.querySelectorAll("title").forEach((t) => t.remove()); // hover tooltips are not needed in an image

  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" }));
  try {
    const img = await loadImage(url);
    const scale = 2; // sharp on high-resolution screens and in slides
    const pad = 24;
    const header = 64;
    const canvas = document.createElement("canvas");
    canvas.width = (width + pad * 2) * scale;
    canvas.height = (height + header + pad * 2) * scale;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(scale, scale);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, width + pad * 2, height + header + pad * 2);

    const font = getComputedStyle(document.body).fontFamily || "sans-serif";
    ctx.fillStyle = TEXT;
    ctx.font = `600 20px ${font}`;
    ctx.fillText(title, pad, pad + 20);
    ctx.fillStyle = MUTED;
    ctx.font = `13px ${font}`;
    ctx.fillText(subtitle, pad, pad + 44);

    ctx.drawImage(img, pad, pad + header, width, height);
    const png = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
    if (png) saveBlob(png, filename);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The largest <svg> inside an element (charts may contain small icon SVGs too). */
export function largestSvg(root: Element | null): SVGSVGElement | null {
  if (!root) return null;
  let best: SVGSVGElement | null = null;
  let bestArea = 0;
  root.querySelectorAll("svg").forEach((s) => {
    const r = s.getBoundingClientRect();
    if (r.width * r.height > bestArea) {
      best = s;
      bestArea = r.width * r.height;
    }
  });
  return best;
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function loadImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Could not render the chart"));
    img.src = src;
  });
}
