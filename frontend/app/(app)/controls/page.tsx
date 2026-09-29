"use client";

import * as Switch from "@radix-ui/react-switch";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Lightbulb, Scissors, ShieldCheck, ShieldOff, Sparkles } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";

import { AlertPicker } from "@/components/chain/alert-bits";
import { ChainRail } from "@/components/chain/chain-rail";
import { Button, Chip, CountUp, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useAlert, useMend } from "@/lib/api";
import { cn, duration, inr, pct, stamp } from "@/lib/format";
import { useAlertParam } from "@/lib/params";
import type { MendControl } from "@/lib/types";

// A control that fires at E0 lets the grant happen but makes it lapse: the chain is cut before E1.
const sever = (link?: string | null) => (link === "E0" ? "E1" : link ?? null);

function ControlCard({ c, on, onToggle, i }: { c: MendControl; on: boolean; onToggle: () => void; i: number }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: i * 0.04 }}
      className={cn(
        "rounded-lg border p-3 transition-colors",
        !c.applicable ? "border-dashed border-line opacity-55" : on ? "border-ok/50 bg-ok-soft/30" : "border-line hover:border-line-strong",
      )}
    >
      <div className="flex items-start gap-3">
        <Switch.Root
          checked={on}
          onCheckedChange={onToggle}
          disabled={!c.applicable}
          aria-label={`Apply ${c.name}`}
          className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full border border-line-strong bg-panel-2 transition-colors data-[state=checked]:border-ok data-[state=checked]:bg-ok disabled:cursor-not-allowed"
        >
          <Switch.Thumb className="block size-4 translate-x-0.5 rounded-full bg-ink shadow transition-transform data-[state=checked]:translate-x-[17px] data-[state=checked]:bg-white" />
        </Switch.Root>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="num text-[11px] text-faint">{c.id}</span>
            <span className="text-[13px] font-semibold text-ink">{c.name}</span>
          </div>
          <p className="mt-0.5 text-[12px] text-muted">{c.description}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Chip tone="info">breaks at {c.breaks_at}</Chip>
            <Chip tone={c.effort === "Low" ? "ok" : c.effort === "Medium" ? "amber" : "threat"}>{c.effort} effort</Chip>
            {!c.applicable && <Chip tone="faint">does not apply to this typology</Chip>}
            {c.applicable && c.breaks && c.lead_time_s !== null && (
              <Chip tone={c.lead_time_s > 3600 ? "ok" : "amber"}>{c.lead_time_s > 0 ? `${duration(c.lead_time_s)} early` : "at the payout"}</Chip>
            )}
            {c.applicable && !c.breaks && <Chip tone="threat">would not have stopped it</Chip>}
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
            <div><div className="text-faint">legit ops hit / 90d</div><div className="num text-ink">{c.friction.legit_ops_affected ?? 0}</div></div>
            <div><div className="text-faint">extra approvals / day</div><div className="num text-ink">{(c.friction.extra_approvals_per_day ?? 0).toFixed(1)}</div></div>
            <div><div className="text-faint">share of sensitive ops</div><div className="num text-ink">{pct(c.friction.share_of_sensitive_ops ?? 0, 2)}</div></div>
          </div>
          {c.friction.customer_delay && <p className="mt-1.5 text-[11px] text-faint">Customer impact: {c.friction.customer_delay}</p>}
        </div>
      </div>
    </motion.div>
  );
}

function Lab() {
  const [alertId, setAlert] = useAlertParam("INSIDER_ATO");
  const [selected, setSelected] = useState<string[]>([]);
  const { data: alert } = useAlert(alertId);
  const { data: m, error, isFetching } = useMend(alertId, selected);
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const r = m?.result;
  const broke = !!r?.breaks && selected.length > 0;

  // Controls that land on the same spot share one labelled point.
  const grouped = new Map<string, { id: string; ids: string[]; name: string; x: number; y: number; z: number }>();
  for (const c of (m?.controls ?? []).filter((c) => c.applicable && c.breaks)) {
    const x = c.friction.legit_ops_affected ?? 0;
    const y = Math.max(0, (c.lead_time_s ?? 0) / 3600);
    const k = `${x}|${y.toFixed(1)}`;
    const g = grouped.get(k);
    if (g) { g.ids.push(c.id); g.id = g.ids.join(" · "); g.name += ` / ${c.name}`; }
    else grouped.set(k, { id: c.id, ids: [c.id], name: c.name, x, y, z: 1 });
  }
  const points = [...grouped.values()];

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader
        eyebrow="Prevent · Control Lab"
        title="What if the control had been in place?"
        sub="Replays the real chain against each control. A control counts only if it would have stopped a hop before the money left — and every control shows the friction it would have added on 90 days of legitimate work."
        right={<AlertPicker value={alertId} onChange={(v) => { setSelected([]); setAlert(v); }} />}
      />
      {error && <ErrorBox error={error} />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <Panel>
          <PanelHead eyebrow="Controls" title="Toggle to test" right={selected.length > 0 && <Button size="sm" variant="ghost" onClick={() => setSelected([])}>Reset</Button>} />
          <div className="space-y-2 px-4 pb-4">
            {!m && <Skeleton className="h-64" />}
            {m?.controls
              .slice()
              .sort((a, b) => Number(b.applicable) - Number(a.applicable))
              .map((c, i) => <ControlCard key={c.id} c={c} i={i} on={selected.includes(c.id)} onToggle={() => toggle(c.id)} />)}
          </div>
        </Panel>

        <div className="space-y-4">
          <Panel className="overflow-hidden">
            <PanelHead eyebrow="Replay with controls applied" title={alert?.typology_label ?? "Chain"}
              right={isFetching ? <Chip tone="ai">simulating…</Chip> : broke ? <Chip tone="ok"><Scissors size={11} /> chain broken</Chip> : <Chip tone="threat">chain completes</Chip>} />
            <div className="px-4 pb-4">
              {alert ? (
                <ChainRail links={alert.links} severAt={broke ? sever(r?.broken_at?.link) : null} />
              ) : <Skeleton className="h-28" />}
              <AnimatePresence mode="wait">
                <motion.div key={broke ? `b-${r?.broken_at?.link}-${selected.join()}` : "none"} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className={cn("mt-3 rounded-lg border px-4 py-3", broke ? "border-ok/30 bg-ok-soft/40" : "border-threat/25 bg-threat-soft/40")}>
                  {broke && r?.broken_at ? (
                    <div className="flex items-start gap-3">
                      <ShieldCheck size={20} className="mt-0.5 shrink-0 text-ok" />
                      <div>
                        <div className="text-[13.5px] font-semibold text-ink">Stopped at {r.broken_at.link} · {stamp(r.broken_at.at)}</div>
                        <p className="text-[12.5px] text-ink-2">{r.broken_at.why}.</p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3">
                      <ShieldOff size={20} className="mt-0.5 shrink-0 text-threat" />
                      <p className="text-[12.5px] text-ink-2">{selected.length ? "The selected controls would not have stopped this chain before the money moved." : "With today's controls the chain ran to completion. Toggle a control on the left to replay it."}</p>
                    </div>
                  )}
                </motion.div>
              </AnimatePresence>

              <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[
                  { k: "Money kept in the bank", v: broke ? r!.prevented : 0, f: (v: number) => inr(v), tone: broke ? "text-ok" : "text-faint" },
                  { k: "Stopped before payout", v: broke ? (r!.lead_time_s ?? 0) : 0, f: (v: number) => (v > 0 ? duration(v) : "—"), tone: "text-ink" },
                  { k: "Legit operations affected / 90d", v: r?.legit_ops_affected ?? 0, f: (v: number) => Math.round(v).toString(), tone: "text-ink" },
                  { k: "Extra approvals per day", v: r?.extra_approvals_per_day ?? 0, f: (v: number) => v.toFixed(1), tone: "text-ink" },
                ].map((x) => (
                  <div key={x.k} className="rounded-lg border border-line bg-panel-2 px-3 py-2.5">
                    <div className="text-[11px] text-faint">{x.k}</div>
                    <div className={cn("display mt-0.5 text-[22px] font-bold", x.tone)}><CountUp key={`${x.k}-${x.v}`} value={x.v} format={x.f} /></div>
                  </div>
                ))}
              </div>
            </div>
          </Panel>

          {m?.recommended && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              <Panel className="border-ai/30">
                <div className="flex flex-wrap items-start gap-4 p-4">
                  <span className="grid size-10 place-items-center rounded-full bg-ai-soft text-ai"><Lightbulb size={20} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="eyebrow !text-ai">Recommended intervention</div>
                    <div className="display text-[17px] font-semibold text-ink">{m.recommended.id} · {m.recommended.name}</div>
                    <p className="mt-0.5 text-[12.5px] text-ink-2">
                      {m.recommended.why}. Breaks the chain <b className="text-ink">{duration(m.recommended.lead_time_s)}</b> before the payout and touches{" "}
                      <b className="text-ink">{m.recommended.legit_ops_affected}</b> legitimate operations in 90 days — the earliest break with the least friction.
                    </p>
                  </div>
                  <Button variant="ai" onClick={() => setSelected([m.recommended!.id])}><Sparkles size={14} /> Apply in the lab</Button>
                </div>
              </Panel>
            </motion.div>
          )}

          <Panel>
            <PanelHead eyebrow="Trade-off" title="How early it stops the chain vs. how much it gets in the way" />
            <div className="h-[260px] px-2 pb-3">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 10, right: 24, bottom: 24, left: 8 }}>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="x" scale="sqrt" domain={[0, "auto"]} name="Legit ops affected" tick={{ fill: "var(--muted)", fontSize: 11 }} stroke="var(--line)"
                    label={{ value: "legitimate operations affected (90 days)", position: "insideBottom", offset: -12, fill: "var(--faint)", fontSize: 11 }} />
                  <YAxis type="number" dataKey="y" scale="sqrt" domain={[0, "auto"]} name="Lead time (h)" tick={{ fill: "var(--muted)", fontSize: 11 }} stroke="var(--line)"
                    label={{ value: "hours before payout", angle: -90, position: "insideLeft", fill: "var(--faint)", fontSize: 11 }} />
                  <ZAxis dataKey="z" range={[110, 110]} />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ payload }) => {
                    const p = payload?.[0]?.payload as (typeof points)[number] | undefined;
                    return p ? <div className="rounded-md border border-line-strong bg-raised px-2.5 py-1.5 text-[12px] text-ink"><b>{p.id}</b> {p.name}<br />{duration(p.y * 3600)} early · {p.x} legit ops</div> : null;
                  }} />
                  <Scatter data={points} fill="var(--ai)" shape={(props: { cx?: number; cy?: number; payload?: { id: string; ids: string[] } }) => {
                    const on = props.payload?.ids.some((x) => selected.includes(x));
                    return (
                      <g>
                        <circle cx={props.cx} cy={props.cy} r={on ? 9 : 7} fill={on ? "var(--ok)" : "var(--ai)"} fillOpacity={0.85} />
                        <text x={(props.cx ?? 0) + 11} y={(props.cy ?? 0) + 4} fontSize={11} fill="var(--ink-2)">{props.payload?.id}</text>
                      </g>
                    );
                  }} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <p className="px-4 pb-3 text-[11px] text-faint">{m?.note} Top-left is best: stops early, disturbs little.</p>
          </Panel>

          <div className="flex justify-end">
            <Link href="/controls/library" className="inline-flex items-center gap-1 text-[12.5px] text-info hover:underline">Coverage across every open case <ArrowRight size={13} /></Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ControlLab() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[480px]" /></div>}><Lab /></Suspense>;
}
