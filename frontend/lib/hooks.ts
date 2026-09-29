"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

const noop = () => () => {};

/** True after hydration — for UI that depends on client-only state such as the resolved theme. */
export function useMounted(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}

/** A media query as live state; `false` during server rendering. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** A localStorage value as state (null when unset or storage is unavailable). */
export function useStoredValue(key: string): [string | null, (v: string) => void] {
  const value = useSyncExternalStore(
    (cb) => {
      window.addEventListener("storage", cb);
      window.addEventListener(`sutra-storage:${key}`, cb);
      return () => {
        window.removeEventListener("storage", cb);
        window.removeEventListener(`sutra-storage:${key}`, cb);
      };
    },
    () => {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => null,
  );
  const set = (v: string) => {
    try {
      localStorage.setItem(key, v);
    } catch {
      /* storage unavailable — the value simply won't persist */
    }
    window.dispatchEvent(new Event(`sutra-storage:${key}`));
  };
  return [value, set];
}

/** The current time, refreshed every `intervalMs`; null until the first client tick (keeps SSR stable). */
export function useNow(intervalMs = 30_000): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}
