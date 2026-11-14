"use client";
import { useRef, useState } from "react";

interface Props {
  title: string;
  /** кнопки в заголовке (например MODIS / VIIRS) */
  actions?: React.ReactNode;
  /** стартовая позиция внутри области карты, px */
  initial: { x: number; y: number };
  width: number;
  z: number;
  onFocus: () => void;
  onClose: () => void;
  children: React.ReactNode;
}

/**
 * Окно поверх карты. На компьютере перетаскивается за заголовок и не выходит
 * за пределы родителя (родитель должен быть position: relative).
 * На телефоне (< lg) открывается на весь экран.
 */
export default function FloatingWindow({ title, actions, initial, width, z, onFocus, onClose, children }: Props) {
  const [pos, setPos] = useState(initial);
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);

  function onPointerDown(e: React.PointerEvent) {
    if ((e.target as HTMLElement).closest("button")) return; // клики по кнопкам не тащат окно
    if (window.matchMedia("(max-width: 1023px)").matches) return;
    // берём реальное положение окна (оно могло быть прижато к краю через CSS min())
    const el = ref.current!;
    drag.current = { dx: e.clientX - el.offsetLeft, dy: e.clientY - el.offsetTop };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current || !ref.current) return;
    const parent = ref.current.offsetParent as HTMLElement | null;
    const maxX = (parent?.clientWidth ?? window.innerWidth) - ref.current.offsetWidth;
    const maxY = (parent?.clientHeight ?? window.innerHeight) - ref.current.offsetHeight;
    setPos({
      x: Math.min(Math.max(0, e.clientX - drag.current.dx), Math.max(0, maxX)),
      // окно сжимается по высоте, если его опустить; не даём сделать его ниже 220px
      y: Math.min(Math.max(0, e.clientY - drag.current.dy), Math.max(0, Math.min(maxY, (parent?.clientHeight ?? 0) - 220))),
    });
  }

  function onPointerUp() {
    drag.current = null;
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={title}
      onPointerDownCapture={onFocus}
      style={{
        // не даём окну стартовать за правым краем на небольших экранах
        left: `min(${pos.x}px, calc(100% - ${width}px - 16px))`,
        top: pos.y, width, zIndex: z, maxHeight: `calc(100% - ${pos.y + 12}px)` }}
      className="fixed inset-0 z-[2000] flex flex-col overflow-auto bg-surface max-lg:left-0! max-lg:top-0! max-lg:w-full! max-lg:max-h-none! lg:absolute lg:inset-auto lg:max-w-[calc(100%-1rem)] lg:rounded-3xl lg:border lg:border-line lg:shadow-2xl lg:shadow-black/50"
    >
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className="sticky top-0 z-10 flex flex-wrap items-center gap-3 bg-surface px-6 pb-2 pt-4 lg:cursor-grab lg:select-none lg:active:cursor-grabbing"
      >
        <h3 className="mr-auto font-display text-base md:text-lg">{title}</h3>
        {actions && <div className="order-3 flex gap-3 max-lg:w-full lg:order-2">{actions}</div>}
        <button onClick={onClose} aria-label="Close" className="order-2 ml-2 rounded-md p-1 transition hover:bg-surface-2 lg:order-3">
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden>
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      </div>
      <div className="overflow-x-auto px-6 pb-5">{children}</div>
    </div>
  );
}
