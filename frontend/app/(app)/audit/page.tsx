"use client";

import { motion } from "motion/react";
import { Link2, ShieldCheck, ShieldX } from "lucide-react";
import { Suspense } from "react";

import { Chip, ErrorBox, PageHeader, Panel, Skeleton } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, stamp } from "@/lib/format";
import { useParam } from "@/lib/params";

interface Entry { id: number; at: string; actor: string; actor_name: string; action: string; target: string | null; payload: Record<string, unknown>; prev_hash: string; hash: string }
interface Audit { entries: Entry[]; verification: { ok: boolean; verified_through: number; head?: string; broken_at?: number } }

const TONE = (a: string) =>
  a.startsWith("unmask") ? "amber" : a.startsWith("case.review") || a.startsWith("case.propose") ? "threat" : a.startsWith("pack") ? "ok" : a.startsWith("council") || a.startsWith("copilot") ? "ai" : "faint";

function AuditTrail() {
  const [target, setTarget] = useParam("target");
  const { data, error } = useGet<Audit>(["audit", target], `/governance/audit?limit=300${target ? `&target=${target}` : ""}`);
  const v = data?.verification;

  return (
    <div className="mx-auto max-w-[1400px] p-5">
      <PageHeader eyebrow="Evidence · Audit Trail" title="Who did what, chained so nobody can quietly edit it"
        sub="Every view, decision, unmask, pack and council run is appended to a hash chain: each entry commits to the one before it. Change any past row and verification breaks from that point on." />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Skeleton className="h-96" />}
      {data && v && (
        <>
          <Panel className={cn("mb-4 flex flex-wrap items-center gap-4 p-4", v.ok ? "border-ok/30" : "border-threat/40")}>
            {v.ok ? <ShieldCheck size={28} className="text-ok" /> : <ShieldX size={28} className="text-threat" />}
            <div className="min-w-0 flex-1">
              <div className={cn("display text-[17px] font-semibold", v.ok ? "text-ok" : "text-threat")}>{v.ok ? "Chain intact" : `Chain broken at #${v.broken_at}`}</div>
              <div className="text-[12px] text-muted">Verified through entry #{v.verified_through} {v.head && <> · head <span className="num text-ink-2">{v.head.slice(0, 24)}…</span></>}</div>
            </div>
            {target && <Chip tone="info">target {target} <button onClick={() => setTarget(null)} className="ml-1">×</button></Chip>}
          </Panel>
          <Panel className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-[12px]">
                <thead><tr className="border-b border-line text-left">{["#", "When", "Who", "Action", "Target", "Detail", "Hash chain"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 eyebrow">{h}</th>)}</tr></thead>
                <tbody>
                  {data.entries.map((e, i) => (
                    <motion.tr key={e.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i, 30) * 0.015 }} className="border-b border-line last:border-0 hover:bg-panel-2">
                      <td className="num px-3 py-2 text-faint">{e.id}</td>
                      <td className="num whitespace-nowrap px-3 py-2 text-muted">{stamp(e.at)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-ink">{e.actor_name}</td>
                      <td className="px-3 py-2"><Chip tone={TONE(e.action)}>{e.action}</Chip></td>
                      <td className="num whitespace-nowrap px-3 py-2">
                        {e.target ? <button onClick={() => setTarget(e.target)} className="text-ink-2 hover:text-info">{e.target}</button> : <span className="text-faint">—</span>}
                      </td>
                      <td className="max-w-[280px] truncate px-3 py-2 text-muted">{Object.entries(e.payload ?? {}).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : String(x)}`).join(" · ")}</td>
                      <td className="num whitespace-nowrap px-3 py-2 text-[11px] text-faint">{e.prev_hash.slice(0, 8)} <Link2 size={10} className="inline text-line-strong" /> <span className="text-ink-2">{e.hash.slice(0, 8)}</span></td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

export default function AuditPage() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-96" /></div>}><AuditTrail /></Suspense>;
}
