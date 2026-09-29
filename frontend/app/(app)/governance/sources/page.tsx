"use client";

import { motion } from "motion/react";
import { DatabaseZap, PlugZap } from "lucide-react";

import { Chip, ErrorBox, PageHeader, Panel, Skeleton } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, stamp } from "@/lib/format";

interface Source { system: string; table: string; rows: number; latest: string | null; status: "LIVE" | "NOT_CONNECTED" }

export default function Sources() {
  const { data, error } = useGet<Source[]>(["sources"], "/governance/sources");
  const max = Math.max(...(data?.map((s) => s.rows) ?? [1]));
  return (
    <div className="mx-auto max-w-[1200px] p-5">
      <PageHeader eyebrow="Governance · Data Sources" title="What SUTRA can see — and what it can't"
        sub="Loom keeps every source bitemporal: when something happened, and when the bank learned it. Sources that are not connected are listed openly, because their absence limits what any finding can claim." />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Skeleton className="h-80" />}
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map((s, i) => (
          <motion.div key={s.system} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
            <Panel className={cn("h-full p-4", s.status !== "LIVE" && "border-dashed")}>
              <div className="flex items-center gap-2">
                {s.status === "LIVE" ? <DatabaseZap size={16} className="text-ok" /> : <PlugZap size={16} className="text-faint" />}
                <span className="text-[13.5px] font-semibold text-ink">{s.system}</span>
                <Chip tone={s.status === "LIVE" ? "ok" : "faint"} className="ml-auto">{s.status === "LIVE" ? "live" : "not connected"}</Chip>
              </div>
              {s.status === "LIVE" ? (
                <>
                  <div className="mt-3 flex items-baseline justify-between text-[12px]">
                    <span className="font-mono text-[11px] text-muted">{s.table}</span>
                    <span className="num text-ink">{s.rows.toLocaleString("en-IN")} rows</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-panel-2">
                    <motion.div className="h-full bg-ok" initial={{ width: 0 }} animate={{ width: `${Math.max(2, (Math.log10(s.rows + 1) / Math.log10(max + 1)) * 100)}%` }} transition={{ delay: 0.1 + i * 0.05, duration: 0.6 }} />
                  </div>
                  <div className="mt-1.5 text-[11px] text-faint">latest record {stamp(s.latest)}</div>
                </>
              ) : (
                <p className="mt-2 text-[12px] text-muted">Findings that depend on this source are marked as gaps and routed to manual collection.</p>
              )}
            </Panel>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
