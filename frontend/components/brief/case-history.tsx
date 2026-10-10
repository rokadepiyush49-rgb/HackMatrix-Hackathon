"use client";

// The case's history: every revision detection wrote, what changed and why. Revisions are append-only,
// so earlier states stay visible — including what a late or duplicated row did (and did not) change.

import { ChevronDown, Clock3, Copy, History } from "lucide-react";
import { useState } from "react";

import { Chip, Panel, PanelHead, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, inr, stamp } from "@/lib/format";
import type { CaseRevision } from "@/lib/types";

const STATUS_TONE = { OPENED: "info", REVISED: "amber", WITHDRAWN: "faint" } as const;

function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toFixed(3);
  return String(v);
}

export function CaseHistory({ alertId }: { alertId: string }) {
  const { data, isLoading } = useGet<{ revisions: CaseRevision[]; note: string }>(["revisions", alertId], `/alerts/${alertId}/revisions`);
  const [open, setOpen] = useState<number | null>(null);
  const revs = [...(data?.revisions ?? [])].reverse();
  return (
    <Panel className="flex flex-col">
      <PanelHead eyebrow="Case history" title="How this case changed as events arrived"
        right={<Chip tone="faint"><History size={11} /> {revs.length} revision{revs.length === 1 ? "" : "s"}</Chip>} />
      <div className="max-h-[420px] space-y-2 overflow-y-auto px-4 pb-4">
        {isLoading && <Skeleton className="h-24" />}
        {!isLoading && revs.length === 0 && (
          <p className="text-[12.5px] text-muted">No revisions yet. Detection writes one the next time it runs.</p>
        )}
        {revs.map((r) => {
          const late = Object.keys(r.trigger?.late ?? {}).length;
          const expanded = open === r.rev;
          return (
            <div key={r.rev} className="rounded-lg border border-line">
              <button onClick={() => setOpen(expanded ? null : r.rev)} aria-expanded={expanded}
                className="flex w-full items-start gap-2.5 px-3 py-2 text-left">
                <span className="num mt-0.5 text-[11px] text-faint">r{r.rev}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Chip tone={STATUS_TONE[r.status]}>{r.status.toLowerCase()}</Chip>
                    {r.priority && <PriorityPill p={r.priority} />}
                    {late > 0 && <Chip tone="amber"><Clock3 size={11} /> {late} late row{late === 1 ? "" : "s"}</Chip>}
                    {(r.trigger?.duplicates ?? 0) > 0 && <Chip tone="faint"><Copy size={11} /> {r.trigger.duplicates} duplicates absorbed</Chip>}
                    <span className="ml-auto text-[11px] text-faint">{stamp(r.at)}</span>
                  </div>
                  <p className="mt-1 text-[12.5px] text-ink">{r.summary}</p>
                  <p className="text-[11px] text-muted">
                    {r.evidence_count} evidence · {inr(r.amount_at_risk)} at risk
                    {r.suspicion_p !== null && <> · M7 suspicion {r.suspicion_p.toFixed(2)} <span className="text-faint">(a reason to look first, not a finding)</span></>}
                  </p>
                </div>
                <ChevronDown size={14} className={cn("mt-1 shrink-0 text-faint transition-transform", expanded && "rotate-180")} />
              </button>
              {expanded && (
                <div className="space-y-1.5 border-t border-line px-3 py-2">
                  {r.changes.map((ch, i) => (
                    <div key={i} className="text-[12px]">
                      <span className="font-medium text-ink">{ch.field}</span>
                      {ch.before !== null && ch.after !== null && (ch.field !== "status") && (
                        <span className="num ml-1.5 text-muted">{value(ch.before)} → {value(ch.after)}</span>
                      )}
                      <p className="text-ink-2">{ch.why}</p>
                    </div>
                  ))}
                  <p className="num pt-1 text-[10.5px] text-faint">run {r.run_id} · state {r.snapshot_sha256.slice(0, 16)}…</p>
                </div>
              )}
            </div>
          );
        })}
        {data?.note && <p className="pt-1 text-[11px] text-faint">{data.note}</p>}
      </div>
    </Panel>
  );
}
