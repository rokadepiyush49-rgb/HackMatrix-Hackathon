"use client";

import { motion } from "motion/react";

import { cn, pct } from "@/lib/format";
import type { Funnel as FunnelData } from "@/lib/types";

/** How ~56k staff accesses narrow to a handful of argued alerts (log scale). */
export function Funnel({ f }: { f: FunnelData }) {
  const rows = [
    { label: "Staff accesses checked", v: f.staff_accesses, tone: "bg-line-strong" },
    { label: "Explained by Alibi", v: f.explained_by_alibi, tone: "bg-ok", note: pct(f.explained_by_alibi / f.staff_accesses) },
    { label: "Signals from 17 detectors", v: f.signals, tone: "bg-ai" },
    { label: "Candidate chains (Needle)", v: f.candidate_chains, tone: "bg-amber" },
    { label: "Queued for investigators", v: f.queued, tone: "bg-threat" },
  ];
  const max = Math.log10(f.staff_accesses + 1);
  return (
    <div className="space-y-2.5">
      {rows.map((r, i) => (
        <div key={r.label}>
          <div className="mb-1 flex items-baseline justify-between text-[12px]">
            <span className="text-ink-2">{r.label}</span>
            <span className="num text-ink">{r.v.toLocaleString("en-IN")} {r.note && <span className="text-ok">· {r.note}</span>}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-panel-2">
            <motion.div className={cn("h-full rounded-full", r.tone)} initial={{ width: 0 }}
              animate={{ width: `${Math.max(2, (Math.log10(r.v + 1) / max) * 100)}%` }} transition={{ delay: 0.2 + i * 0.12, duration: 0.7, ease: "easeOut" }} />
          </div>
        </div>
      ))}
      <div className="pt-1 text-[11.5px] text-muted">
        {f.watch} chains watch-listed by the classifier · {f.suppressed} suppressed as explained (5% sampled to QA). Log scale.
      </div>
    </div>
  );
}
