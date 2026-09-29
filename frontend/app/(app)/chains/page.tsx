"use client";

import { AnimatePresence, motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import { Fragment, Suspense, useMemo, useState } from "react";

import { ChainRail } from "@/components/chain/chain-rail";
import { TypologyChip } from "@/components/chain/alert-bits";
import { ButtonLink, Chip, ErrorBox, PageHeader, Panel, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, duration, inr } from "@/lib/format";
import { useParam } from "@/lib/params";
import type { AlertSummary, ChainLink, Contribution } from "@/lib/types";

type ChainRow = AlertSummary & { features: Record<string, number>; n_links: number };
interface ChainDetail { id: string; kind: string; alert_id: string; priority: string; features: Record<string, number>; contributions: Contribution[]; classifier_p: number | null; links: ChainLink[] }

const ORDER = ["P1", "P2", "P3", "WATCH", "EXPLAINED"] as const;
const SEG: Record<string, { bar: string; label: string; note: string }> = {
  P1: { bar: "bg-threat", label: "P1", note: "page an investigator now" },
  P2: { bar: "bg-amber", label: "P2", note: "same day" },
  P3: { bar: "bg-info", label: "P3", note: "queue" },
  WATCH: { bar: "bg-line-strong", label: "Watch-list", note: "classifier below 0.20 — kept, not queued" },
  EXPLAINED: { bar: "bg-ok", label: "Explained", note: "benign reason proven — 5% sampled to QA" },
};

function Detail({ chainId, alertId }: { chainId: string; alertId: string }) {
  const { data } = useGet<ChainDetail>(["chain", chainId], `/chains/${chainId}`);
  if (!data) return <Skeleton className="my-3 h-28" />;
  const max = Math.max(...data.contributions.map((c) => Math.abs(c.contribution)), 1e-9);
  return (
    <div className="grid gap-4 py-3 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="min-w-0"><ChainRail links={data.links} compact /></div>
      <div>
        {data.contributions.length > 0 ? (
          <>
            <div className="eyebrow mb-1.5">M5 contributions (exact, log-odds){data.classifier_p !== null && <span className="ml-2 normal-case text-ai">p = {data.classifier_p.toFixed(3)}</span>}</div>
            <div className="space-y-1">
              {data.contributions.slice(0, 6).map((c) => (
                <div key={c.feature} className="grid grid-cols-[1fr_90px_44px] items-center gap-2 text-[11.5px]">
                  <span className="truncate text-ink-2">{c.label}</span>
                  <div className="flex h-1.5 overflow-hidden rounded-full bg-panel-2">
                    <div className={cn("h-full", c.contribution >= 0 ? "bg-threat" : "bg-ok")} style={{ width: `${(Math.abs(c.contribution) / max) * 100}%` }} />
                  </div>
                  <span className="num text-right text-muted">{c.contribution >= 0 ? "+" : ""}{c.contribution.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </>
        ) : <p className="text-[12px] text-muted">This typology is argued by rules and graph detectors only; M5 does not score it.</p>}
        <div className="mt-3 flex gap-2">
          <ButtonLink size="sm" variant="primary" href={`/cases/${alertId}`}>Open</ButtonLink>
          <ButtonLink size="sm" href={`/council/${alertId}`}>Council</ButtonLink>
        </div>
      </div>
    </div>
  );
}

function Explorer() {
  const [prio, setPrio] = useParam("priority");
  const [kind, setKind] = useParam("kind");
  const [open, setOpen] = useState<string | null>(null);
  const { data, error } = useGet<ChainRow[]>(["chains"], "/chains");
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    data?.forEach((x) => (c[x.priority] = (c[x.priority] ?? 0) + 1));
    return c;
  }, [data]);
  const kinds = useMemo(() => [...new Map(data?.map((x) => [x.typology, x.typology_label])).entries()], [data]);
  const rows = (data ?? []).filter((x) => (!prio || x.priority === prio) && (!kind || x.typology === kind));
  const total = data?.length ?? 0;
  const queued = (counts.P1 ?? 0) + (counts.P2 ?? 0) + (counts.P3 ?? 0);

  return (
    <div className="mx-auto max-w-[1600px] p-5">
      <PageHeader eyebrow="Investigate · Chain Explorer"
        title={data ? <>{total} chains assembled. <span className="text-threat">{queued}</span> reached an investigator.</> : "Chain Explorer"}
        sub="Needle assembles every time-ordered privilege-to-payment chain it can find. The priority lattice decides which are argued strongly enough to queue — the rest stay visible here, so the precision is auditable." />
      {error && <ErrorBox error={error} />}
      {!data && <Skeleton className="h-[480px]" />}
      {data && (
        <>
          <Panel className="mb-4 p-4">
            <div className="flex h-9 w-full overflow-hidden rounded-lg">
              {ORDER.filter((p) => counts[p]).map((p, i) => (
                <motion.button key={p} onClick={() => setPrio(prio === p ? null : p)} initial={{ flexGrow: 0 }} animate={{ flexGrow: Math.max(counts[p], total * 0.04) }}
                  transition={{ delay: i * 0.08, duration: 0.6 }} style={{ flexBasis: 0 }}
                  className={cn("relative min-w-[44px] border-r border-bg text-[11.5px] font-semibold transition-opacity last:border-0", SEG[p].bar,
                    p === "WATCH" ? "text-ink" : "text-bg", prio && prio !== p && "opacity-35")}>
                  <span className="num">{counts[p]}</span>
                </motion.button>
              ))}
            </div>
            <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px]">
              {ORDER.filter((p) => counts[p]).map((p) => (
                <button key={p} onClick={() => setPrio(prio === p ? null : p)} className={cn("flex items-center gap-1.5", prio === p ? "text-ink" : "text-muted hover:text-ink")}>
                  <span className={cn("size-2 rounded-sm", SEG[p].bar)} /><b>{SEG[p].label}</b> {SEG[p].note}
                </button>
              ))}
            </div>
          </Panel>

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button onClick={() => setKind(null)} className={cn("rounded-full border px-3 py-1 text-[12.5px] font-medium", !kind ? "border-ink bg-ink text-bg" : "border-line text-muted")}>All typologies</button>
            {kinds.map(([k, label]) => (
              <button key={k} onClick={() => setKind(kind === k ? null : k)} className={cn("rounded-full border px-3 py-1 text-[12.5px] font-medium", kind === k ? "border-ink bg-ink text-bg" : "border-line text-muted hover:text-ink")}>{label}</button>
            ))}
            <span className="num ml-auto text-[11.5px] text-faint">{rows.length} shown</span>
          </div>

          <Panel className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-[12px]">
                <thead><tr className="border-b border-line text-left">
                  {["Priority", "Chain", "Typology", "What happened", "Hops", "Latency", "M5", "At risk", "Why this priority", ""].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 eyebrow">{h}</th>)}
                </tr></thead>
                <tbody>
                  {rows.map((x) => {
                    const on = open === x.id;
                    return (
                      <Fragment key={x.id}>
                        <tr onClick={() => setOpen(on ? null : x.id)} className={cn("cursor-pointer border-b border-line hover:bg-panel-2", on && "bg-panel-2")}>
                          <td className="px-3 py-2"><PriorityPill p={x.priority} /></td>
                          <td className="num whitespace-nowrap px-3 py-2 text-muted">{x.id}<div className="text-[10.5px] text-faint">{x.chain_id}</div></td>
                          <td className="px-3 py-2"><TypologyChip t={x.typology} label={x.typology_label} /></td>
                          <td className="max-w-[360px] px-3 py-2 text-ink"><span className="line-clamp-2">{x.summary ?? x.claim}</span></td>
                          <td className="num px-3 py-2 text-ink-2">{x.n_links}</td>
                          <td className="num whitespace-nowrap px-3 py-2 text-muted">{duration(x.latency_s)}</td>
                          <td className="num px-3 py-2">{x.classifier_p !== null ? <span className={x.classifier_p >= 0.2 ? "text-threat" : "text-faint"}>{x.classifier_p.toFixed(2)}</span> : <span className="text-faint">—</span>}</td>
                          <td className="num whitespace-nowrap px-3 py-2 font-semibold text-ink">{inr(x.amount_at_risk)}</td>
                          <td className="max-w-[300px] px-3 py-2 text-[11.5px] text-muted"><span className="line-clamp-2">{x.lattice_rule}</span></td>
                          <td className="px-2 py-2 text-faint"><ChevronDown size={14} className={cn("transition-transform", on && "rotate-180")} /></td>
                        </tr>
                        <AnimatePresence>
                          {on && (
                            <tr className="border-b border-line bg-panel-2/60">
                              <td colSpan={10} className="px-4">
                                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                  <Detail chainId={x.chain_id} alertId={x.id} />
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
            </div>
          </Panel>
          <p className="mt-3 text-[11.5px] text-faint">
            <Chip tone="faint">M5</Chip> is a glass-box logistic model trained on an independent synthetic world. It can move a chain between watch-list and queue; it can never raise an alert on its own.
          </p>
        </>
      )}
    </div>
  );
}

export default function ChainExplorer() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[480px]" /></div>}><Explorer /></Suspense>;
}
