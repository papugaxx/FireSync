import { SITE } from "@/lib/site";

export default function Footer() {
  return (
    <footer className="mt-auto bg-surface">
      <div className="mx-auto max-w-6xl px-4 py-8 text-sm text-muted">
        {SITE.name} · NASA Space Apps Challenge 2026 · Data:{" "}
        <a href="https://firms.modaps.eosdis.nasa.gov/" target="_blank" rel="noreferrer" className="underline hover:text-white">
          NASA FIRMS
        </a>
      </div>
    </footer>
  );
}
