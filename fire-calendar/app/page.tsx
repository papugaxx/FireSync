// Landing page: only the section structure and texts. Design is added later.
import { ButtonLink, Card, Placeholder, Section } from "@/components/ui";

const cardsTheProblem = [
  { title: "25 yrs", text: "of MODIS hotspots since 2000", img: "/visual-content/1.jpg" },
  { title: "375 m", text: "VIIRS pixel vs ~1 km for MODIS", img: "/visual-content/2.jpg" },
  { title: "2–3×", text: "more VIIRS detections for the same fire", img: "/visual-content/3.jpg" },
];

const cardsHowItWorks = [
  { title: "1. Collect", text: "Hotspots from NASA FIRMS, industrial sources filtered out." },
  { title: "2. Grid", text: "Both sensors on one 0.1° grid, counted as active cells." },
  { title: "3. Harmonize", text: "VIIRS fitted to the MODIS scale and validated." },
  { title: "4. Calendar", text: "One series from 2000 to today with anomalies." },
];

const cardsFeatures = [
  { title: "Burning calendar", text: "Year × month heatmap." },
  { title: "Anomaly view", text: "Each month vs its historical median." },
  { title: "Area of interest", text: "Region, bounding box or drawing on the map." },
  { title: "Hotspot map", text: "Active cells colored by sensor." },
  { title: "CSV export", text: "Download data behind any view." },
  { title: "Accessible colors", text: "Color-blind friendly ramps." },
];

export default function Home() {
  return (
    <>
      {/* Hero */}
      <section className="mx-auto grid max-w-6xl gap-8 px-4 py-16 md:grid-cols-2">
        <div>
          <h1 className="text-4xl font-semibold">Know when your land burns.</h1>
          <p className="mt-4">
            FireSync harmonizes 25 years of MODIS and VIIRS fire hotspots into one burning activity calendar.
          </p>
          <div className="mt-6 flex gap-3">
            <ButtonLink href="/explore">Explore the calendar</ButtonLink>
            <ButtonLink href="#how">How it works</ButtonLink>
          </div>
        </div>
        <Placeholder className="h-64" label="Hero image / calendar preview" />
      </section>


      <Section id="problem" title="The problem">
        <p className="mb-6 max-w-2xl">
          MODIS is reaching end of life and VIIRS is replacing it. Their records can&apos;t be compared directly
          because of different resolution, sensitivity and observation schedules.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          {cardsTheProblem.map((cards) =>
            <Card key={cards.title} title={cards.title} img={cards.img} imgAlt={cards.title}>
              {cards.text}
            </Card>
          )}
        </div>
      </Section>

      <Section id="how" title="How it works">
        <ol className="grid gap-4 md:grid-cols-4">
          <Card title="1. Collect">Hotspots from NASA FIRMS, industrial sources filtered out.</Card>
          <Card title="2. Grid">Both sensors on one 0.1° grid, counted as active cells.</Card>
          <Card title="3. Harmonize">VIIRS fitted to the MODIS scale and validated.</Card>
          <Card title="4. Calendar">One series from 2000 to today with anomalies.</Card>
        </ol>
      </Section>

      <Section id="features" title="Features">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card title="Burning calendar">Year × month heatmap.</Card>
          <Card title="Anomaly view">Each month vs its historical median.</Card>
          <Card title="Area of interest">Region, bounding box or drawing on the map.</Card>
          <Card title="Hotspot map">Active cells colored by sensor.</Card>
          <Card title="CSV export">Download data behind any view.</Card>
          <Card title="Accessible colors">Color-blind friendly ramps.</Card>
        </div>
      </Section>

      <Section title="See your area's fire history">
        <ButtonLink href="/explore">Open the calendar</ButtonLink>
      </Section>
    </>
  );
}
