"use client";
// Small download buttons for the chart windows: "PNG" saves the chart of the window it sits in,
// "CSV" saves the numbers behind it.
import { useState } from "react";
import { downloadSvgAsPng, largestSvg } from "@/lib/download";

const pill =
  "inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-xs text-muted transition hover:border-accent hover:text-white disabled:opacity-40";

/** Saves the largest chart inside the same window (or inside `scope`) as a PNG image. */
export function PngButton({
  filename,
  title,
  subtitle,
  scope,
}: {
  filename: string;
  title: string;
  subtitle: string;
  /** element that holds the chart; by default the window the button is in */
  scope?: () => Element | null;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className={pill}
      disabled={busy}
      title="Download this chart as an image"
      onClick={async (e) => {
        const root = scope ? scope() : (e.currentTarget.closest("[role=dialog]") as Element | null);
        const svg = largestSvg(root);
        if (!svg) return;
        setBusy(true);
        try {
          await downloadSvgAsPng(svg, filename, title, subtitle);
        } finally {
          setBusy(false);
        }
      }}
    >
      <DownloadIcon /> PNG
    </button>
  );
}

export function CsvButton({ onClick, disabled, title, label = "CSV" }: { onClick: () => void; disabled?: boolean; title?: string; label?: string }) {
  return (
    <button className={pill} onClick={onClick} disabled={disabled} title={title ?? "Download the numbers as CSV"}>
      <DownloadIcon /> {label}
    </button>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden>
      <path d="M12 4v11m-5-5 5 5 5-5M5 20h14" />
    </svg>
  );
}
