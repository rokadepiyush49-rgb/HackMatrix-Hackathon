"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown, KeyRound, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { Fragment, Suspense, useState } from "react";

import { Chip, CountUp, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, dayMonth, hhmm, pct } from "@/lib/format";
import { useParam } from "@/lib/params";
import type { AlibiCheck, EmployeeCard } from "@/lib/types";

interface Summary {
  total: number; explained: number; partial: number; unexplained: number; coverage: number;
  false_positives_removed: number; raw_access_signals: number;
  by_role: { role: string; coverage: number; accesses: number }[];
  by_template: { template: string; matches: number }[];
  attention: ({ employee: EmployeeCard } & Record<"EXPLAINED" | "PARTIAL" | "UNEXPLAINED", number>)[];
}
interface Row {
  access_id: string; t: string; employee_id: string; action: string; account_id: string | null; customer_id: string | null;
  override: boolean; verdict: "EXPLAINED" | "PARTIAL" | "UNEXPLAINED"; purpose_ok: boolean; timing_ok: boolean;
  reasons_found: number; checked: AlibiCheck[]; reason: string | null;
}

const TEMPLATE: Record<string, { label: string; q: string }> = {
  TICKET: { label: "Service ticket", q: "Was there a request for this customer?" },
  PORTFOLIO: { label: "Portfolio", q: "Is the customer theirs to manage?" },
  QUEUE: { label: "Workflow queue", q: "Was it assigned to them?" },
  INTERACTION: { label: "Customer interaction", q: "Was the customer there, on the phone or on eKYC?" },
  ROSTER: { label: "Rostered shift", q: "Were they on duty?" },
};
const VERDICT_TONE = { EXPLAINED: "ok", PARTIAL: "amber", UNEXPLAINED: "threat" } as const;

function CoverageRing({ v }: { v: number }) {
  const r = 52, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 128 128" className="size-[128px] -rotate-90" role="img" aria-label={`Alibi coverage ${pct(v, 2)}`}>
      <circle cx="64" cy="64" r={r} fill="none" strokeWidth="10" className="stroke-line" />
      <motion.circle cx="64" cy="64" r={r} fill="none" strokeWidth="10" strokeLinecap="round" className="stroke-ok"
        strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - v) }} transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1] }} />
    </svg>
  );
}

function Ledger() {
  const [verdict, setVerdict] = useParam("verdict");
  const [employee, setEmployee] = useParam("employee");
  const [open, setOpen] = useState<string | null>(null);
  const { data: s, error } = useGet<Summary>(["alibi-summary"], "/alibi/summary");
  const q = new URLSearchParams({ limit: "200", ...(verdict ? { verdict } : {}), ...(employee ? { employee } : {}) }).toString();
  const { data: rows, isFetching } = useGet<Row[]>(["alibi-ledger", q], `/alibi/ledger?${q}`, { placeholderData: (p) => p });
  const maxT = Math.max(...(s?.by_template.map((t) => t.matches) ?? [1]));

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader eyebrow="Intelligence · Alibi Ledger" title="Every staff access, reconciled like a bank statement"
        sub="Before anything is called suspicious, Alibi looks for the ordinary reason: a ticket, the customer's portfolio, a queue item, the customer being present, a rostered shift. Most accesses clear here — which is why investigators see five alerts, not seven hundred." />
      {error && <ErrorBox error={error} />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Panel className="flex items-center gap-5 p-4">
          {s ? (
            <>
              <div className="relative shrink-0">
                <CoverageRing v={s.coverage} />
                <div className="absolute inset-0 grid place-items-center text-center">
                  <div><div className="display text-[22px] font-extrabold text-ok"><CountUp value={s.coverage * 100} format={(v) => `${v.toFixed(1)}%`} /></div>
                    <div className="text-[10px] uppercase tracking-wider text-faint">explained</div></div>
                </div>
              </div>
              <div className="min-w-0 space-y-1.5 text-[12.5px]">
                <div className="text-muted"><b className="num text-ink"><CountUp value={s.total} /></b> staff accesses reconciled</div>
                <div className="flex items-center gap-2"><Chip tone="ok">explained</Chip><span className="num text-ink">{s.explained.toLocaleString("en-IN")}</span></div>
                <div className="flex items-center gap-2"><Chip tone="amber">partial</Chip><span className="num text-ink">{s.partial.toLocaleString("en-IN")}</span></div>
                <div className="flex items-center gap-2"><Chip tone="threat">unexplained</Chip><span className="num text-ink">{s.unexplained}</span></div>
                <p className="pt-1 text-[11.5px] text-muted">Without Alibi, <b className="text-ink">{s.raw_access_signals}</b> raw access signals (R5/R6) would have queued.</p>
              </div>
            </>
          ) : <Skeleton className="h-32 w-full" />}
        </Panel>

        <Panel>
          <PanelHead eyebrow="Reason meters" title="Which reasons clear accesses" />
          <div className="space-y-2.5 px-4 pb-4">
            {s?.by_template.map((t, i) => (
              <div key={t.template}>
                <div className="mb-1 flex items-baseline justify-between text-[12px]">
                  <span className="text-ink">{TEMPLATE[t.template]?.label ?? t.template} <span className="text-faint">· {TEMPLATE[t.template]?.q}</span></span>
                  <span className="num text-muted">{t.matches.toLocaleString("en-IN")}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
                  <motion.div className="h-full rounded-full bg-ok" initial={{ width: 0 }} animate={{ width: `${(t.matches / maxT) * 100}%` }} transition={{ delay: 0.1 + i * 0.08, duration: 0.7 }} />
                </div>
              </div>
            )) ?? <Skeleton className="h-32" />}
          </div>
        </Panel>

        <Panel>
          <PanelHead eyebrow="Coverage by role" title="Where explanations are thinnest" />
          <div className="space-y-2.5 px-4 pb-4">
            {s?.by_role.slice().sort((a, b) => a.coverage - b.coverage).map((r, i) => (
              <div key={r.role}>
                <div className="mb-1 flex items-baseline justify-between text-[12px]">
                  <span className="text-ink">{r.role.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</span>
                  <span className="num text-muted">{pct(r.coverage)} <span className="text-faint">of {r.accesses.toLocaleString("en-IN")}</span></span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
                  <motion.div className={cn("h-full rounded-full", r.coverage < 0.9 ? "bg-amber" : "bg-ok")} initial={{ width: 0 }}
                    animate={{ width: `${r.coverage * 100}%` }} transition={{ delay: 0.1 + i * 0.08, duration: 0.7 }} />
                </div>
              </div>
            )) ?? <Skeleton className="h-32" />}
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Panel className="h-fit">
          <PanelHead eyebrow="Needs attention" title="Most unexplained, by employee" />
          <div className="px-2 pb-2">
            {s?.attention.map((a) => {
              const tot = a.EXPLAINED + a.PARTIAL + a.UNEXPLAINED;
              const on = employee === a.employee.id;
              return (
                <button key={a.employee.id} onClick={() => setEmployee(on ? null : a.employee.id)}
                  className={cn("w-full rounded-lg px-2.5 py-2 text-left hover:bg-panel-2", on && "bg-panel-2 ring-1 ring-info/40")}>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="font-medium text-ink">{a.employee.pseudonym}</span><span className="num text-faint">{a.employee.id}</span>
                  </div>
                  <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-panel-2">
                    <span className="bg-ok" style={{ width: `${(a.EXPLAINED / tot) * 100}%` }} />
                    <span className="bg-amber" style={{ width: `${Math.max(1, (a.PARTIAL / tot) * 100)}%` }} />
                    <span className="bg-threat" style={{ width: `${a.UNEXPLAINED ? Math.max(2, (a.UNEXPLAINED / tot) * 100) : 0}%` }} />
                  </div>
                  <div className="num mt-1 text-[10.5px] text-muted">{a.PARTIAL} partial · <span className={a.UNEXPLAINED ? "text-threat" : ""}>{a.UNEXPLAINED} unexplained</span></div>
                </button>
              );
            })}
            <p className="px-2.5 py-2 text-[11px] text-faint">Staff are shown by role and branch. Names need a two-person unmask.</p>
          </div>
        </Panel>

        <Panel className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
            <span className="eyebrow mr-2">Statement</span>
            {[null, "EXPLAINED", "PARTIAL", "UNEXPLAINED"].map((v) => (
              <button key={v ?? "all"} onClick={() => setVerdict(v)}
                className={cn("rounded-full border px-3 py-1 text-[12.5px] font-medium", verdict === v ? "border-ink bg-ink text-bg" : "border-line text-muted hover:text-ink")}>
                {v ? v.toLowerCase() : "all"}
                {s && v && <span className="num ml-1.5 opacity-70">{(v === "EXPLAINED" ? s.explained : v === "PARTIAL" ? s.partial : s.unexplained).toLocaleString("en-IN")}</span>}
              </button>
            ))}
            {employee && <Chip tone="info" className="ml-1">{employee} <button onClick={() => setEmployee(null)} aria-label="Clear employee"><X size={11} /></button></Chip>}
            <span className="ml-auto text-[11px] text-faint">{isFetching ? "loading…" : `latest ${rows?.length ?? 0}`}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-[12px]">
              <thead>
                <tr className="border-b border-line text-left">
                  {["Date", "Time", "Employee", "Action", "Account", "Reason on file", "Reasons", "Verdict", ""].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 eyebrow">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows?.map((r, i) => {
                  const expanded = open === r.access_id;
                  const prevDay = i > 0 ? dayMonth(rows[i - 1].t) : null;
                  return (
                    <Fragment key={r.access_id}>
                      <tr onClick={() => setOpen(expanded ? null : r.access_id)}
                        className={cn("cursor-pointer border-b border-line hover:bg-panel-2", r.verdict === "UNEXPLAINED" && "bg-threat-soft/30", expanded && "bg-panel-2")}>
                        <td className="num whitespace-nowrap px-3 py-2 text-muted">{dayMonth(r.t) !== prevDay ? dayMonth(r.t) : ""}</td>
                        <td className="num px-3 py-2 text-ink">{hhmm(r.t)}</td>
                        <td className="num whitespace-nowrap px-3 py-2 text-ink-2">{r.employee_id}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-ink">
                          <span className="font-mono text-[11px]">{r.action}</span>
                          {r.override && <Chip tone="threat" className="ml-1.5"><KeyRound size={10} /> override</Chip>}
                        </td>
                        <td className="num whitespace-nowrap px-3 py-2 text-muted">{r.account_id ?? "—"}</td>
                        <td className="px-3 py-2">{r.reason ? <span className="num text-ok">{r.reason}</span> : <span className="text-threat">none found</span>}</td>
                        <td className="px-3 py-2">
                          <div className="flex gap-0.5">{r.checked.map((c) => <span key={c.template} title={TEMPLATE[c.template]?.label} className={cn("h-2.5 w-2 rounded-sm", c.ok ? "bg-ok" : "bg-line-strong")} />)}</div>
                        </td>
                        <td className="px-3 py-2"><Chip tone={VERDICT_TONE[r.verdict]}>{r.verdict.toLowerCase()}</Chip></td>
                        <td className="px-2 py-2 text-faint"><ChevronDown size={14} className={cn("transition-transform", expanded && "rotate-180")} /></td>
                      </tr>
                      <AnimatePresence>
                        {expanded && (
                          <tr className="border-b border-line bg-panel-2">
                            <td colSpan={9} className="px-4 py-0">
                              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                <div className="grid gap-1.5 py-3 md:grid-cols-[1fr_auto]">
                                  <ul className="space-y-1">
                                    {r.checked.map((c) => (
                                      <li key={c.template} className="flex items-start gap-2">
                                        {c.ok ? <Check size={13} className="mt-0.5 text-ok" /> : <X size={13} className="mt-0.5 text-threat" />}
                                        <span className="w-[150px] shrink-0 font-medium text-ink">{TEMPLATE[c.template]?.label}</span>
                                        <span className="text-muted">{c.note}</span>
                                      </li>
                                    ))}
                                  </ul>
                                  <div className="flex flex-col items-start gap-1.5 text-[11.5px] md:items-end">
                                    <span className="num text-faint">{r.access_id}</span>
                                    <span className={r.purpose_ok ? "text-ok" : "text-threat"}>purpose {r.purpose_ok ? "explained" : "not explained"}</span>
                                    <span className={r.timing_ok ? "text-ok" : "text-threat"}>timing {r.timing_ok ? "explained" : "not explained"}</span>
                                    {r.account_id && <Link href={`/entities/${r.account_id}`} className="text-info hover:underline">Open account dossier</Link>}
                                  </div>
                                </div>
                              </motion.div>
                            </td>
                          </tr>
                        )}
                      </AnimatePresence>
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {rows && rows.length === 0 && <div className="flex items-center justify-center gap-2 py-10 text-[13px] text-muted"><ShieldCheck size={16} /> Nothing matches this filter.</div>}
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default function AlibiLedger() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[480px]" /></div>}><Ledger /></Suspense>;
}
