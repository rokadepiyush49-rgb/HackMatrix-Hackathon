"use client";

import { AnimatePresence, motion } from "motion/react";
import { EyeOff, Link2 } from "lucide-react";
import { Suspense, useEffect, useState } from "react";

import { AlertPicker } from "@/components/chain/alert-bits";
import { ChainRail } from "@/components/chain/chain-rail";
import { TimelineReplay } from "@/components/chain/timeline-replay";
import { EntityGraph } from "@/components/graph/entity-graph";
import { Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useAlert, useReplay } from "@/lib/api";
import { cn, duration, hhmm, LANE_LABEL, stamp } from "@/lib/format";
import { useAlertParam, useParam } from "@/lib/params";
import type { Lane } from "@/lib/types";

const LANES: Lane[] = ["IAM", "SOC", "FRAUD", "AML", "HR"];
const LANE_TEXT: Record<Lane, string> = { IAM: "text-ai", SOC: "text-amber", FRAUD: "text-threat", AML: "text-info", HR: "text-ok" };

function Replayer() {
  const [alertId, setAlert] = useAlertParam("INSIDER_ATO");
  const [at] = useParam("at");
  const { data: replay, error } = useReplay(alertId);
  const { data: alert } = useAlert(alertId);
  const [asOf, setAsOf] = useState<string | null>(at);
  useEffect(() => setAsOf(at), [alertId, at]);

  const known = replay?.events.filter((e) => !asOf || e.t <= asOf) ?? [];
  const moneyGone = replay?.links.find((l) => l.code === "E5" && (!asOf || l.t <= asOf));

  return (
    <div className="mx-auto max-w-[1600px] p-5">
      <PageHeader eyebrow="Intelligence · Timeline Replay"
        title={<>What did the bank know at <span className="num text-threat">{asOf ? hhmm(asOf) : "the end"}</span>?</>}
        sub="Scrub the evening. Each team's system saw a piece — IAM the privilege, SOC the odd login, Fraud the payee, AML the layering. Nobody saw the thread until SUTRA joined them."
        right={<AlertPicker value={alertId} onChange={(v) => { setAsOf(null); setAlert(v); }} />} />
      {error && <ErrorBox error={error} />}
      {!replay && !error && <Skeleton className="h-[520px]" />}

      {replay && (
        <>
          <Panel className="mb-4 p-4">
            {replay ? <TimelineReplay replay={replay} asOf={asOf} onAsOf={setAsOf} /> : null}
          </Panel>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <Panel className="overflow-hidden">
              <PanelHead eyebrow={`As of ${asOf ? stamp(asOf) : "end of window"}`} title="The money and the people, as they appeared"
                right={moneyGone ? <Chip tone="threat">money has left</Chip> : <Chip tone="ok">money still in the bank</Chip>} />
              <div className="h-[440px] border-t border-line">
                <EntityGraph nodes={replay.nodes} edges={replay.edges} asOf={asOf} particles />
              </div>
            </Panel>

            <Panel>
              <PanelHead eyebrow="Silos" title="What each team could see on its own" />
              <div className="space-y-2 px-4 pb-4">
                {LANES.map((lane) => {
                  const ev = known.filter((e) => e.lane === lane);
                  return (
                    <div key={lane} className="rounded-lg border border-line p-2.5">
                      <div className="mb-1 flex items-center justify-between">
                        <span className={cn("text-[12px] font-semibold", LANE_TEXT[lane])}>{LANE_LABEL[lane]}</span>
                        <span className="num text-[11px] text-faint">{ev.length} event{ev.length === 1 ? "" : "s"}</span>
                      </div>
                      <AnimatePresence initial={false}>
                        {ev.length === 0 && <motion.p key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-1.5 text-[11.5px] text-faint"><EyeOff size={12} /> nothing yet</motion.p>}
                        {ev.slice(-3).map((e) => (
                          <motion.div key={`${e.t}-${e.code}-${e.title}`} layout initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}
                            className="flex gap-2 py-0.5 text-[11.5px]">
                            <span className="num w-10 shrink-0 text-faint">{hhmm(e.t)}</span>
                            <span className="text-ink-2"><b className="font-medium text-ink">{e.title}</b> — {e.detail}</span>
                          </motion.div>
                        ))}
                      </AnimatePresence>
                    </div>
                  );
                })}
                <div className="rounded-lg border border-threat/30 bg-threat-soft/30 p-2.5">
                  <div className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold text-threat"><Link2 size={13} /> SUTRA · joined</div>
                  <p className="text-[11.5px] text-ink-2">
                    {known.length} events across {new Set(known.map((e) => e.lane)).size} teams form one chain
                    {alert?.latency_s ? <> — access to money in <b className="text-ink">{duration(alert.latency_s)}</b></> : null}.
                  </p>
                </div>
              </div>
            </Panel>
          </div>

          <Panel className="mt-4 p-4">
            <div className="eyebrow mb-3">The thread</div>
            <ChainRail links={replay.links} asOf={asOf} latencyS={alert?.headline.access_to_money_s} leadS={alert?.headline.enabling_privilege_lead_s} />
          </Panel>
        </>
      )}
    </div>
  );
}

export default function ReplayPage() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[520px]" /></div>}><Replayer /></Suspense>;
}
