"use client";
import { useEffect, useState } from "react";

/**
 * Loads data and reloads it when key changes.
 * While loading for a new key, data = undefined (we show a placeholder).
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
    // load is recreated on every render, so we depend only on key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state.key === key ? state : { key, data: undefined, error: undefined };
}
