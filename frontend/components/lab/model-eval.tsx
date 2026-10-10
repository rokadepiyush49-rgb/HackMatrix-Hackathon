"use client";

import { motion } from "motion/react";
import { Network, Radio, Scale } from "lucide-react";
import { useState } from "react";

import { Chip, ErrorBox, Panel, PanelHead, Skeleton, Tabs, TabsList, TabsTrigger, Tip } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, stamp } from "@/lib/format";
import type { EvalMethod, EvalRow, EvalSet, Interval, ModelEval } from "@/lib/types";

const METHODS: EvalMethod[] = ["RB-1", "RB-2", "M7", "M7-structure"];
const SHORT: Record<EvalMethod, string> = { "RB-1": "RB-1", "RB-2": "RB-2", M7: "M7", "M7-structure": "M7 − det." };
const SET_LABEL: Record<EvalSet["key"], string> = { cv: "Unseen cases (grouped CV)", heldout: "Held-out worlds", later: "Later events" };
const TYPOLOGY: Record<string, string> = {
  INSIDER_ATO: "Insider takeover", MULE_FACTORY: "Mule ring", EXTERNAL_ATO: "External takeover",
  CIRCULAR_FLOW: "Circular flow", STRUCTURING: "Structuring", RELATIONSHIP: "Staff relationship",
};
const LOOKALIKE: Record<string, string> = {
  VIDEO_KYC: "Video-KYC openings", SINGLE_OFFICER: "Single-officer branch", HOUSEHOLD: "Households sharing a phone",
  S2: "Monthly loan loop", S3: "Kirana takings", S4: "Pension camp", S5: "Declared relative", S6: "New phone",
  S7: "College fees", S8: "Salary-day / festival stress",
};
const FAMILY_TONE: Record<string, string> = { graph: "bg-info", sequence: "bg-ai", evidence: "bg-amber" };

const typology = (t: string) => t.split("+").map((x) => TYPOLOGY[x] ?? x).join(" + ");
const f2 = (v: number | null) => (v == null ? "—" : v.toFixed(2));

function Cell({ m, better }: { m: Interval; better?: boolean }) {
  return (
    <Tip content={m.lo == null ? "No interval (no alerts or no positives)" : `95% bootstrap interval over groups: ${f2(m.lo)}–${f2(m.hi)}`}>
      <span className="inline-flex flex-col items-end leading-tight">
        <span className={cn("num text-[13px] font-semibold", better ? "text-ok" : "text-ink")}>{f2(m.value)}</span>
        <span className="num text-[10px] text-faint">{m.lo == null ? " " : `${f2(m.lo)}–${f2(m.hi)}`}</span>
      </span>
    </Tip>
  );
}

function best(rows: EvalRow[], k: "precision" | "recall" | "f1" | "pr_auc", low = false): number | null {
  const v = rows.map((r) => r[k].value).filter((x): x is number => x != null);
  if (!v.length) return null;
  return low ? Math.min(...v) : Math.max(...v);
}

function SetTable({ s }: { s: EvalSet }) {
  const top = { precision: best(s.rows, "precision"), recall: best(s.rows, "recall"), f1: best(s.rows, "f1"), pr_auc: best(s.rows, "pr_auc") };
  const laBest = Math.min(...s.rows.map((r) => r.lookalike_fp_rate.value ?? 1));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
        <span><b className="num text-ink">{s.cases.toLocaleString("en-IN")}</b> connected cases</span>
        <span><b className="num text-threat">{s.positives}</b> suspicious</span>
        <span><b className="num text-ok">{s.lookalikes}</b> legitimate look-alikes</span>
        <span><b className="num text-ink">{s.background}</b> other</span>
        <span className="text-faint">worlds {s.worlds.join(", ")}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-[12px]">
          <thead><tr className="border-b border-line text-left">
            <th className="py-1.5 eyebrow">Method</th><th className="eyebrow text-right">Alerts</th>
            <th className="eyebrow text-right">Precision</th><th className="eyebrow text-right">Recall</th>
            <th className="eyebrow text-right">F1</th><th className="eyebrow text-right">PR-AUC</th>
            <th className="eyebrow text-right">Look-alike FP</th><th className="eyebrow text-right">Per 1k accts</th>
          </tr></thead>
          <tbody>
            {s.rows.map((r) => (
              <tr key={r.method} className={cn("border-b border-line last:border-0", r.method === "M7" && "bg-ai-soft/30")}>
                <td className="py-2 pr-2">
                  <div className="flex items-center gap-2">
                    <Chip tone={r.method.startsWith("M7") ? "ai" : "faint"} mono>{SHORT[r.method]}</Chip>
                    <span className="text-ink-2">{r.label}</span>
                  </div>
                  {r.at_rb1_budget && r.at_rb1_budget.k > 0 && (
                    <div className="mt-1 pl-1 text-[10.5px] text-faint">
                      At RB-1&apos;s budget of {r.at_rb1_budget.k} alerts: catches {r.at_rb1_budget.tp} of {s.positives}
                    </div>
                  )}
                </td>
                <td className="num py-2 text-right text-ink">{r.alerts}</td>
                <td className="py-2 text-right"><Cell m={r.precision} better={r.precision.value === top.precision} /></td>
                <td className="py-2 text-right"><Cell m={r.recall} better={r.recall.value === top.recall} /></td>
                <td className="py-2 text-right"><Cell m={r.f1} better={r.f1.value === top.f1} /></td>
                <td className="py-2 text-right"><Cell m={r.pr_auc} better={r.pr_auc.value === top.pr_auc} /></td>
                <td className="py-2 text-right">
                  <Cell m={r.lookalike_fp_rate} better={r.lookalike_fp_rate.value === laBest} />
                  <div className="num text-[10px] text-faint">{r.lookalike_alerts} of {s.lookalikes}</div>
                </td>
                <td className="num py-2 text-right text-ink-2">{r.alerts_per_1k_accounts.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s.note && <p className="text-[11px] text-faint">{s.note}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="eyebrow mb-2">Recall by typology — where each method still misses</div>
          <table className="w-full text-[11.5px]">
            <thead><tr className="border-b border-line text-left"><th className="py-1 font-medium text-muted">Typology</th>
              {METHODS.map((m) => <th key={m} className="num whitespace-nowrap pl-3 text-right font-medium text-muted">{SHORT[m]}</th>)}</tr></thead>
            <tbody>
              {s.by_typology.map((t) => {
                const top = Math.max(...METHODS.map((m) => t.recall[m]));
                return (
                  <tr key={t.typology} className="border-b border-line last:border-0">
                    <td className="py-1.5 text-ink-2">{typology(t.typology)} <span className="num text-faint">· {t.cases}</span></td>
                    {METHODS.map((m) => (
                      <td key={m} className={cn("num pl-3 text-right", t.recall[m] === top ? "font-semibold text-ink" : "text-faint",
                        t.recall[m] < top && m.startsWith("M7") && "text-threat")}>{Math.round(t.recall[m] * 100)}%</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div>
          <div className="eyebrow mb-2">Legitimate look-alikes alerted</div>
          <table className="w-full text-[11.5px]">
            <thead><tr className="border-b border-line text-left"><th className="py-1 font-medium text-muted">Look-alike</th>
              {METHODS.map((m) => <th key={m} className="num whitespace-nowrap pl-3 text-right font-medium text-muted">{SHORT[m]}</th>)}</tr></thead>
            <tbody>
              {s.lookalikes_by_type.map((t) => (
                <tr key={t.type} className="border-b border-line last:border-0">
                  <td className="py-1.5 text-ink-2">{LOOKALIKE[t.type] ?? t.type} <span className="num text-faint">· {t.cases}</span></td>
                  {METHODS.map((m) => (
                    <td key={m} className={cn("num pl-3 text-right", t.alerted[m] ? "font-semibold text-threat" : "text-faint")}>{t.alerted[m]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function ModelEvalPanel() {
  const { data: ev, error } = useGet<ModelEval>(["model-eval"], "/lab/model-eval", { retry: false });
  const [tab, setTab] = useState<EvalSet["key"]>("heldout");
  if (error) {
    return (
      <Panel><PanelHead eyebrow="FIN-04 · Learned prioritisation" title="M7 against the rule baselines" />
        <div className="px-4 pb-4"><ErrorBox error={error} /></div></Panel>
    );
  }
  if (!ev) return <Skeleton className="h-[360px]" />;
  const set = ev.test_sets.find((s) => s.key === tab) ?? ev.test_sets[0];
  const m7 = ev.models.M7;
  const fams = Object.entries(m7.families).sort((a, b) => b[1] - a[1]);
  return (
    <Panel className="overflow-hidden border-ai/30">
      <PanelHead eyebrow="FIN-04 · Learned prioritisation" title="M7 against the documented rule baselines"
        right={<span className="text-[11px] text-faint">{stamp(ev.generated_at)}</span>} />
      <div className="space-y-5 px-4 pb-4">
        <p className="max-w-[92ch] text-[12.5px] text-muted">
          One connected case is one investigation: chains and signals joined by shared accounts, customers and devices.
          M7 ranks cases from graph, sequence and detector features. It was trained on worlds {ev.train_worlds.join(", ")} with folds
          grouped by ring, and is compared here with RB-1, a written rule set, and RB-2, SUTRA&apos;s own lattice with every model
          switched off. Look-alikes are in every test set. {ev.note}
        </p>

        <Tabs value={tab} onValueChange={(v) => setTab(v as EvalSet["key"])}>
          <TabsList>{ev.test_sets.map((s) => <TabsTrigger key={s.key} value={s.key}>{SET_LABEL[s.key]}</TabsTrigger>)}</TabsList>
        </Tabs>
        <p className="-mt-2 text-[12px] text-ink-2">{set.title}</p>
        <SetTable s={set} />

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="rounded-lg border border-line p-3">
            <div className="flex items-center gap-2"><Network size={14} className="text-ai" />
              <span className="text-[13px] font-semibold text-ink">What M7 leans on</span>
              <span className="num ml-auto text-[10.5px] text-faint">mean |TreeSHAP|, training cases</span></div>
            <div className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-line">
              {fams.map(([k, v]) => <motion.span key={k} className={cn("h-full", FAMILY_TONE[k])} initial={{ width: 0 }} animate={{ width: `${v * 100}%` }} transition={{ duration: 0.6 }} />)}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-3 text-[11px] text-muted">
              {fams.map(([k, v]) => <span key={k} className="inline-flex items-center gap-1.5"><span className={cn("size-2 rounded-full", FAMILY_TONE[k])} />{k} {Math.round(v * 100)}%</span>)}
            </div>
            <div className="mt-3 space-y-1.5">
              {m7.importance.slice(0, 7).map((f) => (
                <div key={f.feature} className="flex items-center gap-2 text-[11.5px]">
                  <span className={cn("size-1.5 shrink-0 rounded-full", FAMILY_TONE[f.family])} />
                  <span className="min-w-0 flex-1 truncate text-ink-2">{f.label}</span>
                  <div className="h-1.5 w-24 overflow-hidden rounded-full bg-line">
                    <span className="block h-full bg-ai" style={{ width: `${Math.min(100, (f.share / m7.importance[0].share) * 100)}%` }} />
                  </div>
                  <span className="num w-9 text-right text-faint">{Math.round(f.share * 100)}%</span>
                </div>
              ))}
            </div>
            <p className="mt-2.5 text-[11px] text-faint">
              Ablation: without detector features M7 keeps graph and sequence only — the &ldquo;M7 − det.&rdquo; row above.
              M7 orders the queue inside each priority band and is shown as a suspicion score. It never sets P1 and never closes a case.
            </p>
          </div>
          <div className="space-y-3">
            <div className="rounded-lg border border-line p-3">
              <div className="flex items-center gap-2"><Scale size={14} className="text-muted" />
                <span className="text-[13px] font-semibold text-ink">RB-1 v{ev.baselines["RB-1"].version} — {ev.baselines["RB-1"].rule}</span></div>
              <ul className="mt-2 space-y-1 text-[11.5px]">
                {ev.baselines["RB-1"].clauses.map((c) => (
                  <li key={c.code} className="flex gap-2"><span className="num shrink-0 text-faint">{c.code}</span>
                    <span className="text-ink-2"><b className="font-medium text-ink">{c.typology}.</b> {c.text}</span></li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-faint">RB-2: {ev.baselines["RB-2"].rule}.</p>
            </div>
            {ev.live_feed.map((c) => (
              <div key={c.case_key} className="rounded-lg border border-info/30 bg-info-soft/30 p-3">
                <div className="flex flex-wrap items-center gap-2"><Radio size={14} className="text-info" />
                  <span className="text-[13px] font-semibold text-ink">22 Sep live feed — a later event joins a case</span>
                  <span className="num ml-auto text-[10.5px] text-faint">{c.case_key}</span></div>
                <p className="mt-1.5 text-[12px] text-ink-2">
                  {typology(c.typology)} · RB-1 {c.rb1.length ? c.rb1.join(" ") : "quiet"} · RB-2 {c.rb2 ?? "—"} ·
                  M7 (trained on the past only) <b className="num">{c.m7_score.toFixed(2)}</b>{c.m7_alert ? " — above threshold" : ""}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {c.top_features.map((f) => (
                    <Tip key={f.label} content={f.refs.join(", ") || "no records"}><Chip tone="info" className="!normal-case">{f.label} {f.contribution > 0 ? "+" : ""}{f.contribution.toFixed(1)}</Chip></Tip>
                  ))}
                </div>
                <p className="mt-1.5 text-[11px] text-faint">{ev.live_feed_note}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}
