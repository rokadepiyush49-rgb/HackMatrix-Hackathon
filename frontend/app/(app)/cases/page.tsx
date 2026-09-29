"use client";

import { motion } from "motion/react";
import { ArrowRight, Clock, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { DimBars, TypologyChip } from "@/components/chain/alert-bits";
import { Chip, Empty, PageHeader, Panel, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { useAlerts, useCases } from "@/lib/api";
import { cn, duration, inr, stamp } from "@/lib/format";
import type { CaseFile } from "@/lib/types";

const COLUMNS = [
  { key: "INVESTIGATING", title: "Investigating", tone: "text-amber" },
  { key: "REVIEW", title: "Four-eyes review", tone: "text-ai" },
  { key: "CLOSED", title: "Closed", tone: "text-ok" },
];

function CaseCard({ c, i }: { c: CaseFile; i: number }) {
  const left = c.sla_due_at ? (new Date(c.sla_due_at).getTime() - Date.now()) / 1000 : null;
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
      <Link href={`/cases/${c.alert_id}`} className="block rounded-lg border border-line bg-panel-2 p-3 transition-colors hover:border-line-strong">
        <div className="flex items-center gap-2">
          <PriorityPill p={c.priority} />
          <span className="num ml-auto whitespace-nowrap text-[12.5px] font-semibold text-threat">{inr(c.alert.amount_at_risk)}</span>
        </div>
        <div className="num mt-1 text-[10.5px] text-faint">{c.id} · {c.alert_id}
        </div>
        <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-snug text-ink">{c.title}</p>
        <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
          <span className="text-ink-2">{c.assignee_name ?? "Unassigned"}</span>
          {c.decision && <Chip tone={c.decision === "ESCALATE" ? "threat" : c.decision === "BENIGN" ? "ok" : "amber"}>{c.decision}</Chip>}
          {left !== null && !c.state.startsWith("CLOSED") && (
            <span className={cn("ml-auto flex items-center gap-1", left < 0 ? "text-threat" : left < 1800 ? "text-amber" : "")}>
              <Clock size={11} /> {left < 0 ? `SLA +${duration(-left)}` : duration(left)}
            </span>
          )}
          {c.closed_at && <span className="ml-auto">{stamp(c.closed_at)}</span>}
        </div>
      </Link>
    </motion.div>
  );
}

export default function CaseDesk() {
  const router = useRouter();
  const { data: cases, isLoading } = useCases();
  const { data: alerts } = useAlerts();
  const opened = new Set(cases?.map((c) => c.alert_id));
  const waiting = alerts?.filter((a) => !opened.has(a.id)) ?? [];

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader eyebrow="Investigate · Case Desk" title="Cases by state"
        sub="Opening an alert creates a case with an SLA from its priority. Closing needs a second person — the four-eyes rule is enforced by the API, not the screen." />
      <div className="grid gap-4 lg:grid-cols-4">
        <Panel className="p-3">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="eyebrow !text-threat">Waiting to be opened</span>
            <span className="num text-[11px] text-faint">{waiting.length}</span>
          </div>
          <div className="space-y-2">
            {waiting.map((a, i) => (
              <motion.button key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}
                onClick={() => router.push(`/cases/${a.id}`)}
                className="group w-full rounded-lg border border-dashed border-line-strong p-3 text-left hover:border-threat/50">
                <div className="flex items-center gap-2">
                  <PriorityPill p={a.priority} /><span className="num text-[11px] text-faint">{a.id}</span>
                  <Plus size={14} className="ml-auto text-faint group-hover:text-threat" />
                </div>
                <p className="mt-1.5 line-clamp-2 text-[12.5px] text-ink">{a.claim}</p>
                <div className="mt-2 flex items-center justify-between"><TypologyChip t={a.typology} label={a.typology_label} /><DimBars dims={a.dims} /></div>
              </motion.button>
            ))}
            {waiting.length === 0 && <p className="px-1 text-[12px] text-muted">Every queued alert has a case.</p>}
          </div>
        </Panel>
        {COLUMNS.map((col) => {
          const list = cases?.filter((c) => (col.key === "CLOSED" ? c.state.startsWith("CLOSED") : c.state === col.key)) ?? [];
          return (
            <Panel key={col.key} className="p-3">
              <div className="mb-2 flex items-center justify-between px-1">
                <span className={cn("eyebrow", col.tone)}>{col.title}</span>
                <span className="num text-[11px] text-faint">{list.length}</span>
              </div>
              <div className="space-y-2">
                {isLoading && <Skeleton className="h-24" />}
                {list.map((c, i) => <CaseCard key={c.id} c={c} i={i} />)}
                {!isLoading && list.length === 0 && <Empty title="Nothing here">{col.key === "REVIEW" ? "Proposed decisions wait here for a second reviewer." : "—"}</Empty>}
              </div>
            </Panel>
          );
        })}
      </div>
      <div className="mt-4 text-right">
        <Link href="/signals" className="inline-flex items-center gap-1 text-[12.5px] text-info hover:underline">Triage the queue in Signal Desk <ArrowRight size={13} /></Link>
      </div>
    </div>
  );
}
