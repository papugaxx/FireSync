// Базовые UI-элементы в стиле дизайна. Страницы собираются из них.
import Link from "next/link";

export function Section({ id, title, children }: { id?: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-6xl scroll-mt-20 px-4 py-12">
      <h2 className="mb-6 font-display text-2xl">{title}</h2>
      {children}
    </section>
  );
}

/** Тёмная панель со скруглением и тонкой рамкой. */
export function Panel({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-3xl border border-line bg-surface ${className}`}>{children}</div>;
}

export function Card({
  title,
  action,
  className = "",
  children,
}: {
  title?: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Panel className={`p-6 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h3 className="font-display text-lg md:text-xl">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </Panel>
  );
}

export function ButtonLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="inline-block rounded-full bg-accent px-6 py-2.5 font-medium text-white transition hover:brightness-110">
      {children}
    </Link>
  );
}

export function Button({ className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-full bg-accent px-6 py-2.5 font-medium text-white transition hover:brightness-110 disabled:opacity-40 ${className}`}
    />
  );
}

/** Таблетка-переключатель (MODIS / VIIRS). color — фон в активном состоянии. */
export function Toggle({
  active,
  color,
  onClick,
  children,
}: {
  active: boolean;
  color: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className="min-w-28 rounded-full border-2 px-5 py-1.5 text-sm font-medium transition"
      style={active ? { background: color, borderColor: color, color: "#fff" } : { borderColor: color, color }}
    >
      {children}
    </button>
  );
}

/** Подпись + выпадающий список в одной "капсуле", как в панели фильтров. */
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-4 rounded-2xl bg-bg/70 py-1.5 pl-5 pr-1.5">
      <span className="text-base">{label}</span>
      {children}
    </label>
  );
}

export function Select({ className = "", ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className="relative inline-block">
      <select
        {...props}
        className={`min-w-36 cursor-pointer appearance-none rounded-xl bg-surface-2 py-2 pl-4 pr-10 text-base ${className}`}
      />
      <svg
        viewBox="0 0 24 24"
        className="pointer-events-none absolute right-3 top-1/2 h-5 w-5 -translate-y-1/2"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        aria-hidden
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Panel className="p-5">
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint && <div className="text-xs text-muted">{hint}</div>}
    </Panel>
  );
}

/** Заглушка: место под будущий контент или состояние загрузки. */
export function Placeholder({ className = "h-40", label = "Loading…" }: { className?: string; label?: string }) {
  return (
    <div className={`flex w-full animate-pulse items-center justify-center rounded-2xl bg-surface-2/60 text-sm text-muted ${className}`}>
      {label}
    </div>
  );
}
