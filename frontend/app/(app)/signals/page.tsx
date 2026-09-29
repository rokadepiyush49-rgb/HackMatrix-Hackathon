"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Filter, Keyboard, Landmark, Radio } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ChainRail } from "@/components/chain/chain-rail";
import { DimBars, TypologyChip } from "@/components/chain/alert-bits";
import { useLive } from "@/components/shell/live";
import { Button, Chip, Empty, ErrorBox, Kbd, PageHeader, Panel, PanelHead, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { useAlert, useAlerts } from "@/lib/api";
import { cn, duration, hhmm, inr, stamp } from "@/lib/format";

const FILTERS = [
  { key: "queued", label: "Queued", q: "" },
  { key: "p1", label: "P1 only", q: "?priority=P1" },
  { key: "all", label: "Incl. watch-list & explained", q: "?include_watch=true&priority=P1&priority=P2&priority=P3&priority=WATCH&priority=EXPLAINED" },
];

export default function SignalDesk() {
  const router = useRouter();
  const [filter, setFilter] = useState("queued");
  const { data, error, isLoading } = useAlerts(FILTERS.find((f) => f.key === filter)!.q);
  const [sel, setSel] = useState(0);
  const rows = useMemo(() => data ?? [], [data]);
  const current = rows[sel];
  const { data: detail } = useAlert(current?.id);
  const live = useLive();

  useEffect(() => setSel(0), [filter]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "j") setSel((s) => Math.min(s + 1, rows.length - 1));
      if (e.key === "k") setSel((s) => Math.max(s - 1, 0));
      if (e.key === "Enter" && rows[sel]) router.push(`/cases/${rows[sel].id}`);
      if (e.key === "c" && rows[sel]) router.push(`/council/${rows[sel].id}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, sel, router]);

  const liveAlerts = live.events.filter((e) => e.type === "alert");

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader
        eyebrow="Investigate · Signal Desk"
        title="Argued alerts, ready for triage"
        sub="Every row is a chain that survived Alibi and the priority rules — never a raw detector hit. Signals alone never reach this queue."
        right={<span className="flex items-center gap-1.5 text-[11.5px] text-muted"><Keyboard size={13} /> <Kbd>J</Kbd><Kbd>K</Kbd> move · <Kbd>↵</Kbd> open · <Kbd>C</Kbd> council</span>}
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Filter size={14} className="text-faint" />
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={cn("rounded-full border px-3 py-1 text-[12.5px] font-medium", filter === f.key ? "border-ink bg-ink text-bg" : "border-line text-muted hover:text-ink")}>
            {f.label}
          </button>
        ))}
        {live.running && <Chip tone="threat" className="ml-auto"><Radio size={11} /> replay {hhmm(live.clock)} · {liveAlerts.length} alert(s) raised so far</Chip>}
      </div>

      {error && <ErrorBox error={error} />}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Panel className="overflow-hidden">
          <div className="grid grid-cols-[108px_minmax(0,1fr)_64px_78px_70px] gap-3 border-b border-line px-4 py-2 eyebrow">
            <span>Priority</span><span>Claim</span><span>Dims</span><span className="text-right">At risk</span><span className="text-right">Raised</span>
          </div>
          {isLoading && <div className="space-y-2 p-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
          {!isLoading && rows.length === 0 && <Empty title="Queue is clear">No argued alerts match this filter.</Empty>}
          <div className="max-h-[calc(100vh-270px)] overflow-y-auto">
            {rows.map((a, i) => (
              <motion.button
                key={a.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i, 12) * 0.03 }}
                onClick={() => setSel(i)}
                onDoubleClick={() => router.push(`/cases/${a.id}`)}
                className={cn(
                  "relative grid w-full grid-cols-[108px_minmax(0,1fr)_64px_78px_70px] items-center gap-3 border-b border-line px-4 py-3 text-left transition-colors last:border-0",
                  i === sel ? "bg-panel-2" : "hover:bg-panel-2/60",
                )}
              >
                {i === sel && <motion.span layoutId="sel-bar" className="absolute inset-y-0 left-0 w-[3px] bg-threat" />}
                <div className="flex flex-col gap-1"><PriorityPill p={a.priority} /><span className="num text-[10.5px] text-faint">{a.id}</span></div>
                <div className="min-w-0">
                  <div className="line-clamp-2 text-[12.5px] leading-snug text-ink">{a.claim}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <TypologyChip t={a.typology} label={a.typology_label} />
                    {a.latency_s != null && <span className="text-[11px] text-muted">latency {duration(a.latency_s)}</span>}
                    {a.state !== "OPEN" && <Chip tone="info">{a.state.toLowerCase()}</Chip>}
                  </div>
                </div>
                <DimBars dims={a.dims} />
                <span className="num text-right text-[13px] font-semibold text-threat">{inr(a.amount_at_risk)}</span>
                <span className="num text-right text-[11px] text-muted">{stamp(a.created_at).replace(" ", " ")}</span>
              </motion.button>
            ))}
          </div>
        </Panel>

        <Panel className="sticky top-[76px] h-fit">
          <AnimatePresence mode="wait">
            {current && (
              <motion.div key={current.id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                <PanelHead eyebrow={`Preview · ${current.id}`} title={current.typology_label}
                  right={<><Button size="sm" variant="ai" onClick={() => router.push(`/council/${current.id}`)}><Landmark size={13} /> Council</Button>
                    <Button size="sm" variant="primary" onClick={() => router.push(`/cases/${current.id}`)}>Open case <ArrowRight size={13} /></Button></>} />
                <div className="space-y-3 px-4 pb-4">
                  <p className="text-[13px] leading-relaxed text-ink">{current.summary ?? current.claim}</p>
                  <div className="rounded-lg border border-line bg-panel-2 p-3 text-[12px] leading-relaxed text-ink-2">
                    <div className="eyebrow mb-1">Why this priority</div>{current.lattice_rule}
                  </div>
                  {detail?.id === current.id ? (
                    <>
                      <ChainRail links={detail.links} compact />
                      <div className="grid grid-cols-2 gap-2">
                        {detail.argument.rebuttals.slice(0, 4).map((r) => (
                          <div key={r.hypothesis} className="rounded-md border border-line px-2.5 py-1.5 text-[11.5px]">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-ink">{r.hypothesis}</span>
                              <Chip tone={r.status === "open" ? "amber" : r.status === "supported" ? "ok" : "faint"}>{r.status}</Chip>
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : <Skeleton className="h-28" />}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </Panel>
      </div>
    </div>
  );
}
