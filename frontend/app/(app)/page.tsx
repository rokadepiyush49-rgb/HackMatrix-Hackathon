"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, CircleCheck, Factory, Landmark, ShieldOff, Sparkles, Timer, UserX, Waypoints, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { ChainRail, LaneLegend } from "@/components/chain/chain-rail";
import { EntityGraph } from "@/components/graph/entity-graph";
import { useLive } from "@/components/shell/live";
import { useUI } from "@/components/shell/ui-context";
import { Funnel } from "@/components/brief/funnel";
import { PathDoodle, Sparkle } from "@/components/ui/doodles";
import { ArrowCTA, Button, Chip, CountUp, Dot, ErrorBox, LevelBar, Panel, PanelHead, PriorityPill, Skeleton, StatTile, Tip, rise, stagger } from "@/components/ui/primitives";
import { useOverview } from "@/lib/api";
import { cn, duration, hhmm, inr, pct, stamp } from "@/lib/format";
import type { GraphEdge } from "@/lib/types";

function EdgeCard({ e, onClose }: { e: GraphEdge; onClose: () => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }}
      className="absolute left-3 top-3 z-20 w-[260px] rounded-3xl border border-coral bg-raised p-4 shadow-2xl">
      <div className="mb-2 flex items-start justify-between">
        <div>
          <div className="display text-[22px] font-semibold leading-none text-threat">{e.amount ? `₹${Math.round(e.amount).toLocaleString("en-IN")}` : e.label}</div>
          <div className="num mt-1 text-[11.5px] text-muted">{stamp(e.t)} {e.channel && `· ${e.channel}`}</div>
        </div>
        <button onClick={onClose} className="rounded p-1 text-faint hover:bg-panel-2" aria-label="Close"><X size={14} /></button>
      </div>
      <dl className="grid grid-cols-[62px_1fr] gap-y-1 text-[12px]">
        <dt className="eyebrow">From</dt><dd className="num text-ink">{e.source}</dd>
        <dt className="eyebrow">To</dt><dd className="num text-ink">{e.target}</dd>
        {e.after_root_s != null && (<><dt className="eyebrow">Trigger</dt><dd className="text-ink-2">{duration(e.after_root_s)} after <b className="text-ink">{e.root_event}</b></dd></>)}
        {e.employee && (<><dt className="eyebrow">Staff</dt><dd className="num text-threat">{e.employee}</dd></>)}
        {e.chain_latency_s != null && (<><dt className="eyebrow">Chain</dt><dd className="text-ink-2">access → money {duration(e.chain_latency_s)}</dd></>)}
      </dl>
    </motion.div>
  );
}

export default function CommandCenter() {
  const { data, error, isLoading } = useOverview();
  const router = useRouter();
  const { openAsk, setFocusAlert } = useUI();
  const live = useLive();
  const [edge, setEdge] = useState<GraphEdge | null>(null);

  const replayAsOf = live.running ? live.clock : null;
  const bypassed = data ? Object.values(data.kpis.controls_bypassed).reduce((a, b) => a + b, 0) : 0;
  const rail = data?.rail;
  const topMoney = useMemo(() => data?.money, [data]);

  if (error) return <div className="p-6"><ErrorBox error={error} /></div>;

  return (
    <div className="mx-auto max-w-[1480px] space-y-4 px-2 pt-1 pb-6">
      {/* bento hero — orchid "at risk" card + periwinkle path card, as on the Disha moodboard */}
      <motion.section variants={stagger} initial="hidden" animate="show" className="grid gap-4 lg:grid-cols-12">
        <motion.div variants={rise} className="relative overflow-hidden rounded-[var(--radius-blob)] bg-orchid p-7 text-pastel-ink lg:col-span-7 xl:p-9">
          <Sparkle className="absolute top-7 right-8 size-7 animate-[var(--animate-twinkle)] text-pastel-ink" fill="var(--color-sunflower)" />
          <div className="mb-3 flex items-center gap-2 text-[12px] font-medium tracking-[0.06em] uppercase opacity-80">
            <Dot tone="threat" pulse /> Command Center · Kestrel UCB
          </div>
          {isLoading || !data ? <Skeleton className="h-14 w-[420px] max-w-full bg-paper/40" /> : (
            <h1 className="display text-[40px] leading-[1.1] font-light xl:text-[52px]">
              <CountUp value={data.hero.amount_at_risk} format={(v) => inr(v)} className="font-semibold" /> at risk
            </h1>
          )}
          {data && (
            <p className="mt-3 flex flex-wrap items-center gap-x-1.5 text-[15px] opacity-85">
              <Sparkles size={15} /> <b>{data.hero.active_chains}</b> active chains · <b>{data.hero.critical}</b> critical ·{" "}
              <b>{data.hero.in_motion}</b> money movements in the last 48 h
            </p>
          )}
          <div className="mt-6 flex flex-wrap items-center gap-4">
            {rail && <ArrowCTA href={`/cases/${rail.alert.id}`} label="Open the top case" />}
            <div className="flex flex-col gap-2">
              <Button variant="primary" className="!bg-pastel-ink !text-paper" disabled={!rail} onClick={() => rail && router.push(`/cases/${rail.alert.id}`)}>
                Open top case <ArrowRight size={14} />
              </Button>
              <Button variant="outline" className="border-transparent !bg-paper !text-pastel-ink" disabled={!rail}
                onClick={() => { if (!rail) return; setFocusAlert(rail.alert.id); openAsk(rail.alert.id, "Why was this flagged?"); }}>
                <Sparkles size={14} /> Why was it flagged?
              </Button>
            </div>
          </div>
          {data && <p className="mt-5 text-[11.5px] opacity-70">Data as of {stamp(data.as_of)} IST · synthetic</p>}
        </motion.div>

        <motion.div variants={rise} className="relative flex flex-col justify-between overflow-hidden rounded-[var(--radius-blob)] bg-periwinkle p-7 text-pastel-ink lg:col-span-5">
          <h2 className="text-center text-[22px] leading-snug">
            Follow the <span className="font-semibold">thread</span> from
            <br />
            <span className="font-semibold">privilege</span> to <span className="font-semibold">payment</span>
          </h2>
          <PathDoodle className="mx-auto my-4 h-24 w-full max-w-xs" current={2} />
          <div className="rounded-full bg-paper px-4 py-2.5">
            <div className="grid grid-cols-3 text-center">
              {[
                { label: "Chains", value: data?.hero.active_chains, disc: "bg-pastel-ink text-paper" },
                { label: "Critical", value: data?.hero.critical, disc: "bg-tangerine" },
                { label: "Moves · 48 h", value: data?.hero.in_motion, disc: "border-2 border-dashed border-pastel-ink/25" },
              ].map((s) => (
                <div key={s.label} className="flex items-center justify-center gap-2">
                  <span className={cn("num grid size-8 shrink-0 place-items-center rounded-full text-[12px] font-semibold", s.disc)}>{s.value ?? "–"}</span>
                  <span className="text-[12px] leading-tight opacity-70">{s.label}</span>
                </div>
              ))}
            </div>
          </div>
          {data?.scenario_summary && (
            <Link href="/lab" className="mt-3 flex items-center justify-center gap-1.5 text-[12px] hover:underline">
              <CircleCheck size={13} /> {data.scenario_summary.passed}/{data.scenario_summary.total} scenario checks pass · {data.scenario_summary.twins_quiet}/{data.scenario_summary.twins_total} twins quiet
            </Link>
          )}
        </motion.div>
      </motion.section>

      {/* live threat rail */}
      <Panel className="overflow-hidden">
        <PanelHead
          eyebrow={<span className="flex items-center gap-2"><Waypoints size={12} /> Live threat rail {live.running && <Chip tone="threat">replaying {hhmm(live.clock)}</Chip>}</span>}
          title={rail ? rail.alert.claim : "…"}
          right={rail && (
            <>
              <PriorityPill p={rail.alert.priority} />
              <Button size="sm" variant="ai" onClick={() => router.push(`/council/${rail.alert.id}`)}><Landmark size={13} /> Council</Button>
              <Button size="sm" variant="primary" onClick={() => router.push(`/cases/${rail.alert.id}`)}>Open case <ArrowRight size={13} /></Button>
            </>
          )}
        />
        <div className="px-4 pb-4">
          {rail ? (
            <>
              <ChainRail links={rail.links} latencyS={rail.alert.latency_s} leadS={rail.links.length ? (new Date(rail.links.find((l) => l.code === "E5")?.t ?? 0).getTime() - new Date(rail.links[0].t).getTime()) / 1000 : null}
                asOf={replayAsOf} onSelect={() => router.push(`/cases/${rail.alert.id}`)} />
              <div className="mt-1 flex items-center justify-between">
                <LaneLegend />
                <button onClick={() => { setFocusAlert(rail.alert.id); openAsk(rail.alert.id, "Why was this flagged?"); }} className="text-[12px] text-ai hover:underline">Why did SUTRA flag this? →</button>
              </div>
            </>
          ) : <Skeleton className="h-32" />}
        </div>
      </Panel>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile tone="coral" icon={<Waypoints size={16} />} label="Active chains" href="/signals"
          value={data ? <CountUp value={data.kpis.active_chains} /> : "—"} sub={data && `${data.hero.critical} critical · from ${data.funnel?.candidate_chains ?? "…"} candidates`} />
        <StatTile tone="orchid" icon={<Landmark size={16} />} label="Amount at risk"
          value={data ? inr(data.kpis.amount_at_risk) : "—"} sub="Sum over queued chains" />
        <StatTile tone="sunflower" icon={<Timer size={16} />} label="Median access → money"
          value={data ? duration(data.kpis.median_access_to_money_s) : "—"} sub="Staff or login to first payout" />
        <StatTile tone="periwinkle" icon={<UserX size={16} />} label="Unexplained accesses" href="/alibi?verdict=UNEXPLAINED"
          value={data ? <CountUp value={data.kpis.unexplained_accesses} /> : "—"}
          sub={data && <>+{data.kpis.partially_explained.toLocaleString("en-IN")} partial · Alibi coverage <b>{pct(data.kpis.alibi_coverage)}</b></>} />
        <StatTile tone="mint" icon={<Factory size={16} />} label="Mule clusters" href="/mule"
          value={data ? <CountUp value={data.kpis.mule_clusters} /> : "—"} sub="Employee-origin account factories" />
        <StatTile tone="tangerine" icon={<ShieldOff size={16} />} label="Controls bypassed" href="/controls"
          value={data ? <CountUp value={bypassed} /> : "—"}
          sub={data && `${data.kpis.controls_bypassed.expired_entitlements} expired grants · ${data.kpis.controls_bypassed.sod_breaches} SoD · ${data.kpis.controls_bypassed.presence_less_openings} presence-less`} />
      </div>

      {/* money in motion + critical chains */}
      <div className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
        <Panel className="relative overflow-hidden">
          <PanelHead eyebrow="Money in motion" title="Privilege → account → mule → cash-out"
            right={<span className="text-[11.5px] text-muted">Click a flow for its trigger and latency</span>} />
          <div className="relative h-[430px] border-t border-line">
            {topMoney ? (
              <EntityGraph nodes={topMoney.nodes} edges={topMoney.edges} particles asOf={replayAsOf} selectedEdge={edge?.id}
                onEdgeClick={(e) => setEdge(e)} onNodeClick={(n) => n.kind !== "cash" && router.push(`/entities/${n.id}`)} />
            ) : <Skeleton className="m-4 h-[400px]" />}
            <AnimatePresence>{edge && <EdgeCard e={edge} onClose={() => setEdge(null)} />}</AnimatePresence>
          </div>
        </Panel>

        <Panel className="flex flex-col">
          <PanelHead eyebrow="Critical chains" title="Queued for investigators" right={<Link href="/signals" className="text-[12px] text-info hover:underline">Signal Desk →</Link>} />
          <div className="flex-1 space-y-2 px-3 pb-3">
            {data?.alerts.map((a, i) => (
              <motion.button key={a.id} onClick={() => router.push(`/cases/${a.id}`)}
                initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
                className="group w-full rounded-3xl border border-transparent bg-panel-2 px-4 py-3 text-left transition-colors hover:border-line-strong">
                <div className="flex items-center gap-2">
                  <PriorityPill p={a.priority} />
                  <span className="num text-[11px] text-faint">{a.id}</span>
                  <span className="ml-auto num text-[13px] font-semibold text-threat">{inr(a.amount_at_risk)}</span>
                </div>
                <div className="mt-1.5 line-clamp-2 text-[12.5px] leading-snug text-ink">{a.claim}</div>
                <div className="mt-2 flex items-center gap-3">
                  <span className="text-[11px] text-muted">{a.typology_label}{a.latency_s ? ` · ${duration(a.latency_s)}` : ""}</span>
                  <div className="ml-auto flex gap-1">
                    {a.dims.filter((d) => d.level !== "NONE").slice(0, 7).map((d) => (
                      <Tip key={d.key} content={`${d.label}: ${d.level}`}>
                        <span className={cn("h-3.5 w-1.5 rounded-sm", d.level === "HIGH" ? "bg-threat" : d.level === "ELEVATED" ? "bg-amber" : "bg-ok")} />
                      </Tip>
                    ))}
                  </div>
                </div>
              </motion.button>
            ))}
            {isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}
          </div>
        </Panel>
      </div>

      {/* funnel + signals */}
      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Panel>
          <PanelHead eyebrow="Precision" title="From every access to a short queue" />
          <div className="px-4 pb-4">{data?.funnel ? <Funnel f={data.funnel} /> : <Skeleton className="h-40" />}</div>
        </Panel>
        <Panel>
          <PanelHead eyebrow="Signal feed" title="Latest detector signals" right={<span className="text-[11.5px] text-muted">Signals are not alerts — only chains reach the queue</span>} />
          <div className="max-h-[260px] overflow-y-auto px-4 pb-3">
            {data?.signals.map((s) => (
              <div key={s.id} className="flex items-start gap-3 border-b border-line py-2 last:border-0">
                <span className="num w-12 shrink-0 pt-0.5 text-[11px] text-faint">{hhmm(s.t)}</span>
                <Chip tone={s.family === "GRAPH" ? "info" : s.family === "ML" ? "ai" : "amber"}>{s.detector}</Chip>
                <span className="flex-1 text-[12.5px] text-ink-2">{s.summary}</span>
                <LevelBar level={s.strength >= 0.8 ? "HIGH" : s.strength >= 0.5 ? "ELEVATED" : "LOW"} />
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
