import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Indian rupee formatting: ₹4.9 L, ₹1.09 Cr, ₹48,000 */
export function inr(v: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const compact = opts.compact ?? true;
  if (compact && v >= 1e7) return `₹${trim(v / 1e7)} Cr`;
  if (compact && v >= 1e5) return `₹${trim(v / 1e5)} L`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

function trim(n: number): string {
  return n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1).replace(/\.0$/, "") : n.toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
}

export function duration(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  const a = Math.abs(s);
  if (a < 90) return `${Math.round(a)} s`;
  if (a < 90 * 60) return `${Math.round(a / 60)} min`;
  if (a < 48 * 3600) return `${(a / 3600).toFixed(1).replace(/\.0$/, "")} h`;
  return `${(a / 86400).toFixed(1).replace(/\.0$/, "")} days`;
}

const IST = "Asia/Kolkata";

export function hhmm(iso: string | null | undefined, seconds = false): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), timeZone: IST, hour12: false,
  });
}

export function dayMonth(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: IST });
}

export function stamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${dayMonth(iso)} ${hhmm(iso)}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits).replace(/\.0$/, "")}%`;
}

export const LEVEL_TONE: Record<string, string> = {
  HIGH: "threat",
  ELEVATED: "amber",
  LOW: "ok",
  NONE: "faint",
};

export const PRIORITY_TONE: Record<string, string> = {
  P1: "threat",
  P2: "amber",
  P3: "info",
  WATCH: "faint",
  EXPLAINED: "ok",
};

export const LANE_LABEL: Record<string, string> = {
  IAM: "IAM",
  SOC: "SOC · insider risk",
  FRAUD: "Fraud ops",
  AML: "AML",
  HR: "HR",
};
