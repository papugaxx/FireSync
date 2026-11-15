// Landing page. Texts and cards live in the arrays below, so they can be edited without touching the markup.
import Image from "next/image";
import Link from "next/link";
import { ButtonLink, Panel } from "@/components/ui";
import { mockCalendar } from "@/lib/mock";
import { fireColor, MONTHS } from "@/lib/colors";

const heroStats = [
  { value: "2000–2025", label: "years of records" },
  { value: "2", label: "sensors, MODIS + VIIRS" },
  { value: "0.1°", label: "shared grid" },
];

const cardsTheProblem = [
  { title: "25 yrs", text: "of MODIS hotspots since 2000", img: "/visual-content/1.jpg" },
  { title: "375 m", text: "VIIRS pixel vs ~1 km for MODIS", img: "/visual-content/2.jpg" },
  { title: "2–3×", text: "more VIIRS detections for the same fire", img: "/visual-content/3.jpg" },
];

const cardsHowItWorks = [
  { title: "Collect", text: "Hotspots from NASA FIRMS, industrial sources filtered out." },
  { title: "Grid", text: "Both sensors on one 0.1° grid, counted as active cells." },
  { title: "Harmonize", text: "VIIRS fitted to the MODIS scale and validated." },
  { title: "Calendar", text: "One series from 2000 to today with anomalies." },
];

const cardsFeatures = [
  { title: "Burning calendar", text: "Year × month heatmap." },
  { title: "Anomaly view", text: "Each month vs its historical median." },
  { title: "Area of interest", text: "Region, bounding box or drawing on the map." },
  { title: "Hotspot map", text: "Active cells colored by sensor." },
  { title: "CSV export", text: "Download data behind any view." },
  { title: "Accessible colors", text: "Color-blind friendly ramps." },
];

const outlineLink =
  "inline-block rounded-full border-2 border-accent px-6 py-2 font-medium text-accent transition hover:bg-accent hover:text-bg";

export default function Home() {
  return (
    <>
      {/* ===== Hero ===== */}
      <section className="relative overflow-hidden">
        {/* soft turquoise glow behind the hero */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(50% 60% at 75% 40%, rgb(23 182 217 / 0.16), transparent 70%), radial-gradient(35% 40% at 10% 55%, rgb(31 111 192 / 0.12), transparent 70%)",
          }}
        />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 py-20 md:grid-cols-[1.1fr_1fr] md:py-28">
          <div>
            <p className="mb-5 inline-block rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs font-medium text-accent">
              NASA Space Apps Challenge 2026
            </p>
            <h1 className="font-display text-3xl leading-tight md:text-5xl">
              Know when your land <span className="text-accent">burns</span>.
            </h1>
            <p className="mt-6 max-w-xl text-lg text-muted">
              FireSync harmonizes 25 years of MODIS and VIIRS fire hotspots into one burning activity calendar.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <ButtonLink href="/explore">Explore the calendar</ButtonLink>
              <Link href="#how" className={outlineLink}>
                How it works
              </Link>
            </div>
            <dl className="mt-10 grid max-w-md grid-cols-3 gap-4 border-t border-line pt-6">
              {heroStats.map((s) => (
                <div key={s.label}>
                  <dt className="sr-only">{s.label}</dt>
                  <dd className="font-display text-lg text-white md:text-xl">{s.value}</dd>
                  <dd className="mt-1 text-xs text-muted">{s.label}</dd>
                </div>
              ))}
            </dl>
          </div>

          <HeroVisual />
        </div>
      </section>

      {/* ===== The problem ===== */}
      <Block id="problem" kicker="The problem" title="Two satellites, two scales">
        <p className="mb-10 max-w-2xl text-muted">
          MODIS is reaching end of life and VIIRS is replacing it. Their records can&apos;t be compared directly
          because of different resolution, sensitivity and observation schedules.
        </p>
        <div className="grid gap-5 md:grid-cols-3">
          {cardsTheProblem.map((c) => (
            <Panel key={c.title} className="overflow-hidden">
              <div className="relative aspect-[4/3] w-full">
                <Image src={c.img} alt="" fill sizes="(max-width: 768px) 100vw, 33vw" className="object-cover" />
              </div>
              <div className="p-6">
                <div className="font-display text-3xl text-accent">{c.title}</div>
                <p className="mt-2 text-muted">{c.text}</p>
              </div>
            </Panel>
          ))}
        </div>
      </Block>

      {/* ===== How it works ===== */}
      <Block id="how" kicker="How it works" title="From raw hotspots to one calendar" tinted>
        <ol className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {cardsHowItWorks.map((c, i) => (
            <li key={c.title} className="relative">
              <Panel className="h-full p-6">
                <span className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-accent font-display text-accent">
                  {i + 1}
                </span>
                <h3 className="mt-5 font-display text-lg">{c.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{c.text}</p>
              </Panel>
            </li>
          ))}
        </ol>
      </Block>

      {/* ===== Features ===== */}
      <Block id="features" kicker="Features" title="Built for people who respond to fire">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {cardsFeatures.map((c) => (
            <Panel key={c.title} className="p-6 transition hover:border-accent/50">
              <span aria-hidden className="block h-1 w-10 rounded-full bg-accent" />
              <h3 className="mt-4 text-lg font-semibold">{c.title}</h3>
              <p className="mt-1 text-sm text-muted">{c.text}</p>
            </Panel>
          ))}
        </div>
      </Block>

      {/* ===== Call to action ===== */}
      <section className="mx-auto max-w-6xl px-4 pb-24">
        <Panel className="relative overflow-hidden px-6 py-16 text-center">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{ background: "radial-gradient(60% 80% at 50% 0%, rgb(23 182 217 / 0.18), transparent 70%)" }}
          />
          <div className="relative">
            <h2 className="font-display text-2xl md:text-3xl">See your area&apos;s fire history</h2>
            <p className="mx-auto mt-4 max-w-xl text-muted">
              Pick a region and month to get its burning calendar, anomalies and hotspots.
            </p>
            <div className="mt-8">
              <ButtonLink href="/explore">Open the calendar</ButtonLink>
            </div>
          </div>
        </Panel>
      </section>
    </>
  );
}

/** Section with a small turquoise label above the heading. `tinted` adds a slightly lighter band. */
function Block({
  id,
  kicker,
  title,
  tinted,
  children,
}: {
  id: string;
  kicker: string;
  title: string;
  tinted?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`scroll-mt-20 ${tinted ? "border-y border-line bg-surface/40" : ""}`}>
      <div className="mx-auto max-w-6xl px-4 py-20">
        <p className="mb-3 text-sm font-medium uppercase tracking-widest text-accent">{kicker}</p>
        <h2 className="mb-6 font-display text-2xl md:text-3xl">{title}</h2>
        {children}
      </div>
    </section>
  );
}

/**
 * Right side of the hero. For now a small preview of the year × month burning calendar (demo data).
 * To use an image or a video instead, replace the contents of this component.
 */
function HeroVisual() {
  const years = mockCalendar("argentina").years.slice(-10);
  const max = Math.max(...years.flatMap((y) => y.months.map((v) => v ?? 0)));

  return (
    <Panel className="p-5 shadow-2xl shadow-accent/5">
      <div className="mb-4 flex items-baseline justify-between gap-3 text-sm">
        <span className="font-display">Burning calendar</span>
        <span className="text-xs text-muted">preview · demo data</span>
      </div>
      <div className="grid grid-cols-[auto_repeat(12,1fr)] gap-1 text-[10px] text-muted">
        <span />
        {MONTHS.map((m) => (
          <span key={m} className="text-center">
            {m[0]}
          </span>
        ))}
        {years.map((y) => (
          <div key={y.year} className="contents">
            <span className="pr-2 font-mono">{y.year}</span>
            {y.months.map((v, i) => (
              <span key={i} className="aspect-square rounded-[3px]" style={{ background: fireColor(v, max) }} />
            ))}
          </div>
        ))}
      </div>
    </Panel>
  );
}
