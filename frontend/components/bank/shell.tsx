"use client";

// Kestrel Bank's look: a plain, green-and-grey core-banking product, deliberately unlike SUTRA,
// so it is obvious on stage which system is the bank and which is SUTRA.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, ExternalLink, Landmark } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/format";

import { bank, bankTime, type BankRecord } from "./bank-client";

export interface BankClock { now: string; day: string; open: boolean }

export function useBankClock() {
  return useQuery<BankClock>({ queryKey: ["bank-clock"], queryFn: () => bank<BankClock>("clock"), refetchInterval: 15_000, staleTime: 0 });
}

/** Ticks locally between fetches so the header clock moves every second. */
function useTicking(iso: string | undefined, fetchedAt: number) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!iso) return null;
  return new Date(+new Date(iso) + Math.max(0, (now ?? fetchedAt) - fetchedAt)).toISOString();
}

export function BankHeader() {
  const path = usePathname();
  const qc = useQueryClient();
  const clock = useBankClock();
  const shown = useTicking(clock.data?.now, clock.dataUpdatedAt);
  const [setting, setSetting] = useState(false);
  const [hhmm, setHhmm] = useState("21:20");
  const refresh = (c: BankClock) => qc.setQueryData(["bank-clock"], c);
  const nav = [
    { href: "/bank", label: "Overview" },
    { href: "/bank/staff", label: "Staff · Core banking" },
    { href: "/bank/netbanking", label: "Customer · NetBanking" },
  ];
  return (
    <header className="bg-[#0b4f3c] text-white">
      <div className="bg-[#f2c94c] px-4 py-1 text-center text-[11.5px] font-bold tracking-[0.08em] text-[#14211d]">
        MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY · synthetic customers · never connected to a real bank or UPI
      </div>
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/bank" className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-md bg-white text-[#0b4f3c]"><Landmark size={18} /></span>
          <span className="leading-tight">
            <span className="block text-[15px] font-semibold">Kestrel Urban Co-operative Bank</span>
            <span className="block text-[11.5px] text-white/70">Test bank · synthetic customers · for trying SUTRA</span>
          </span>
        </Link>
        <nav className="flex flex-wrap gap-1 text-[13px]">
          {nav.map((n) => (
            <Link key={n.href} href={n.href}
              className={cn("rounded px-2.5 py-1.5", path === n.href ? "bg-white/15 font-semibold" : "text-white/80 hover:bg-white/10")}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="flex items-center gap-1.5 rounded bg-white/10 px-2.5 py-1.5" title="Bank time. Each action also moves it on by the time that action takes.">
            <Clock size={13} /> Tue 22 Sep 2026 · <b className="font-mono tabular-nums">{bankTime(shown, true)}</b> IST
          </span>
          {setting ? (
            <span className="flex items-center gap-1">
              <input type="time" value={hhmm} onChange={(e) => setHhmm(e.target.value)} aria-label="Bank time"
                className="h-7 rounded bg-white px-1.5 font-mono text-[12px] text-[#14211d]" />
              <button className="rounded bg-[#f2c94c] px-2 py-1 font-semibold text-[#14211d]"
                onClick={async () => { refresh(await bank<BankClock>("clock", { body: { at: hhmm } })); setSetting(false); }}>Set</button>
              <button className="rounded px-2 py-1 text-white/80 hover:bg-white/10" onClick={() => setSetting(false)}>Cancel</button>
            </span>
          ) : (
            <>
              <button className="rounded px-2 py-1.5 text-white/85 hover:bg-white/10" onClick={() => setSetting(true)}>Set time</button>
              <button className="rounded px-2 py-1.5 text-white/85 hover:bg-white/10"
                onClick={async () => refresh(await bank<BankClock>("clock/advance", { body: { minutes: 15 } }))}>+15 min</button>
            </>
          )}
          <a href="/live#bank" target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded bg-[#f2c94c] px-2.5 py-1.5 font-semibold text-[#14211d]">
            Open SUTRA <ExternalLink size={12} />
          </a>
        </div>
      </div>
      {clock.data && !clock.data.open && (
        <div className="bg-[#b3261e] px-4 py-1.5 text-center text-[12.5px]">The bank day (22 Sep) is over. Use “Set time” to go back to the evening.</div>
      )}
    </header>
  );
}

export function Card({ title, sub, right, children, className }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border border-[#d5dcd9] bg-white", className)}>
      {(title || right) && (
        <div className="flex flex-wrap items-start justify-between gap-2 border-b border-[#e3e8e6] px-4 py-2.5">
          <div>
            {title && <h2 className="text-[14px] font-semibold text-[#14211d]">{title}</h2>}
            {sub && <p className="text-[12px] text-[#5b6b66]">{sub}</p>}
          </div>
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Btn({ tone = "primary", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "plain" | "warn" }) {
  return (
    <button
      {...props}
      className={cn("inline-flex h-9 items-center justify-center gap-1.5 rounded-md px-3.5 text-[13px] font-medium disabled:opacity-40",
        tone === "primary" && "bg-[#0f6b50] text-white hover:bg-[#0b5a43]",
        tone === "plain" && "border border-[#c7d0cc] bg-white text-[#14211d] hover:bg-[#f3f6f5]",
        tone === "warn" && "bg-[#9a3412] text-white hover:bg-[#7c2d12]",
        className)}
    />
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] font-medium text-[#3c4a46]">{label}</span>
      {children}
      {hint && <span className="text-[11.5px] text-[#6b7a75]">{hint}</span>}
    </label>
  );
}

export const INPUT = "h-9 rounded-md border border-[#c7d0cc] bg-white px-2.5 text-[13px] text-[#14211d] outline-none focus:border-[#0f6b50] focus:ring-2 focus:ring-[#0f6b50]/20";

export function Notice({ tone, children }: { tone: "ok" | "error" | "info" | "warn"; children: ReactNode }) {
  return (
    <div className={cn("rounded-md px-3 py-2 text-[12.5px]",
      tone === "ok" && "bg-[#e3f4ec] text-[#0b5a43]",
      tone === "error" && "bg-[#fde8e6] text-[#9f1d14]",
      tone === "warn" && "bg-[#fdf1d8] text-[#7a4b00]",
      tone === "info" && "bg-[#e8eef9] text-[#26437a]")}>
      {children}
    </div>
  );
}

/** The rows the bank's systems wrote for what you just did — exactly what SUTRA will ingest. */
export function RecordsList({ records, empty }: { records: BankRecord[]; empty: string }) {
  if (!records.length) return <p className="text-[12.5px] text-[#6b7a75]">{empty}</p>;
  return (
    <ol className="flex max-h-[420px] flex-col gap-1 overflow-y-auto">
      {[...records].reverse().map((r) => (
        <li key={r.seq} className="grid grid-cols-[56px_minmax(0,1fr)] gap-2 border-b border-[#eef1f0] py-1.5 text-[12px]">
          <span className="font-mono tabular-nums text-[#6b7a75]">{bankTime(r.t, true)}</span>
          <span>
            <span className="mr-1.5 rounded bg-[#eef1f0] px-1.5 py-0.5 text-[10.5px] font-medium text-[#3c4a46]">{r.system}</span>
            <span className="text-[#14211d]">{r.summary}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

export function useBankActivity() {
  return useQuery<BankRecord[]>({ queryKey: ["bank-activity"], queryFn: () => bank<BankRecord[]>("activity"), refetchInterval: 4000 });
}
