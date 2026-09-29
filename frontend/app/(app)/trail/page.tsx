"use client";

import { motion } from "motion/react";
import { ArrowLeftRight, Banknote, Clock, GitFork, Repeat, Split } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { EntityGraph } from "@/components/graph/entity-graph";
import { EntitySearch } from "@/components/graph/entity-search";
import { Chip, CountUp, Empty, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useAlerts, useGet } from "@/lib/api";
import { cn, duration, inr, pct, stamp } from "@/lib/format";
import { useParam } from "@/lib/params";
import type { GraphEdge, GraphNode } from "@/lib/types";

interface Trail {
  root: string;
  direction: "forward" | "backward";
  nodes: GraphNode[];
  edges: (GraphEdge & { narration: string; depth: number })[];
  stats: { fan_out: number; fan_in: number; total_out: number; pass_through: number | null; cash_out: number; time_to_layering_s: number | null; edges: number };
}

const MIN_AMOUNTS = [1_000, 10_000, 50_000, 1_00_000];

function TrailView() {
  const [account, setAccount] = useParam("account");
  const [direction, setDirection] = useParam("direction");
  const [hopsP, setHops] = useParam("hops");
  const [minP, setMin] = useParam("min");
  const [sel, setSel] = useState<string | null>(null);
  const { data: alerts } = useAlerts();
  const root = account ?? alerts?.find((a) => a.typology === "INSIDER_ATO")?.account_id ?? alerts?.[0]?.account_id ?? null;
  const dir = direction === "backward" ? "backward" : "forward";
  const hops = Number(hopsP ?? 3);
  const min = Number(minP ?? 10_000);
  const q = root ? `/trail?account=${root}&direction=${dir}&hops=${hops}&min_amount=${min}` : null;
  const { data: t, error, isFetching } = useGet<Trail>(["trail", q], q, { placeholderData: (p) => p });

  const picks = [...new Set(alerts?.map((a) => a.account_id).filter(Boolean) as string[])];

  return (
    <div className="mx-auto max-w-[1600px] p-5">
      <PageHeader eyebrow="Investigate · Money Trail" title="Follow the money, hop by hop"
        sub="Time-respecting: each hop only follows money that left after it arrived, within 72 hours. Pass-through and time-to-layering tell you whether an account is a destination or a conduit." />

      <Panel className="mb-4 flex flex-wrap items-center gap-3 p-3">
        <EntitySearch kinds={["account", "external"]} placeholder="Trace from an account…" onPick={(h) => setAccount(h.id)} />
        <div className="flex rounded-md border border-line p-0.5">
          {(["forward", "backward"] as const).map((d) => (
            <button key={d} onClick={() => setDirection(d === "forward" ? null : d)}
              className={cn("rounded px-2.5 py-1 text-[12px]", dir === d ? "bg-ink text-bg" : "text-muted hover:text-ink")}>
              {d === "forward" ? "Where it went →" : "← Where it came from"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-[12px] text-muted">
          Hops
          <input type="range" min={1} max={4} value={hops} onChange={(e) => setHops(e.target.value === "3" ? null : e.target.value)} className="w-24 accent-[var(--threat)]" />
          <span className="num w-3 text-ink">{hops}</span>
        </label>
        <div className="flex items-center gap-1 text-[12px] text-muted">
          Min
          {MIN_AMOUNTS.map((m) => (
            <button key={m} onClick={() => setMin(m === 10_000 ? null : String(m))}
              className={cn("num rounded border px-1.5 py-0.5", min === m ? "border-ink text-ink" : "border-line text-muted hover:text-ink")}>{inr(m)}</button>
          ))}
        </div>
        {picks.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 text-[12px] text-faint">
            From alerts:
            {picks.map((p) => (
              <button key={p} onClick={() => setAccount(p)} className={cn("num rounded bg-panel-2 px-1.5 py-0.5 hover:text-info", p === root ? "text-info" : "text-ink-2")}>{p}</button>
            ))}
          </div>
        )}
      </Panel>

      {error && <ErrorBox error={error} />}
      {!t && !error && <Skeleton className="h-[480px]" />}
      {t && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {[
              { k: dir === "forward" ? "Fan-out" : "Fan-in", v: dir === "forward" ? t.stats.fan_out : t.stats.fan_in, f: undefined, icon: GitFork, sub: "distinct counterparties" },
              { k: "Total moved", v: t.stats.total_out, f: (v: number) => inr(v), icon: ArrowLeftRight, sub: `${t.stats.edges} transfers traced` },
              { k: "Passed straight on", v: t.stats.pass_through ?? 0, f: (v: number) => (t.stats.pass_through === null ? "—" : pct(v)), icon: Repeat, sub: "of what the first hop received" },
              { k: "Time to layering", v: t.stats.time_to_layering_s ?? 0, f: (v: number) => (t.stats.time_to_layering_s === null ? "—" : duration(v)), icon: Clock, sub: "first in → first onward" },
              { k: "Cashed out", v: t.stats.cash_out, f: (v: number) => inr(v), icon: Banknote, sub: "ATM withdrawals on the trail" },
              { k: "Hops", v: Math.max(0, ...t.edges.map((e) => e.depth)), f: undefined, icon: Split, sub: `of ${hops} searched` },
            ].map((x, i) => (
              <motion.div key={x.k} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
                <Panel className="h-full p-3.5">
                  <div className="flex items-center gap-1.5 text-[11.5px] text-muted"><x.icon size={13} /> {x.k}</div>
                  <div className="display mt-1 text-[22px] font-extrabold leading-none text-ink"><CountUp key={`${root}-${dir}-${x.k}-${x.v}`} value={x.v} format={x.f} /></div>
                  <div className="mt-1 text-[11px] text-faint">{x.sub}</div>
                </Panel>
              </motion.div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <Panel className="overflow-hidden">
              <PanelHead eyebrow={`${dir === "forward" ? "Forward" : "Backward"} from ${t.root}`} title="Trail graph"
                right={<><Link href={`/entities/${t.root}`} className="text-[12px] text-info hover:underline">Dossier</Link>{isFetching && <Chip tone="ai">tracing…</Chip>}</>} />
              <div className="h-[500px] border-t border-line">
                {t.edges.length ? (
                  <EntityGraph nodes={t.nodes} edges={t.edges} layout="chain" particles selectedEdge={sel} onEdgeClick={(e) => setSel(e.id)}
                    onNodeClick={(n) => n.id !== t.root && !n.id.startsWith("X-ATM") && setAccount(n.id)} />
                ) : <Empty title="No transfers above the minimum">Lower the minimum amount or change direction.</Empty>}
              </div>
              <p className="border-t border-line px-4 py-2 text-[11px] text-faint">Click an account to re-root the trail there.</p>
            </Panel>
            <Panel className="overflow-hidden">
              <PanelHead eyebrow="Ledger" title="Every hop, in time order" />
              <div className="max-h-[540px] overflow-y-auto">
                <table className="w-full text-[12px]">
                  <thead className="sticky top-0 bg-panel"><tr className="border-b border-line text-left">
                    {["Hop", "When", "From → To", "Amount", "Channel"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 eyebrow">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {t.edges.slice().sort((a, b) => (a.t ?? "").localeCompare(b.t ?? "")).map((e) => (
                      <tr key={e.id} onClick={() => setSel(e.id)} className={cn("cursor-pointer border-b border-line last:border-0 hover:bg-panel-2", sel === e.id && "bg-panel-2")}>
                        <td className="px-3 py-2"><span className={cn("num rounded px-1.5 py-0.5 text-[10.5px]", e.depth === 1 ? "bg-threat-soft text-threat" : e.depth === 2 ? "bg-amber-soft text-amber" : "bg-info-soft text-info")}>{e.depth}</span></td>
                        <td className="num whitespace-nowrap px-3 py-2 text-muted">{stamp(e.t)}</td>
                        <td className="num whitespace-nowrap px-3 py-2 text-ink">{e.source} <span className="text-faint">→</span> {e.target}</td>
                        <td className="num whitespace-nowrap px-3 py-2 font-semibold text-ink">{inr(e.amount)}</td>
                        <td className="px-3 py-2 text-muted">{e.channel}<div className="text-[10.5px] text-faint">{e.narration}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export default function MoneyTrail() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[520px]" /></div>}><TrailView /></Suspense>;
}
