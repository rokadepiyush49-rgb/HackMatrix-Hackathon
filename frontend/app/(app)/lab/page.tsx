"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, Cpu, Eraser, FlaskConical, Loader2, RotateCcw, Scale, X } from "lucide-react";

import { AlibiResolution } from "@/components/brief/brief";
import { Funnel } from "@/components/brief/funnel";
import { Button, Chip, CountUp, ErrorBox, LevelBar, PageHeader, Panel, PanelHead, PriorityPill, Skeleton, Tip } from "@/components/ui/primitives";
import { useGet, usePost } from "@/lib/api";
import { cn, pct, stamp } from "@/lib/format";
import type { AlibiCard, FlipResult, LabReport, LabScenario, Registry } from "@/lib/types";

// ── Separation: where each variant landed on the priority lattice ──────────

const STOPS = ["quiet", "EXPLAINED", "WATCH", "P3", "P2", "P1"] as const;
const STOP_LABEL: Record<string, string> = { quiet: "Quiet", EXPLAINED: "Explained", WATCH: "Watch", P3: "P3", P2: "P2", P1: "P1" };

function landed(s: LabScenario): string {
  const pool = s.variant === "suspicious" && s.expected.kind ? s.matched.filter((m) => m.kind === s.expected.kind) : s.matched;
  let best = 0;
  for (const m of pool) best = Math.max(best, STOPS.indexOf(m.priority as (typeof STOPS)[number]));
  return STOPS[best];
}
const pos = (stop: string) => (STOPS.indexOf(stop as (typeof STOPS)[number]) / (STOPS.length - 1)) * 100;

function SeparationBar({ sus, twin }: { sus?: LabScenario; twin?: LabScenario }) {
  const a = sus ? landed(sus) : null;
  const b = twin ? landed(twin) : null;
  return (
    <div className="relative pb-5 pt-6">
      <div className="relative h-2 rounded-full bg-gradient-to-r from-ok/30 via-amber/25 to-threat/40">
        {/* queue threshold: P3 and above reach an investigator */}
        <div className="absolute -top-2 bottom-[-8px] border-l border-dashed border-ink/40" style={{ left: `${(pos("WATCH") + pos("P3")) / 2}%` }}>
          <span className="absolute -top-4 left-1 whitespace-nowrap text-[9.5px] uppercase tracking-wider text-faint">queue →</span>
        </div>
        {b && (
          <motion.div initial={{ left: "0%" }} animate={{ left: `${pos(b)}%` }} transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2">
            <Tip content={`Twin → ${STOP_LABEL[b]}`}><span className="block size-4 rounded-full border-2 border-bg bg-ok shadow" /></Tip>
          </motion.div>
        )}
        {a && (
          <motion.div initial={{ left: "0%" }} animate={{ left: `${pos(a)}%` }} transition={{ duration: 1.1, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2">
            <Tip content={`Suspicious → ${STOP_LABEL[a]}`}><span className="block size-4 rounded-full border-2 border-bg bg-threat shadow" /></Tip>
          </motion.div>
        )}
      </div>
      <div className="absolute inset-x-0 bottom-0 flex justify-between text-[9.5px] uppercase tracking-wider text-faint">
        {STOPS.map((s) => <span key={s} className={cn((s === a || s === b) && "text-ink-2")}>{STOP_LABEL[s]}</span>)}
      </div>
    </div>
  );
}

function VariantCard({ s }: { s: LabScenario }) {
  const sus = s.variant === "suspicious";
  return (
    <div className={cn("rounded-lg border p-3", sus ? "border-threat/25 bg-threat-soft/25" : "border-ok/25 bg-ok-soft/25")}>
      <div className="flex items-center gap-2">
        <Chip tone={sus ? "threat" : "ok"}>{sus ? "suspicious" : "legit twin"}</Chip>
        {s.passed ? <Chip tone="ok"><Check size={10} /> pass</Chip> : <Chip tone="threat"><X size={10} /> fail</Chip>}
      </div>
      <p className="mt-2 text-[12.5px] leading-snug text-ink">{s.description}</p>
      <p className={cn("mt-2 text-[12px] font-medium", sus ? "text-threat" : "text-ok")}>{s.outcome}</p>
    </div>
  );
}

function PairCard({ id, list, i }: { id: string; list: LabScenario[]; i: number }) {
  const sus = list.find((x) => x.variant === "suspicious");
  const twin = list.find((x) => x.variant === "twin");
  const head = sus ?? twin!;
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
      <Panel className="h-full p-4">
        <div className="flex items-center gap-2">
          <span className="num rounded bg-panel-2 px-1.5 py-0.5 text-[11px] text-muted">{id}</span>
          <span className="display text-[15px] font-semibold text-ink">{head.title}</span>
        </div>
        {twin?.differing_fact && sus && (
          <div className="mt-2 rounded-md border border-info/25 bg-info-soft/40 px-2.5 py-1.5 text-[12px] text-ink-2">
            <span className="mr-1 font-semibold text-info">The one fact that differs:</span>{twin.differing_fact}
          </div>
        )}
        <SeparationBar sus={sus} twin={twin} />
        <div className={cn("grid gap-2", sus && twin ? "sm:grid-cols-2" : "grid-cols-1")}>
          {sus && <VariantCard s={sus} />}
          {twin && <VariantCard s={twin} />}
        </div>
      </Panel>
    </motion.div>
  );
}

// ── Flip: delete the twin's alibi and re-run ────────────────────────────────

function toCard(x: FlipResult["before"][number]): AlibiCard {
  const ok = x.checked.filter((c) => c.ok);
  return {
    verdict: x.verdict as AlibiCard["verdict"],
    purpose_ok: ok.some((c) => c.template !== "ROSTER"),
    timing_ok: !!x.checked.find((c) => c.template === "ROSTER")?.ok,
    reasons_found: ok.length,
    checked: x.checked,
  };
}

function FlipPanel() {
  const flip = usePost<{ key: string }, FlipResult>("/lab/flip");
  const r = flip.data;
  return (
    <Panel className="overflow-hidden border-ai/30">
      <PanelHead eyebrow="Counterfactual · S4 twin" title="Delete the alibi. Does SUTRA change its mind?"
        right={r ? <Button size="sm" variant="ghost" onClick={() => flip.reset()}><RotateCcw size={13} /> Reset</Button> : undefined} />
      <div className="px-4 pb-4">
        <p className="text-[12.5px] text-muted">
          The pension-camp twin stays quiet because a ticket, a biometric eKYC and a camp roster explain the 21:40 mobile change.
          Remove those three records in memory and re-run Alibi → Needle → Brief on the same access. Nothing is written to the database.
        </p>
        {!r && (
          <Button variant="ai" className="mt-3" disabled={flip.isPending} onClick={() => flip.mutate({ key: "S4-twin" })}>
            {flip.isPending ? <><Loader2 size={14} className="animate-spin" /> Re-running the pipeline…</> : <><Eraser size={14} /> Remove the explaining records</>}
          </Button>
        )}
        {flip.error && <div className="mt-3"><ErrorBox error={flip.error} /></div>}
        <AnimatePresence>
          {r && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-4 space-y-4">
              <div>
                <div className="eyebrow mb-2">Records removed</div>
                <div className="space-y-1.5">
                  {r.removed.map((x, i) => (
                    <motion.div key={x.id} initial={{ opacity: 1 }} animate={{ opacity: 0.55 }} transition={{ delay: 0.3 + i * 0.25 }}
                      className="relative flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-[12px]">
                      <Chip tone="faint">{x.kind}</Chip><span className="num whitespace-nowrap text-muted">{x.ref}</span><span className="truncate text-ink-2">{x.text}</span>
                      <motion.span initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ delay: 0.3 + i * 0.25, duration: 0.35 }}
                        className="absolute inset-x-2 top-1/2 h-px origin-left bg-threat" />
                    </motion.div>
                  ))}
                </div>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {r.before[0] && <AlibiResolution card={toCard(r.before[0])} title="Before — with the records" replayKey="before" />}
                {r.after[0] && <AlibiResolution card={toCard(r.after[0])} title="After — records removed" replayKey="after" />}
              </div>
              {r.alert ? (
                <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 2.2 }}
                  className="rounded-lg border border-line-strong bg-panel-2 p-3.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="eyebrow">Needle now builds a chain</span><ArrowRight size={12} className="text-faint" /><PriorityPill p={r.alert.priority} />
                  </div>
                  <p className="mt-1.5 text-[13px] font-semibold text-ink">{r.alert.claim}</p>
                  <p className="mt-1 text-[12px] text-ink-2"><Scale size={12} className="mr-1 inline text-faint" />{r.alert.lattice_rule}</p>
                  <div className="mt-3 grid gap-x-4 gap-y-1.5 2xl:grid-cols-2">
                    {r.alert.dims.map((d) => (
                      <div key={d.key} className="flex items-center gap-2 text-[11.5px]">
                        <span className="w-[112px] shrink-0 text-muted">{d.label}</span><LevelBar level={d.level} /><span className="truncate text-faint">{d.summary}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 rounded-md bg-ai-soft px-2.5 py-1.5 text-[12px] text-ai">
                    Proportionate, not paranoid: without its alibi the access becomes a chain, but the money side is small and slow,
                    so the lattice keeps it on the watch-list instead of paging an investigator.
                  </p>
                </motion.div>
              ) : <p className="text-[12px] text-muted">No chain formed even without the records.</p>}
              <p className="text-[11px] text-faint">{r.note}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Panel>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

const METRIC_LABEL: Record<string, string> = {
  roc_auc_oof: "ROC-AUC (OOF)", pr_auc_oof: "PR-AUC (OOF)", brier_oof: "Brier (OOF)", precision_at_k: "Precision@k",
};

export default function TwinLab() {
  const { data: rep, error } = useGet<LabReport>(["lab"], "/lab/report");
  const { data: reg } = useGet<Registry>(["registry"], "/governance/registry");

  const pairs = new Map<string, LabScenario[]>();
  rep?.scenarios.forEach((s) => pairs.set(s.scenario, [...(pairs.get(s.scenario) ?? []), s]));
  const detName = new Map(reg?.detectors.map((d) => [d.code, d]) ?? []);

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader eyebrow="Prevent · Twin Scenario Lab" title="Catch the fraud. Stay quiet on its twin."
        sub="Every suspicious scenario has a legitimate twin that differs by one fact. A detector that fires on both is noise; SUTRA must separate them — and show its working."
        right={rep && <span className="text-[11.5px] text-faint">{rep.run_id} · {stamp(rep.run_at)}</span>} />
      {error && <ErrorBox error={error} />}
      {!rep && !error && <Skeleton className="h-[420px]" />}

      {rep && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {[
              { k: "Scenario checks passed", v: rep.summary.passed, of: rep.summary.total, tone: "text-ink", icon: FlaskConical },
              { k: "Suspicious scenarios caught", v: rep.summary.suspicious_caught, of: rep.summary.suspicious_total, tone: "text-threat", icon: Check },
              { k: "Legitimate twins kept quiet", v: rep.summary.twins_quiet, of: rep.summary.twins_total, tone: "text-ok", icon: Scale },
            ].map((x, i) => (
              <motion.div key={x.k} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }}>
                <Panel className="flex items-center gap-4 p-4">
                  <span className="grid size-11 place-items-center rounded-full bg-panel-2 text-muted"><x.icon size={20} /></span>
                  <div>
                    <div className="text-[12px] text-muted">{x.k}</div>
                    <div className={cn("display text-[30px] font-extrabold leading-none", x.tone)}>
                      <CountUp value={x.v} /><span className="text-[18px] text-faint"> / {x.of}</span>
                    </div>
                  </div>
                </Panel>
              </motion.div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            {[...pairs.entries()].map(([id, list], i) => <PairCard key={id} id={id} list={list} i={i} />)}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <FlipPanel />
            <Panel>
              <PanelHead eyebrow="Precision story" title="From every staff access to five argued alerts" />
              <div className="px-4 pb-4"><Funnel f={rep.funnel} /></div>
            </Panel>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <Panel>
              <PanelHead eyebrow="Detectors" title="Where each detector fired" />
              <div className="overflow-x-auto px-4 pb-4">
                <table className="w-full min-w-[560px] text-[12px]">
                  <thead><tr className="border-b border-line text-left">
                    <th className="py-1.5 eyebrow">Code</th><th className="eyebrow">Detector</th><th className="eyebrow text-right">Signals</th>
                    <th className="eyebrow pl-4">On scenario entities vs. elsewhere</th>
                  </tr></thead>
                  <tbody>
                    {rep.detectors.slice().sort((a, b) => a.code.localeCompare(b.code, "en", { numeric: true })).map((d) => {
                      const meta = detName.get(d.code);
                      const share = d.signals ? d.on_scenario_entities / d.signals : 0;
                      return (
                        <tr key={d.code} className="border-b border-line last:border-0">
                          <td className="num py-2 text-muted">{d.code}</td>
                          <td className="py-2 pr-2">
                            <Tip content={meta?.logic ?? ""}><span className="text-ink">{meta?.name ?? d.code}</span></Tip>
                            {meta && <span className="ml-1.5 text-[10.5px] text-faint">{meta.family.toLowerCase()}</span>}
                          </td>
                          <td className="num py-2 text-right text-ink">{d.signals}</td>
                          <td className="py-2 pl-4">
                            <div className="flex items-center gap-2">
                              <div className="flex h-1.5 w-32 overflow-hidden rounded-full bg-line">
                                <motion.span className="h-full bg-threat" initial={{ width: 0 }} animate={{ width: `${share * 100}%` }} transition={{ duration: 0.6 }} />
                              </div>
                              <span className="num text-[11px] text-muted">{d.on_scenario_entities} / {d.elsewhere}</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="mt-2 text-[11px] text-faint">A signal is not an alert. Detectors that fire mostly elsewhere (e.g. salary-day fan-out) are exactly why SUTRA argues chains instead of queueing hits.</p>
              </div>
            </Panel>

            <Panel>
              <PanelHead eyebrow="Model cards" title="Glass-box models, trained on an independent world" />
              <div className="space-y-3 px-4 pb-4">
                {Object.entries(rep.models).map(([name, m]) => (
                  <div key={name} className="rounded-lg border border-line p-3">
                    <div className="flex items-center gap-2">
                      <Cpu size={14} className="text-ai" />
                      <span className="text-[13px] font-semibold text-ink">{name === "chain_classifier" ? "M5 · Chain classifier (logistic + Platt)" : "M6 · Mule-likeness (LightGBM + TreeSHAP)"}</span>
                      <span className="num ml-auto text-[10.5px] text-faint">v{m.version} · seed {m.train_seed} · n={m.n_train.toLocaleString("en-IN")}</span>
                    </div>
                    <div className="mt-2.5 grid grid-cols-3 gap-2">
                      {Object.entries(m.metrics).filter(([k]) => METRIC_LABEL[k]).map(([k, v]) => (
                        <div key={k} className="rounded-md bg-panel-2 px-2 py-1.5">
                          <div className="text-[10.5px] text-faint">{METRIC_LABEL[k]}</div>
                          <div className="num text-[15px] font-semibold text-ink">{typeof v === "number" ? v.toFixed(3) : v}</div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">{m.features.map((f) => <Chip key={f} tone="faint" className="!normal-case">{f}</Chip>)}</div>
                    <p className="mt-2 text-[11px] text-faint">{String(m.metrics.note ?? "")}</p>
                  </div>
                ))}
                <p className="text-[11px] text-faint">{rep.note} Positive rate in training: {pct(Number(rep.models.chain_classifier?.metrics.positives ?? 0) / Math.max(1, rep.models.chain_classifier?.n_train ?? 1))}.</p>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
