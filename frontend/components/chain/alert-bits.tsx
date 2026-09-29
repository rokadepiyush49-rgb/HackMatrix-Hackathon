"use client";

import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { Chip, PriorityPill, Tip } from "@/components/ui/primitives";
import { useAlerts } from "@/lib/api";
import { cn, inr } from "@/lib/format";
import type { AlertSummary, DimLite } from "@/lib/types";

export function DimBars({ dims, className }: { dims: DimLite[]; className?: string }) {
  return (
    <div className={cn("flex gap-[3px]", className)}>
      {dims.map((d) => (
        <Tip key={d.key} content={`${d.label}: ${d.level}`}>
          <span className={cn("h-3.5 w-1.5 rounded-sm",
            d.level === "HIGH" ? "bg-threat" : d.level === "ELEVATED" ? "bg-amber" : d.level === "LOW" ? "bg-ok" : "bg-line")} />
        </Tip>
      ))}
    </div>
  );
}

/** Choose which alert a workbench page (Council, Control Lab, Replay, Evidence) works on. */
export function AlertPicker({ value, onChange, include = "" }: { value?: string | null; onChange: (id: string) => void; include?: string }) {
  const { data } = useAlerts(include);
  const [open, setOpen] = useState(false);
  const cur = data?.find((a) => a.id === value);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button className="flex h-9 w-full min-w-0 items-center gap-2 rounded-md border border-line-strong bg-panel px-3 text-left text-[12.5px] hover:border-info max-w-full sm:w-[420px]">
          {cur ? (
            <>
              <PriorityPill p={cur.priority} />
              <span className="num whitespace-nowrap text-muted">{cur.id}</span>
              <span className="min-w-0 truncate text-ink">{cur.typology_label}</span>
              <span className="num ml-auto whitespace-nowrap text-threat">{inr(cur.amount_at_risk)}</span>
            </>
          ) : <span className="text-faint">Choose a case…</span>}
          <ChevronsUpDown size={14} className="shrink-0 text-faint" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={6} className="z-[75] w-[560px] max-w-[92vw] rounded-lg border border-line-strong bg-raised p-1 shadow-2xl">
          {data?.map((a: AlertSummary) => (
            <button key={a.id} onClick={() => { onChange(a.id); setOpen(false); }}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[12.5px] hover:bg-panel-2">
              <PriorityPill p={a.priority} />
              <span className="num whitespace-nowrap text-muted">{a.id}</span>
              <span className="min-w-0 flex-1 truncate text-ink">{a.claim}</span>
              <span className="num whitespace-nowrap text-threat">{inr(a.amount_at_risk)}</span>
              {a.id === value && <Check size={14} className="text-ok" />}
            </button>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function TypologyChip({ t, label }: { t: string; label: string }) {
  const tone = t === "INSIDER_ATO" ? "threat" : t === "MULE_FACTORY" ? "ai" : t === "EXTERNAL_ATO" ? "amber" : "info";
  return <Chip tone={tone}>{label}</Chip>;
}
