"use client";

import { motion } from "motion/react";
import { ArrowRight, DatabaseZap, FileQuestion, PlugZap } from "lucide-react";
import { Suspense } from "react";

import { MissingEvidence } from "@/components/brief/brief";
import { AlertPicker } from "@/components/chain/alert-bits";
import { AgentAvatar } from "@/components/council/council";
import { Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useAlert, useCouncil, useGet } from "@/lib/api";
import { cn, stamp } from "@/lib/format";
import { useAlertParam } from "@/lib/params";

interface Source { system: string; table: string; rows: number; latest: string | null; status: "LIVE" | "NOT_CONNECTED" }

function Missing() {
  const [alertId, setAlert] = useAlertParam("INSIDER_ATO");
  const { data: a, error } = useAlert(alertId);
  const { data: c } = useCouncil(alertId);
  const { data: sources } = useGet<Source[]>(["sources"], "/governance/sources");
  const gaps = c?.requests.filter((r) => r.status === "NOT_INGESTED") ?? [];

  return (
    <div className="mx-auto max-w-[1500px] p-5">
      <PageHeader eyebrow="Evidence · Missing Evidence" title="What nobody could see — and what it could change"
        sub="SUTRA never fills a gap with a guess. It lists the records it did not have, who asked for them, and how each one could move the conclusion."
        right={<AlertPicker value={alertId} onChange={setAlert} />} />
      {error && <ErrorBox error={error} />}
      {!a && !error && <Skeleton className="h-[420px]" />}
      {a && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <Panel className="p-4"><MissingEvidence a={a} /></Panel>
            <Panel>
              <PanelHead eyebrow="Asked for during the council" title="Records the agents could not get" />
              <div className="space-y-2 px-4 pb-4">
                {!c && <Skeleton className="h-24" />}
                {c && gaps.length === 0 && <p className="text-[12.5px] text-muted">Every record the agents asked for was retrieved.</p>}
                {gaps.map((g, i) => {
                  const ag = c?.agents.find((x) => x.id === g.by);
                  return (
                    <motion.div key={g.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
                      className="rounded-lg border border-dashed border-line-strong p-3">
                      <div className="flex items-center gap-2">
                        {ag && <AgentAvatar agent={ag} size={22} />}
                        <span className="text-[12.5px] font-semibold text-ink">{g.record}</span><span className="text-[12px] text-muted">· {g.system}</span>
                        <Chip tone="faint" className="ml-auto">not ingested</Chip>
                      </div>
                      <p className="mt-1 text-[12px] text-ink-2">{g.reason}</p>
                      <p className="mt-1 text-[11.5px] text-amber">Collect manually and attach to the case.</p>
                    </motion.div>
                  );
                })}
              </div>
            </Panel>
          </div>
          <div className="space-y-4">
            <Panel>
              <PanelHead eyebrow="Decision sensitivity" title="If we obtain it, what changes?" />
              <div className="space-y-2.5 px-4 pb-4">
                {!c && <Skeleton className="h-40" />}
                {c?.sensitivity.map((s, i) => (
                  <motion.div key={s.evidence} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }} className="rounded-lg border border-line p-3">
                    <div className="mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-ink"><FileQuestion size={14} className="text-amber" />{s.evidence}</div>
                    {s.if.map((w) => (
                      <div key={w.condition} className="grid grid-cols-[1fr_auto_1fr] items-start gap-2 py-0.5 text-[12px]">
                        <span className="text-ink-2">{w.condition}</span><ArrowRight size={12} className="mt-0.5 text-faint" /><span className="text-ink">{w.effect}</span>
                      </div>
                    ))}
                  </motion.div>
                ))}
              </div>
            </Panel>
            <Panel>
              <PanelHead eyebrow="Coverage" title="Sources connected to SUTRA" />
              <div className="px-4 pb-4">
                {sources?.map((s) => (
                  <div key={s.system} className="flex items-center gap-2 border-b border-line py-1.5 text-[12px] last:border-0">
                    {s.status === "LIVE" ? <DatabaseZap size={13} className="text-ok" /> : <PlugZap size={13} className="text-faint" />}
                    <span className={cn(s.status === "LIVE" ? "text-ink" : "text-muted")}>{s.system}</span>
                    <span className="num ml-auto text-faint">{s.status === "LIVE" ? `${s.rows.toLocaleString("en-IN")} rows · ${stamp(s.latest)}` : "not connected"}</span>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MissingPage() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[420px]" /></div>}><Missing /></Suspense>;
}
