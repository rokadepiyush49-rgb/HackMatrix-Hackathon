"use client";

// Kestrel Bank's browser client. Bank sessions live in sessionStorage for this tab only: this is a
// test bank on synthetic data, signed in without passwords, and it never sees SUTRA's session.

import { useSyncExternalStore } from "react";

export class BankError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function bank<T>(path: string, opts: { token?: string | null; body?: unknown; method?: string } = {}): Promise<T> {
  const res = await fetch(`/api/bank/${path}`, {
    method: opts.method ?? (opts.body === undefined ? "GET" : "POST"),
    headers: { "Content-Type": "application/json", ...(opts.token ? { "X-Bank-Token": opts.token } : {}) },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : Array.isArray(b.detail) ? b.detail.map((d: { msg: string }) => d.msg).join("; ") : detail;
    } catch {
      /* not JSON */
    }
    throw new BankError(res.status, detail);
  }
  return (await res.json()) as T;
}

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};

/** A bank session token kept for this browser tab. */
export function useBankSession(key: string): [string | null, (t: string | null) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => {
      try {
        return sessionStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => null,
  );
  const set = (t: string | null) => {
    try {
      if (t) sessionStorage.setItem(key, t);
      else sessionStorage.removeItem(key);
    } catch {
      /* storage unavailable */
    }
    listeners.forEach((l) => l());
  };
  return [value, set];
}

export interface BankRecord { seq: number; t: string; table: string; ref: string; system: string; summary: string }

export const rupees = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;

export function bankTime(iso: string | null | undefined, seconds = false): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), timeZone: "Asia/Kolkata", hour12: false });
}
