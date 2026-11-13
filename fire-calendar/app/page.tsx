// Лендинг: только структура секций и тексты. Дизайн добавляется позже.
import { ButtonLink, Card, Placeholder, Section } from "@/components/ui";

export default function Home() {
  return (
    <div style={{ backgroundColor: 'rgba(11, 15, 25, 1)' }} className="min-h-screen text-white">
      {/* Hero */}
      <section className="mx-auto grid max-w-6xl gap-8 px-4 py-16 md:grid-cols-2">
        <div>
          <h1 className="text-4xl font-semibold text-[white]">Know when your land burns.</h1>
          <p className="mt-4 text-gray-300">
            FireSync harmonizes 25 years of MODIS and VIIRS fire hotspots into one burning activity calendar.
          </p>
          <div className="mt-6 flex gap-3 text-[white]">
            <ButtonLink href="/explore">Explore the calendar</ButtonLink>
            <ButtonLink href="#how">How it works</ButtonLink>
          </div>
        </div>
        <Placeholder 
          className="h-64 text-[white] border border-gray-700 rounded-2xl p-4" 
          label="Hero image / calendar preview" 
        />
      </section>

      <Section id="problem" title="The problem">
        <p className="mb-6 max-w-2xl text-gray-300">
          MODIS is reaching end of life and VIIRS is replacing it. Their records cant be compared directly
          because of different resolution, sensitivity and observation schedules.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="25 yrs">of MODIS hotspots since 2000</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="375 m">VIIRS pixel vs ~1 km for MODIS</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="2–3×">more VIIRS detections for the same fire</Card>
          </div>
        </div>
      </Section>

      <Section id="how" title="How it works">
        <ol className="grid gap-4 md:grid-cols-4">
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="1. Collect">Hotspots from NASA FIRMS, industrial sources filtered out.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="2. Grid">Both sensors on one 0.1° grid, counted as active cells.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="3. Harmonize">VIIRS fitted to the MODIS scale and validated.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="4. Calendar">One series from 2000 to today with anomalies.</Card>
          </div>
        </ol>
      </Section>

      <Section id="features" title="Features">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="Burning calendar">Year × month heatmap.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="Anomaly view">Each month vs its historical median.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="Area of interest">Region, bounding box or drawing on the map.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="Hotspot map">Active cells colored by sensor.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="CSV export">Download data behind any view.</Card>
          </div>
          <div style={{ backgroundColor: 'rgba(31, 41, 55, 1)' }} className="border border-gray-700 rounded-2xl p-6">
            <Card title="Accessible colors">Color-blind friendly ramps.</Card>
          </div>
        </div>
      </Section>

      <Section title="See your area's fire history">
        <ButtonLink href="/explore">Open the calendar</ButtonLink>
      </Section>
    </div>
  );
}