"use client";

import { useQueries } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Check, Minus, X } from "lucide-react";
import Link from "next/link";

import { Chip, PageHeader, Panel, PanelHead, PriorityPill, Skeleton, Tip } from "@/components/ui/primitives";
import { api, useAlerts } from "@/lib/api";
import { cn, duration, inr, pct } from "@/lib/format";
import type { Mend } from "@/lib/types";

export default function ControlLibrary() {
  const { data: alerts } = useAlerts();
  const mends = useQueries({
    queries: (alerts ?? []).map((a) => ({ queryKey: ["mend", a.id, ""], queryFn: () => api<Mend>(`/mend/${a.id}`) })),
  });
  const ready = alerts && mends.every((q) => q.data);
  const controls = mends[0]?.data?.controls ?? [];

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader eyebrow="Prevent · Control Library" title="Which control stops which chain"
        sub="Every control is tested against every open case. A tick means the control would have broken the chain before the money left; the figure is how early." />
      <Panel className="overflow-hidden">
        <PanelHead eyebrow="Coverage matrix" title={`${controls.length} controls × ${alerts?.length ?? 0} open cases`} />
        {!ready ? <Skeleton className="m-4 h-72" /> : (
          <div className="overflow-x-auto px-4 pb-4">
            <table className="w-full min-w-[900px] border-separate border-spacing-0 text-[12px]">
              <thead>
                <tr>
                  <th className="sticky left-0 z-10 border-b border-line bg-panel py-2 pr-3 text-left eyebrow">Control</th>
                  <th className="border-b border-line px-2 py-2 text-left eyebrow">Friction / 90d</th>
                  {alerts!.map((a) => (
                    <th key={a.id} className="border-b border-line px-2 py-2 text-left align-bottom">
                      <Link href={`/controls?alert=${a.id}`} className="block hover:text-info">
                        <PriorityPill p={a.priority} />
                        <div className="num mt-1 text-[10.5px] text-faint">{a.id}</div>
                        <div className="max-w-[140px] truncate text-[11.5px] font-medium text-ink">{a.typology_label}</div>
                        <div className="num text-[11px] text-threat">{inr(a.amount_at_risk)}</div>
                      </Link>
                    </th>
                  ))}
                  <th className="border-b border-line px-2 py-2 text-right eyebrow">Would have saved</th>
                </tr>
              </thead>
              <tbody>
                {controls.map((c, ri) => {
                  const cells = mends.map((q) => q.data!.controls.find((x) => x.id === c.id)!);
                  const saved = cells.reduce((s, x) => s + (x.breaks ? x.prevented : 0), 0);
                  return (
                    <motion.tr key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: ri * 0.04 }} className="group">
                      <td className="sticky left-0 z-10 border-b border-line bg-panel py-2.5 pr-3 group-hover:bg-panel-2">
                        <div className="flex items-center gap-2"><span className="num text-faint">{c.id}</span><span className="font-semibold text-ink">{c.name}</span></div>
                        <div className="mt-0.5 flex gap-1"><Chip tone="info">at {c.breaks_at}</Chip><Chip tone={c.effort === "Low" ? "ok" : "amber"}>{c.effort}</Chip></div>
                      </td>
                      <td className="border-b border-line px-2 py-2.5 text-muted group-hover:bg-panel-2">
                        <span className="num text-ink">{c.friction.legit_ops_affected ?? 0}</span> ops · {pct(c.friction.share_of_sensitive_ops ?? 0, 2)}
                      </td>
                      {cells.map((x, i) => (
                        <td key={i} className="border-b border-line px-2 py-2.5 group-hover:bg-panel-2">
                          {!x.applicable ? (
                            <Tip content="Does not apply to this typology"><span className="text-faint"><Minus size={14} /></span></Tip>
                          ) : x.breaks ? (
                            <Tip content={x.hit?.why ?? ""}>
                              <span className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5", (x.lead_time_s ?? 0) > 3600 ? "bg-ok-soft text-ok" : "bg-amber-soft text-amber")}>
                                <Check size={12} /> <span className="num">{(x.lead_time_s ?? 0) > 0 ? duration(x.lead_time_s) : "at payout"}</span>
                              </span>
                            </Tip>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-threat"><X size={13} /> misses</span>
                          )}
                        </td>
                      ))}
                      <td className="num border-b border-line px-2 py-2.5 text-right font-semibold text-ok group-hover:bg-panel-2">{saved ? inr(saved) : "—"}</td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <p className="mt-3 text-[11.5px] text-faint">Friction is measured on the synthetic 90-day history: how many legitimate staff operations each control would have delayed or blocked.</p>
    </div>
  );
}
