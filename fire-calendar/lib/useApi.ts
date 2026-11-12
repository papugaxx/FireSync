"use client";
import { useEffect, useState } from "react";

/**
 * Загружает данные и перезагружает их, когда меняется key.
 * Пока идёт загрузка для нового key, data = undefined (показываем заглушку).
 */
export function useApi<T>(key: string, load: () => Promise<T>) {
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>({ key: "" });

  useEffect(() => {
    let alive = true;
    load()
      .then((data) => alive && setState({ key, data }))
      .catch((e) => alive && setState({ key, error: String(e) }));
    return () => {
      alive = false;
    };
    // load пересоздаётся на каждом рендере, ориентируемся только на key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state.key === key ? state : { key, data: undefined, error: undefined };
}
