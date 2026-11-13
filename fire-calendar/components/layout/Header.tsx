import Link from "next/link";

const NAV = [
  { href: "/#problem", label: "Problem" },
  { href: "/#how", label: "How it works" },
  { href: "/#features", label: "Features" },
];

export default function Header() {
  return (
    <header style={{ backgroundColor: 'rgba(17, 24, 39, 1)' }} className="border-b text-[white]">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="font-semibold">
          {/* TODO: логотип */}
          FireSync
        </Link>
        <nav className="hidden gap-6 md:flex">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href}>
              {n.label}
            </Link>
          ))}
        </nav>
        <Link href="/explore" className="border px-3 py-1">
          Open calendar
        </Link>
      </div>
    </header>
  );
}
