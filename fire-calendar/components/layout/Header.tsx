"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SITE } from "@/lib/site";

const NAV = [
  { href: "/#problem", label: "Problem" },
  { href: "/#how", label: "How it works" },
  { href: "/#features", label: "Features" },
  { href: "/#team", label: "Team" },
];

const outlineBtn =
  "rounded-full border-2 border-accent px-6 py-2 text-sm transition hover:bg-accent hover:text-bg";

export default function Header() {
  const isExplore = usePathname().startsWith("/explore");

  return (
    <header className="bg-surface">
      <div className="mx-auto flex h-20 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="font-display text-2xl tracking-wide md:text-3xl">
          {SITE.name}
        </Link>

        {isExplore ? (
          <Link href="/" className={outlineBtn}>
            Go back
          </Link>
        ) : (
          <>
            <nav className="hidden gap-8 text-sm text-muted md:flex">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="transition hover:text-white">
                  {n.label}
                </Link>
              ))}
            </nav>
            <Link href="/explore" className={outlineBtn}>
              Open calendar
            </Link>
          </>
        )}
      </div>
    </header>
  );
}
