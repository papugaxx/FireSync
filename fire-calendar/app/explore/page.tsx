import type { Metadata } from "next";
import Explorer from "@/components/explore/Explorer";

export const metadata: Metadata = { title: "Explore · FireSync" };

export default function ExplorePage() {
  return <Explorer />;
}
