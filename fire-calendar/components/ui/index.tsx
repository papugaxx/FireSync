// Базовые UI-элементы. Сейчас это нейтральные заглушки.
// Под дизайн меняются только эти файлы, страницы трогать не нужно.
import Link from "next/link";

export function Section({ id, title, children }: { id?: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-6xl scroll-mt-16 px-4 py-12">
      <h2 className="mb-6 text-2xl font-semibold">{title}</h2>
      {children}
    </section>
  );
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
    <div className={`border p-4 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between">
          {title && <h3 className="font-medium">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}

export function ButtonLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="inline-block border px-4 py-2">
      {children}
    </Link>
  );
}

export function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={`border px-3 py-1 disabled:opacity-50 ${props.className ?? ""}`} />;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      {children}
    </label>
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className="border px-2 py-1" />;
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Card>
      <div className="text-sm">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
      {hint && <div className="text-xs">{hint}</div>}
    </Card>
  );
}

/** Серый прямоугольник: место под будущий контент или состояние загрузки. */
export function Placeholder({ className = "h-40", label = "Loading…" }: { className?: string; label?: string }) {
  return <div className={`flex w-full items-center justify-center border border-dashed text-sm ${className}`}>{label}</div>;
}
