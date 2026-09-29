"use client";

import { motion } from "motion/react";
import { ArrowRight, Landmark } from "lucide-react";
import Link from "next/link";

import { DimBars, TypologyChip } from "@/components/chain/alert-bits";
import { AgentAvatar, stanceOf } from "@/components/council/council";
import { PageHeader, Panel, PanelHead, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { useAlerts, useCouncil } from "@/lib/api";
import { cn, inr } from "@/lib/format";

const PROTOCOL = [
  ["Independent investigation", "Each agent reads the evidence alone and states a position with its evidence codes."],
  ["Cross-examination", "Agents challenge each other's claims. The Defence Agent must test the innocent readings."],
  ["Evidence requests", "An agent that cannot settle a point asks for a record. The moderator retrieves it — or records that it is not ingested."],
  ["Rebuttal & update", "Claims are re-marked supported, contested, unexplained, missing or contradictory."],
  ["Gap detection", "The Evidence Agent lists what nobody could see, and what each gap could change."],
  ["Structured finding", "Consensus and dissent are recorded side by side. The case goes to a human."],
];

export default function CouncilIndex() {
  const { data: alerts } = useAlerts();
  const { data: sample } = useCouncil(alerts?.[0]?.id);

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader eyebrow="Council · Investigation Council" title="Eight agents. One set of records. A human decides."
        sub="The council is adversarial by design: four agents argue the case, one argues against it, three are neutral finders. None can create evidence, score a case or close it." />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel>
          <PanelHead eyebrow="Convene" title="Cases ready for the council" />
          <div className="px-2 pb-2">
            {!alerts && <Skeleton className="m-2 h-40" />}
            {alerts?.map((a, i) => (
              <motion.div key={a.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                <Link href={`/council/${a.id}`} className="group flex items-center gap-3 rounded-lg px-3 py-3 hover:bg-panel-2">
                  <span className="shrink-0"><PriorityPill p={a.priority} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] text-ink">{a.claim}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2"><span className="num whitespace-nowrap text-[11px] text-faint">{a.id}</span><TypologyChip t={a.typology} label={a.typology_label} /></div>
                  </div>
                  <DimBars dims={a.dims} className="hidden lg:flex" />
                  <span className="num w-16 shrink-0 whitespace-nowrap text-right text-[13px] font-semibold text-threat">{inr(a.amount_at_risk)}</span>
                  <span className="flex shrink-0 items-center gap-1 rounded-md border border-ai/30 bg-ai-soft px-2 py-1 text-[12px] text-ai opacity-80 group-hover:opacity-100">
                    <Landmark size={13} /> <span className="hidden sm:inline">Convene</span> <ArrowRight size={12} />
                  </span>
                </Link>
              </motion.div>
            ))}
          </div>
        </Panel>

        <Panel>
          <PanelHead eyebrow="Protocol" title="How a session runs" />
          <ol className="relative space-y-3 px-4 pb-4">
            <span className="absolute bottom-6 left-[27px] top-2 w-px bg-line" />
            {PROTOCOL.map(([t, d], i) => (
              <motion.li key={t} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + i * 0.07 }} className="relative flex gap-3">
                <span className="num relative z-10 grid size-6 shrink-0 place-items-center rounded-full border border-line-strong bg-panel text-[11px] text-ink">{i + 1}</span>
                <div><div className="text-[13px] font-semibold text-ink">{t}</div><p className="text-[12px] text-muted">{d}</p></div>
              </motion.li>
            ))}
          </ol>
        </Panel>
      </div>

      <Panel className="mt-4">
        <PanelHead eyebrow="Agent registry" title="Who sits on the council" />
        <div className="grid gap-3 px-4 pb-4 sm:grid-cols-2 xl:grid-cols-4">
          {!sample && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
          {sample?.agents.map((a, i) => (
            <motion.div key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
              whileHover={{ y: -2 }} className="rounded-lg border border-line bg-panel-2 p-3.5">
              <div className="flex items-center gap-2.5">
                <AgentAvatar agent={a} size={34} />
                <div><div className="text-[13px] font-semibold text-ink">{a.name}</div>
                  <div className={cn("text-[11px]", stanceOf(a.stance).text)}>{stanceOf(a.stance).label}</div></div>
              </div>
              <p className="mt-2.5 text-[12px] leading-relaxed text-muted">{a.job}</p>
            </motion.div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
