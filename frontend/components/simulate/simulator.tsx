"use client";

// The Fraud Simulator: pick a fraud, tune it, commit it one action at a time in Kestrel Bank (the mock
// bank), then hand the bank's records to SUTRA. Detection, signals, alerts and cases are SUTRA's own:
// this screen only drives the bank's API, starts the same detection run Live Ops does, and opens a
// case through the case API, exactly as an analyst would from the Signal Desk.
//
// Progress lives in sessionStorage, so presenters can leave for the case file and come back.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import {
  Activity, ArrowLeft, ArrowRight, BriefcaseBusiness, Check, CheckCircle2, Circle, CircleAlert, Clock3, Eye, FastForward,
  FileQuestion, FlaskConical, Gavel, History, Landmark, Loader2, Play, ReceiptText, RotateCcw, Route, Scale, ShieldCheck,
  Siren, Square, Wallet, XCircle, type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { TypologyChip } from "@/components/chain/alert-bits";
import { useLiveRun } from "@/components/live/use-live-run";
import { Button, ButtonLink, Chip, CountUp, ErrorBox, PageHeader, Panel, PanelHead, PriorityPill, Skeleton, type Tone } from "@/components/ui/primitives";
import { api, ApiError, useGet } from "@/lib/api";
import { cn, dayMonth, duration, hhmm, inr } from "@/lib/format";
import { useMounted } from "@/lib/hooks";
import type { LiveAlert, LiveAlibi, LiveResult, LiveSignal, LiveStatus, LiveVerdict } from "@/lib/types";

import {
  account, activity, ACTOR, bankCall, checkParams, moneyOut, playbook, PLAYBOOKS,
  type Account, type BankRecord, type Ctx, type Expect, type Field, type Params, type Playbook,
} from "./playbooks";

// ── state ───────────────────────────────────────────────────────────────────

type Stage = "choose" | "brief" | "perform" | "judge";
interface StepResult { note: string; rows: BankRecord[] }
interface Snapshot { verdict: LiveVerdict | null; alerts: LiveAlert[]; detectors: string[]; elapsed: number }
interface Sim {
  key: string | null;
  params: Params;
  stage: Stage;
  results: StepResult[];
  staff: string | null;
  customer: string | null;
  bag: Record<string, unknown>;
  autoCase: boolean;
  runId: string | null;
  /** What the detection run concluded, kept in case the run itself is no longer on the server. */
  outcome: Snapshot | null;
  cases: Record<string, { caseId?: string; error?: string }>;
  visited: string[];
}

const EMPTY: Sim = {
  key: null, params: {}, stage: "choose", results: [], staff: null, customer: null, bag: {}, autoCase: true,
  runId: null, outcome: null, cases: {}, visited: [],
};
const STORE = "sutra-fraud-sim";
const QUEUED = ["P1", "P2", "P3"];

function load(): Sim {
  try {
    const raw = sessionStorage.getItem(STORE);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const lakh = (v: number) => (v >= 1e5 ? `₹${(v / 1e5).toFixed(2)} L` : inr(v));

export function FraudSimulator() {
  // sessionStorage only exists in the browser: render the simulator after hydration.
  return useMounted() ? <Simulator /> : <Skeleton className="h-[620px]" />;
}

function Simulator() {
  const qc = useQueryClient();
  const [sim, setSim] = useState<Sim>(load);
  const [busyStep, setBusyStep] = useState<number | null>(null);
  const [stepError, setStepError] = useState<{ i: number; message: string } | null>(null);
  const [auto, setAuto] = useState(false);
  const stopAuto = useRef(false);
  const found = useRef<LiveAlert[]>([]); // new alerts the current detection run has reported
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetRun, setResetRun] = useState<string | null>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(sim));
    } catch {
      /* storage unavailable: progress simply is not kept across pages */
    }
  }, [sim]);

  const pb = playbook(sim.key);
  const steps = useMemo(() => (pb ? pb.steps(sim.params) : []), [pb, sim.params]);
  const status = useGet<LiveStatus>(["live-status"], "/live/status", { refetchInterval: (q) => (q.state.data?.busy ? 2000 : false) });

  const { state: run, attach: attachRun } = useLiveRun({
    onAlert: (a) => {
      if (a.new) found.current = [...found.current.filter((x) => x.id !== a.id), a];
    },
    onDone: (r, kind) => {
      status.refetch();
      if (kind === "reset") {
        setSim(() => EMPTY);
        setResetRun(null);
        qc.invalidateQueries();
        return;
      }
      void conclude(r);
    },
  });
  const attach = (runId: string) => {
    found.current = [];
    attachRun(runId);
  };

  // Coming back to the page mid-run, or after it: replay the run from the server to show it again.
  useEffect(() => {
    if (sim.runId && sim.stage === "judge") attach(sim.runId);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- once, on arrival

  /** The detection run finished: keep what it found and open a case on every queued alert it raised. */
  async function conclude(r: LiveResult) {
    if (sim.outcome) return; // the replay of a run concluded earlier
    const fresh = found.current;
    setSim((s) => ({ ...s, outcome: { verdict: r.verdict ?? null, alerts: fresh, detectors: r.detectors ?? [], elapsed: r.elapsed } }));
    if (!sim.autoCase) return;
    for (const a of fresh.filter((x) => QUEUED.includes(x.priority))) {
      try {
        const c = await api<{ id: string }>("/cases", { method: "POST", body: JSON.stringify({ alert_id: a.id }) });
        setSim((s) => ({ ...s, cases: { ...s.cases, [a.id]: { caseId: c.id } } }));
      } catch (e) {
        setSim((s) => ({ ...s, cases: { ...s.cases, [a.id]: { error: e instanceof ApiError ? e.message : "Could not open the case." } } }));
      }
    }
    qc.invalidateQueries({ queryKey: ["cases"] });
    qc.invalidateQueries({ queryKey: ["alerts"] });
  }

  // ── actions ──

  const choose = (p: Playbook) => setSim((s) => ({ ...EMPTY, autoCase: s.autoCase, key: p.key, params: p.defaults, stage: "brief" }));

  /** Do one step in the bank. Returns the context for the next step, or null if the bank refused. */
  async function perform(i: number, ctx: Ctx): Promise<Ctx | null> {
    setBusyStep(i);
    setStepError(null);
    try {
      const before = (await activity())[0]?.seq ?? 0;
      const out = await steps[i].run(ctx);
      const rows = (await activity()).filter((r) => r.seq > before).reverse();
      const next: Ctx = { p: ctx.p, staff: out.staff ?? ctx.staff, customer: out.customer ?? ctx.customer, bag: { ...ctx.bag, ...out.bag } };
      setSim((s) => ({ ...s, results: [...s.results, { note: out.note, rows }], staff: next.staff, customer: next.customer, bag: next.bag }));
      qc.invalidateQueries({ queryKey: ["sim-account"] });
      return next;
    } catch (e) {
      setStepError({ i, message: e instanceof Error ? e.message : "The bank refused." });
      return null;
    } finally {
      setBusyStep(null);
    }
  }

  const ctxOf = (s: Sim): Ctx => ({ p: s.params, staff: s.staff, customer: s.customer, bag: s.bag });

  async function playRest() {
    stopAuto.current = false;
    setAuto(true);
    let ctx: Ctx | null = ctxOf(sim);
    for (let i = sim.results.length; i < steps.length && ctx && !stopAuto.current; i++) {
      ctx = await perform(i, ctx);
      if (ctx && i < steps.length - 1) await sleep(900);
    }
    setAuto(false);
  }

  async function detect() {
    setActionError(null);
    try {
      const r = await api<{ run_id: string }>("/live/detect", { method: "POST", body: "{}" });
      setSim((s) => ({ ...s, stage: "judge", runId: r.run_id, outcome: null, cases: {}, visited: [] }));
      attach(r.run_id);
      status.refetch();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Could not reach SUTRA.");
    }
  }

  async function resetAll() {
    setConfirmReset(false);
    setActionError(null);
    try {
      await bankCall("clock", { body: { at: "20:45" } });
      if (!(status.data?.bank.total ?? 0)) {
        setSim(() => EMPTY);
        return;
      }
      const r = await api<{ run_id: string }>("/live/reset?scope=bank", { method: "POST", body: "{}" });
      setResetRun(r.run_id);
      attach(r.run_id);
      status.refetch();
    } catch (e) {
      setActionError(e instanceof ApiError || e instanceof Error ? e.message : "Could not reset.");
    }
  }

  const busy = !!status.data?.busy || !!resetRun || ["connecting", "streaming", "detecting"].includes(run.phase);
  const resetting = !!resetRun && run.runId === resetRun && run.phase !== "done";
  const bankRows = status.data?.bank.total ?? 0;

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader
        eyebrow="Simulate · play the fraudster, then investigate it"
        title={<>Fraud <span className="text-threat">Simulator</span></>}
        sub="Choose a fraud and commit it one action at a time in Kestrel Bank, the test bank. Every click is recorded by the bank system that handles it, exactly as a real bank's feeds would deliver it. Then hand the records to SUTRA: the same detection run, the same Signal Desk, the same Case Desk."
        right={<>
          <ButtonLink size="sm" variant="ghost" href="/bank"><Landmark size={13} /> Kestrel Bank</ButtonLink>
          {confirmReset ? (
            <>
              <Button size="sm" variant="danger" disabled={busy} onClick={resetAll}><RotateCcw size={13} /> Undo all bank activity &amp; re-detect</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmReset(false)}>Keep</Button>
            </>
          ) : (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirmReset(true)}
              title="Removes everything done in Kestrel Bank, restores the accounts and re-runs detection">
              <RotateCcw size={13} /> Reset simulation
            </Button>
          )}
        </>}
      />

      <Stepper stage={sim.stage} pb={pb} onJump={(st) => setSim((s) => ({ ...s, stage: st }))} canBack={sim.stage === "brief"} />

      {status.error && <ErrorBox error={status.error} />}
      {actionError && <div className="mb-4 rounded-lg border border-threat/30 bg-threat-soft px-4 py-2.5 text-[13px] text-threat">{actionError}</div>}
      {resetting && (
        <Panel className="mb-4 flex items-center gap-3 p-4">
          <Loader2 size={16} className="animate-spin text-ai" />
          <div className="text-[13px]">
            <b className="font-semibold text-ink">Undoing everything done in Kestrel Bank</b>
            <span className="text-muted"> · {Object.values(run.progress).filter((p) => p.status === "done").length} of {run.stages.length || 10} stages · accounts restored, detection re-run on the history</span>
          </div>
        </Panel>
      )}

      {/* No exit animation to wait for: the next stage mounts at once, even in a background tab. */}
      <motion.div key={sim.stage + (sim.key ?? "")} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}>
        {sim.stage === "choose" && <ChooseStage onPick={choose} bankRows={bankRows} />}
        {sim.stage === "brief" && pb && (
          <BriefStage pb={pb} params={sim.params} bankRows={bankRows} busy={busy}
            autoCase={sim.autoCase} onAutoCase={(v) => setSim((s) => ({ ...s, autoCase: v }))}
            onChange={(params) => setSim((s) => ({ ...s, params }))}
            onBack={() => setSim((s) => ({ ...s, stage: "choose" }))}
            onBegin={() => setSim((s) => ({ ...s, stage: "perform" }))} />
        )}
        {sim.stage === "perform" && pb && (
          <PerformStage pb={pb} sim={sim} steps={steps} busyStep={busyStep} error={stepError} auto={auto} busy={busy}
            onStep={(i) => void perform(i, ctxOf(sim))} onPlay={() => void playRest()} onStop={() => { stopAuto.current = true; }}
            onDetect={() => void detect()} />
        )}
        {sim.stage === "judge" && pb && (
          <JudgeStage pb={pb} sim={sim} run={run} onVisit={(href) => setSim((s) => ({ ...s, visited: [...new Set([...s.visited, href])] }))}
            onAgain={() => setSim((s) => ({ ...EMPTY, autoCase: s.autoCase }))} onReset={() => setConfirmReset(true)} />
        )}
      </motion.div>
    </div>
  );
}

// ── stepper ─────────────────────────────────────────────────────────────────

const STAGES: { key: Stage; label: string; icon: LucideIcon }[] = [
  { key: "choose", label: "Choose a fraud", icon: Siren },
  { key: "brief", label: "Brief & tune", icon: FileQuestion },
  { key: "perform", label: "Commit it in the bank", icon: Play },
  { key: "judge", label: "SUTRA investigates", icon: ShieldCheck },
];

function Stepper({ stage, pb, onJump, canBack }: { stage: Stage; pb: Playbook | null; onJump: (s: Stage) => void; canBack: boolean }) {
  const at = STAGES.findIndex((s) => s.key === stage);
  return (
    <ol className="mb-5 grid grid-cols-2 gap-2 md:grid-cols-4">
      {STAGES.map((s, i) => {
        const Icon = s.icon;
        const state = i < at ? "done" : i === at ? "now" : "next";
        const clickable = canBack && s.key === "choose";
        return (
          <li key={s.key}>
            <button disabled={!clickable} onClick={() => onJump(s.key)}
              className={cn("flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors",
                state === "now" ? "border-ink bg-panel shadow-xs" : state === "done" ? "border-line bg-panel" : "border-dashed border-line bg-panel/50",
                clickable && "hover:border-ink")}>
              <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg",
                state === "now" ? "bg-primary text-on-primary" : state === "done" ? "bg-ok-soft text-ok" : "bg-panel-2 text-faint")}>
                {state === "done" ? <Check size={15} /> : <Icon size={15} />}
              </span>
              <span className="min-w-0">
                <span className="eyebrow block">Step {i + 1}</span>
                <span className={cn("block truncate text-[13px] font-semibold", state === "next" ? "text-muted" : "text-ink")}>
                  {i === 0 && pb && at > 0 ? pb.title : s.label}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// ── 1. choose ───────────────────────────────────────────────────────────────

function ChooseStage({ onPick, bankRows }: { onPick: (p: Playbook) => void; bankRows: number }) {
  return (
    <div className="flex flex-col gap-4">
      {bankRows > 0 && <LeftoverNotice rows={bankRows} />}
      <div className="grid gap-4 md:grid-cols-2">
        {PLAYBOOKS.map((p, i) => {
          const Icon = p.icon;
          return (
            <motion.button key={p.key} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
              whileHover={{ y: -3 }} onClick={() => onPick(p)}
              className={cn("panel group flex flex-col gap-3 p-5 text-left transition-colors hover:border-line-strong",
                p.kind === "twin" && "border-dashed")}>
              <div className="flex items-center gap-3">
                <span className={cn("grid size-11 place-items-center rounded-2xl", p.kind === "twin" ? "bg-ok-soft text-ok" : "bg-threat-soft text-threat")}>
                  <Icon size={20} />
                </span>
                <div className="min-w-0">
                  <Chip tone={p.kind === "twin" ? "ok" : "threat"}>{p.kind === "twin" ? "Legitimate twin · no fraud" : "Fraud"}</Chip>
                  <div className="display mt-1 text-[18px] font-semibold text-ink">{p.title}</div>
                </div>
                <ArrowRight size={18} className="ml-auto shrink-0 text-faint transition-transform group-hover:translate-x-1 group-hover:text-ink" />
              </div>
              <p className="text-[13.5px] leading-relaxed text-ink-2">{p.tagline}</p>
              <div className="rounded-lg bg-panel-2 px-3 py-2 text-[12px] leading-relaxed text-muted">
                <span className="font-semibold text-ink">SUTRA should conclude: </span>{p.expectText}
              </div>
              <div className="text-[11.5px] text-faint">{p.steps(p.defaults).length} actions · {[...new Set(p.steps(p.defaults).map((s) => s.system))].length} bank systems</div>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

function LeftoverNotice({ rows }: { rows: number }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-amber/30 bg-amber-soft/50 px-4 py-2.5 text-[12.5px] text-ink-2">
      <CircleAlert size={15} className="mt-0.5 shrink-0 text-amber" />
      <span>Kestrel Bank already holds <b>{rows}</b> record{rows === 1 ? "" : "s"} from earlier activity. SUTRA judges them together with yours.
        For a clean demo, press <b>Reset simulation</b> first. Running the same fraud on the same account twice will be refused by the bank.</span>
    </div>
  );
}

// ── 2. brief & tune ─────────────────────────────────────────────────────────

interface Dormant { id: string; full_name: string; account_id: string; status: string; balance: number }

function BriefStage({ pb, params, bankRows, busy, autoCase, onAutoCase, onChange, onBack, onBegin }: {
  pb: Playbook; params: Params; bankRows: number; busy: boolean; autoCase: boolean; onAutoCase: (v: boolean) => void;
  onChange: (p: Params) => void; onBack: () => void; onBegin: () => void;
}) {
  const victimId = pb.victim(params);
  const victim = useQuery<Account>({ queryKey: ["sim-account", victimId], queryFn: () => account(victimId) });
  const errors = checkParams(pb, params, victim.data);
  const out = moneyOut(pb, params);
  const steps = pb.steps(params);
  const Icon = pb.icon;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] xl:items-start">
      <Panel className="p-5">
        <div className="flex items-center gap-3">
          <span className={cn("grid size-11 place-items-center rounded-2xl", pb.kind === "twin" ? "bg-ok-soft text-ok" : "bg-threat-soft text-threat")}><Icon size={20} /></span>
          <div>
            <div className="eyebrow">{pb.kind === "twin" ? "The control case" : "Your mission"}</div>
            <div className="display text-[20px] font-semibold text-ink">{pb.title}</div>
          </div>
        </div>
        <p className="mt-3 max-w-[75ch] text-[14px] leading-relaxed text-ink-2">{pb.brief}</p>

        <div className="eyebrow mt-5 mb-2">Tune the fraud</div>
        <div className="grid gap-3 sm:grid-cols-2">
          {pb.fields.map((f) => <FieldInput key={f.key} f={f} value={params[f.key]} onChange={(v) => onChange({ ...params, [f.key]: v })} />)}
        </div>

        <div className="eyebrow mt-5 mb-2">The plan · {steps.length} actions</div>
        <ol className="grid gap-1.5 sm:grid-cols-2">
          {steps.map((s, i) => (
            <li key={s.key} className="flex items-start gap-2 text-[12.5px]">
              <span className="num mt-px grid size-5 shrink-0 place-items-center rounded-full bg-panel-2 text-[10.5px] text-muted">{i + 1}</span>
              <span><Chip tone={ACTOR[s.actor].tone} className="mr-1 !py-0 !text-[10.5px]">{ACTOR[s.actor].label}</Chip><span className="text-ink-2">{s.title}</span></span>
            </li>
          ))}
        </ol>
      </Panel>

      <div className="flex flex-col gap-4 xl:sticky xl:top-[76px]">
        <AccountCard title="Target account" q={victim} />
        <Panel className="p-5">
          {out > 0 && (
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <span className="text-[12.5px] text-muted">Money that will leave the account</span>
              <span className="num text-[20px] font-semibold text-threat">{lakh(out)}</span>
            </div>
          )}
          <div className="rounded-lg bg-panel-2 px-3 py-2.5 text-[12.5px] leading-relaxed text-ink-2">
            <div className="eyebrow mb-0.5">SUTRA should conclude</div>{pb.expectText}
          </div>
          <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-[12.5px] text-ink-2">
            <input type="checkbox" checked={autoCase} onChange={(e) => onAutoCase(e.target.checked)} className="mt-0.5 size-4 accent-[var(--color-primary)]" />
            <span><b className="font-semibold text-ink">Open a case automatically</b> on every alert SUTRA queues, as the duty analyst would from the Signal Desk.</span>
          </label>
          {bankRows > 0 && <div className="mt-3"><LeftoverNotice rows={bankRows} /></div>}
          {errors.length > 0 && (
            <ul className="mt-3 space-y-1 text-[12px] text-threat">{errors.map((e) => <li key={e} className="flex gap-1.5"><XCircle size={13} className="mt-0.5 shrink-0" />{e}</li>)}</ul>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="ghost" onClick={onBack}><ArrowLeft size={14} /> Another fraud</Button>
            <Button variant="primary" className="ml-auto" disabled={busy || errors.length > 0 || !victim.data} onClick={onBegin}>
              Begin <ArrowRight size={14} />
            </Button>
          </div>
        </Panel>
      </div>
    </div>
  );
}

const inputClass = "h-9 w-full rounded-lg border border-line bg-panel px-3 text-[13px] text-ink outline-none focus:border-info";

function FieldInput({ f, value, onChange }: { f: Field; value: Params[string]; onChange: (v: Params[string]) => void }) {
  const dormant = useQuery<Dormant[]>({
    queryKey: ["sim-dormant"], enabled: f.kind === "victim",
    queryFn: async () => (await bankCall<Dormant[]>("customers")).filter((c) => c.status === "INOPERATIVE"),
  });
  const id = `sim-${f.key}`;
  let input: ReactNode;
  if (f.kind === "multi") {
    const chosen = Array.isArray(value) ? value : [];
    input = (
      <div className="flex flex-wrap gap-1.5">
        {f.options!.map((o) => {
          const on = chosen.includes(o.v);
          return (
            <button key={o.v} type="button" aria-pressed={on} onClick={() => onChange(on ? chosen.filter((x) => x !== o.v) : [...chosen, o.v])}
              className={cn("rounded-full border px-3 py-1 text-[12px] font-medium", on ? "border-ink bg-ink text-bg" : "border-line text-muted hover:text-ink")}>
              {o.label}
            </button>
          );
        })}
      </div>
    );
  } else if (f.kind === "select" || f.kind === "victim") {
    const options = f.kind === "victim"
      ? (dormant.data ?? []).map((d) => ({ v: d.account_id, label: `${d.account_id} · ${d.full_name} · ${lakh(d.balance)}` }))
      : f.options!;
    if (f.kind === "victim" && !options.some((o) => o.v === value)) options.unshift({ v: String(value), label: String(value) });
    input = (
      <select id={id} value={String(value)} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        {options.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
      </select>
    );
  } else {
    input = (
      <input id={id} type={f.kind === "text" ? "text" : f.kind} value={String(value ?? "")} min={f.min} max={f.max} step={f.step}
        inputMode={f.kind === "text" ? "numeric" : undefined}
        onChange={(e) => onChange(f.kind === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
        className={cn(inputClass, "num")} />
    );
  }
  return (
    <div className={cn(f.kind === "multi" || f.kind === "victim" ? "sm:col-span-2" : "")}>
      <label htmlFor={id} className="mb-1 block text-[12px] font-medium text-ink-2">{f.label}</label>
      {input}
      {f.help && <p className="mt-1 text-[11px] text-faint">{f.help}</p>}
    </div>
  );
}

function AccountCard({ title, q }: { title: string; q: { data?: Account; error: unknown; isLoading: boolean } }) {
  const a = q.data;
  return (
    <Panel className="p-5">
      <div className="flex items-center gap-2">
        <Wallet size={15} className="text-muted" />
        <span className="eyebrow">{title} · Kestrel Bank</span>
        {a && <Chip tone={a.status === "ACTIVE" ? "ok" : a.status === "BLOCKED" ? "threat" : "amber"} className="ml-auto">{a.status.toLowerCase()}</Chip>}
      </div>
      {q.isLoading && <Skeleton className="mt-3 h-24" />}
      {q.error ? <p className="mt-2 text-[12.5px] text-threat">{q.error instanceof Error ? q.error.message : "Not reachable"}</p> : null}
      {a && (
        <>
          <div className="mt-2 flex items-baseline justify-between gap-3">
            <div className="min-w-0">
              <div className="display truncate text-[17px] font-semibold text-ink">{a.name}</div>
              <div className="num text-[11.5px] text-muted">{a.accountId} · {a.customerId} · {a.segment.toLowerCase().replaceAll("_", " ")}</div>
            </div>
            <CountUp value={a.balance} format={(v) => `₹${Math.round(v).toLocaleString("en-IN")}`} className="num text-[22px] font-semibold text-ink" />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
            <div className="rounded-lg bg-panel-2 px-3 py-2"><div className="text-[10.5px] uppercase tracking-wide text-faint">Registered mobile</div><div className="num font-medium text-ink">{a.registeredMobile}</div></div>
            <div className="rounded-lg bg-panel-2 px-3 py-2"><div className="text-[10.5px] uppercase tracking-wide text-faint">Limit per transfer</div><div className="num font-medium text-ink">₹{a.transactionLimit.toLocaleString("en-IN")}</div></div>
          </div>
        </>
      )}
    </Panel>
  );
}

// ── 3. commit it ────────────────────────────────────────────────────────────

// Colours by the bank system that recorded a row (names from app.loom.compose.source_system).
const SYSTEM_TONE: Record<string, Tone> = {
  "VPN gateway": "ai", "Branch SSO": "ok", "IAM": "amber", "HRMS": "ok", "CBS application audit": "faint", "Core banking": "threat",
  "Service desk": "ok", "UIDAI eKYC": "ok", "Digital banking": "info", "Device registry": "amber",
};
const toneOf = (system: string): Tone => SYSTEM_TONE[system] ?? (system.endsWith(" switch") ? "threat" : "faint");

function PerformStage({ pb, sim, steps, busyStep, error, auto, busy, onStep, onPlay, onStop, onDetect }: {
  pb: Playbook; sim: Sim; steps: ReturnType<Playbook["steps"]>; busyStep: number | null; error: { i: number; message: string } | null;
  auto: boolean; busy: boolean; onStep: (i: number) => void; onPlay: () => void; onStop: () => void; onDetect: () => void;
}) {
  const victimId = pb.victim(sim.params);
  const victim = useQuery<Account>({ queryKey: ["sim-account", victimId], queryFn: () => account(victimId) });
  const next = sim.results.length;
  const finished = next >= steps.length;
  const rows = sim.results.flatMap((r) => r.rows);
  const systems = new Map<string, number>();
  for (const r of rows) systems.set(r.system, (systems.get(r.system) ?? 0) + 1);
  const last = rows.at(-1);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] xl:items-start">
      <Panel>
        <PanelHead eyebrow={`${pb.title} · action ${Math.min(next + 1, steps.length)} of ${steps.length}`} title={finished ? "Done. The bank has recorded everything." : "Commit the fraud, one action at a time"}
          right={!finished && (auto
            ? <Button size="sm" variant="outline" onClick={onStop}><Square size={12} /> Pause</Button>
            : <Button size="sm" variant="ghost" disabled={busyStep !== null} onClick={onPlay}><FastForward size={13} /> Play the rest</Button>)} />
        <ol className="relative mx-5 mb-5 border-l border-line pl-6">
          {steps.map((s, i) => {
            const res = sim.results[i];
            const state = res ? "done" : i === next ? (busyStep === i ? "running" : error?.i === i ? "error" : "now") : "later";
            return (
              <li key={s.key} className="relative pb-4 last:pb-0">
                <span className={cn("absolute -left-[37px] top-0.5 grid size-6 place-items-center rounded-full border-2 border-panel text-[11px] num",
                  state === "done" ? "bg-ok text-on-primary" : state === "running" ? "bg-ai text-on-primary" : state === "error" ? "bg-threat text-on-primary"
                    : state === "now" ? "bg-primary text-on-primary" : "bg-panel-2 text-faint")}>
                  {state === "done" ? <Check size={12} /> : state === "running" ? <Loader2 size={12} className="animate-spin" /> : state === "error" ? "!" : i + 1}
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip tone={ACTOR[s.actor].tone} className="!py-0 !text-[10.5px]">{ACTOR[s.actor].label}</Chip>
                  <span className="text-[11px] text-faint">{s.system}</span>
                </div>
                <div className={cn("mt-0.5 text-[14px] font-semibold", state === "later" ? "text-muted" : "text-ink")}>{s.title}</div>
                {(state === "now" || state === "running" || state === "error") && (
                  <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
                    <p className="mt-1 max-w-[70ch] text-[12.5px] leading-relaxed text-muted">{s.story}</p>
                    {state === "error" && (
                      <div className="mt-2 rounded-lg border border-threat/30 bg-threat-soft px-3 py-2 text-[12.5px] text-threat">
                        <b>The bank refused:</b> {error!.message}
                      </div>
                    )}
                    <Button size="sm" variant={pb.kind === "twin" ? "primary" : "danger"} className="mt-2" disabled={busyStep !== null || auto} onClick={() => onStep(i)}>
                      {state === "running" ? <Loader2 size={13} className="animate-spin" /> : <Play size={12} />} {state === "error" ? "Try again" : s.cta}
                    </Button>
                  </motion.div>
                )}
                {res && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-1">
                    <p className="text-[12.5px] text-ink-2">{res.note}</p>
                    {res.rows.length > 0 && (
                      <ul className="mt-1.5 space-y-1">
                        {res.rows.map((r) => (
                          <li key={r.seq} className="flex items-start gap-2 rounded-md bg-panel-2 px-2.5 py-1.5 text-[11.5px]">
                            <span className="num shrink-0 text-faint">{dayMonth(r.t)} {hhmm(r.t)}</span>
                            <Chip tone={toneOf(r.system)} className="!py-0 !text-[10.5px] shrink-0">{r.system}</Chip>
                            <span className="min-w-0 leading-snug text-ink-2">{r.summary}</span>
                            <span className="num ml-auto shrink-0 text-faint">{r.ref}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </motion.div>
                )}
              </li>
            );
          })}
        </ol>
      </Panel>

      <div className="flex flex-col gap-4 xl:sticky xl:top-[76px]">
        <AccountCard title="Target account, live" q={victim} />
        <Panel className="p-5">
          <div className="flex items-center gap-2">
            <ReceiptText size={15} className="text-muted" />
            <span className="eyebrow">What the bank&apos;s systems recorded</span>
            {last && <span className="num ml-auto flex items-center gap-1 text-[11.5px] text-faint"><Clock3 size={11} /> bank time {hhmm(last.t)}</span>}
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="num display text-[28px] font-semibold text-ink">{rows.length}</span>
            <span className="text-[12.5px] text-muted">records from {systems.size} system{systems.size === 1 ? "" : "s"}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {[...systems.entries()].map(([sys, c]) => <Chip key={sys} tone={toneOf(sys)}>{sys} · {c}</Chip>)}
          </div>
          <p className="mt-3 text-[11.5px] leading-relaxed text-faint">
            SUTRA never sees what you meant to do, only these rows: sessions, the core-banking audit trail, master-data changes, payees and transfers.
            They are already in SUTRA&apos;s evidence store, Loom, the way a change-data-capture feed delivers them.
          </p>
        </Panel>
        <Panel className={cn("p-5", finished && "ring-1 ring-threat/30")}>
          <div className="eyebrow mb-1">Hand it to SUTRA</div>
          <p className="text-[12.5px] leading-relaxed text-muted">
            {finished
              ? "Run detection now, as the scheduled 15-minute job would: every engine re-reads all 90 days with your records included."
              : `Finish the ${steps.length - next} remaining action${steps.length - next === 1 ? "" : "s"} first, or run detection on what has happened so far.`}
          </p>
          <Button variant="primary" className="mt-3 w-full" disabled={busy || busyStep !== null || auto || rows.length === 0} onClick={onDetect}>
            <ShieldCheck size={15} /> Run SUTRA detection
          </Button>
        </Panel>
      </div>
    </div>
  );
}

// ── 4. SUTRA investigates ───────────────────────────────────────────────────

function JudgeStage({ pb, sim, run, onVisit, onAgain, onReset }: {
  pb: Playbook; sim: Sim; run: ReturnType<typeof useLiveRun>["state"]; onVisit: (href: string) => void; onAgain: () => void; onReset: () => void;
}) {
  const live = run.runId === sim.runId && run.phase !== "error" && run.phase !== "idle";
  const done = live ? run.phase === "done" : !!sim.outcome;
  const verdict = (live ? run.result?.verdict : null) ?? sim.outcome?.verdict ?? null;
  const alerts = live && run.phase === "done" ? run.alerts.filter((a) => a.new) : sim.outcome?.alerts ?? [];
  // Only what this simulation's own rows set off: the bank may hold rows from earlier simulations too.
  const mine = new Set(sim.results.flatMap((r) => r.rows.map((x) => x.ref)));
  const signals = run.signals.filter((s) => !s.refs || s.refs.some((r) => mine.has(r)));
  const alibi = run.alibi.filter((a) => mine.has(a.ref));
  const detectors = live && run.phase === "done" ? [...new Set(signals.map((s) => s.detector))]
    : (sim.outcome?.detectors ?? []);
  const check = done ? meets(pb.expect, alerts, detectors, live ? alibi : []) : null;
  const queued = alerts.filter((a) => QUEUED.includes(a.priority));
  const main = queued[0] ?? alerts[0];

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] xl:items-start">
      <div className="flex flex-col gap-4">
        {!done && <EngineProgress run={run} live={live} />}
        {done && verdict && <Verdict v={verdict} check={check} expectText={pb.expectText} elapsed={run.result?.elapsed ?? sim.outcome?.elapsed} />}
        <AnimatePresence>
          {alerts.map((a) => <AlertCard key={a.id} a={a} caseState={sim.cases[a.id]} autoCase={sim.autoCase} onVisit={onVisit} />)}
        </AnimatePresence>
        {done && live && signals.length > 0 && <Signals signals={signals} />}
        {done && live && alibi.length > 0 && <Alibi rows={alibi} />}
        {done && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={onAgain}><Siren size={14} /> Simulate another fraud</Button>
            <Button variant="ghost" onClick={onReset}><RotateCcw size={14} /> Reset the bank</Button>
          </div>
        )}
      </div>
      <div className="xl:sticky xl:top-[76px]">
        {done ? <Journey pb={pb} sim={sim} alert={main && QUEUED.includes(main.priority) ? main : null} onVisit={onVisit} />
          : <Panel className="p-5 text-[12.5px] leading-relaxed text-muted">
            <div className="eyebrow mb-1">While SUTRA works</div>
            Nothing is pre-computed. Alibi looks for a legitimate reason behind every staff access; the rules, models and graph
            detectors raise signals; Needle tries to join a privilege to money leaving the bank; Brief argues the result both ways
            and sets a priority by readable rules. Alert IDs, triage and open cases survive every run.
          </Panel>}
      </div>
    </div>
  );
}

function meets(e: Expect, alerts: LiveAlert[], detectors: string[], alibi: LiveAlibi[]): { ok: boolean; parts: string[] } {
  const queued = alerts.filter((a) => QUEUED.includes(a.priority));
  const parts: string[] = [];
  let ok = true;
  if (e.alert === null) {
    ok &&= queued.length === 0;
    parts.push(queued.length ? `unexpected ${queued[0].priority} ${queued[0].typology_label}` : "no alert queued");
  } else {
    const hit = queued.find((a) => (e.alert === "P1" ? a.priority === "P1" : true) && (!e.typology || a.typology === e.typology));
    ok &&= !!hit;
    parts.push(hit ? `${hit.priority} ${hit.typology_label}` : `expected ${e.alert === "P1" ? "a P1" : "a queued alert"}`);
  }
  if (e.signal) {
    ok &&= detectors.includes(e.signal);
    parts.push(detectors.includes(e.signal) ? `${e.signal} signal raised` : `no ${e.signal} signal`);
  }
  if (e.alibi && alibi.length) {
    const mine = alibi.filter((r) => r.employee_id === e.alibi!.employee);
    const good = mine.length > 0 && mine.every((r) => r.verdict === e.alibi!.verdict);
    ok &&= good;
    parts.push(`Alibi: ${mine.length} access${mine.length === 1 ? "" : "es"} ${good ? e.alibi.verdict.toLowerCase() : "mixed"}`);
  }
  return { ok, parts };
}

function EngineProgress({ run, live }: { run: ReturnType<typeof useLiveRun>["state"]; live: boolean }) {
  const stages = run.stages;
  const doneN = stages.filter((s) => run.progress[s.key]?.status === "done").length;
  return (
    <Panel className="p-5">
      <div className="flex items-center gap-2">
        <Loader2 size={15} className="animate-spin text-ai" />
        <span className="display text-[17px] font-semibold text-ink">SUTRA is re-reading all 90 days, your records included…</span>
      </div>
      <p className="mt-1 text-[12px] text-muted">{live ? `${doneN} of ${stages.length || 10} stages · usually under a minute` : "Connecting to the run…"}</p>
      <ol className="mt-3 grid gap-1.5 sm:grid-cols-2">
        {stages.map((s) => {
          const p = run.progress[s.key];
          const st = p?.status ?? "pending";
          return (
            <li key={s.key} className={cn("flex items-start gap-2 rounded-lg border px-2.5 py-1.5", st === "running" ? "border-ai/40 bg-ai-soft/50" : st === "done" ? "border-line" : "border-dashed border-line")}>
              <span className="mt-0.5">{st === "done" ? <CheckCircle2 size={13} className="text-ok" /> : st === "running" ? <Loader2 size={13} className="animate-spin text-ai" /> : <Circle size={13} className="text-faint" />}</span>
              <span className="min-w-0">
                <span className={cn("block text-[12.5px] font-semibold", st === "pending" ? "text-muted" : "text-ink")}>{s.label}</span>
                <span className="block text-[11px] leading-snug text-muted">{p?.detail ?? s.what}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

const VERDICT: Record<LiveVerdict["outcome"], { text: string; ring: string; icon: LucideIcon; label: string }> = {
  alert: { text: "text-threat", ring: "ring-threat/30", icon: Siren, label: "Caught" },
  watch: { text: "text-amber", ring: "ring-amber/30", icon: Eye, label: "On the watch list" },
  updated: { text: "text-ai", ring: "ring-ai/30", icon: Route, label: "Linked to an existing alert" },
  explained: { text: "text-ok", ring: "ring-ok/30", icon: ShieldCheck, label: "Explained, no alert" },
  signals: { text: "text-info", ring: "ring-info/30", icon: Activity, label: "Signals only, no alert" },
};

function Verdict({ v, check, expectText, elapsed }: { v: LiveVerdict; check: { ok: boolean; parts: string[] } | null; expectText: string; elapsed?: number }) {
  const s = VERDICT[v.outcome];
  const Icon = s.icon;
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: "spring", stiffness: 260, damping: 24 }}>
      <Panel className={cn("p-5 ring-1", s.ring)}>
        <div className={cn("eyebrow flex items-center gap-1.5", s.text)}>
          <Icon size={13} /> {s.label} · SUTRA&apos;s verdict{elapsed != null && <span className="text-faint"> · {duration(elapsed)}</span>}
        </div>
        <p className="display mt-1.5 text-[20px] font-semibold leading-snug text-ink">{v.headline}</p>
        <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{v.detail}</p>
        {check && (
          <div className={cn("mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-[12.5px]", check.ok ? "bg-ok-soft text-ok" : "bg-amber-soft text-amber")}>
            {check.ok ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <CircleAlert size={14} className="mt-0.5 shrink-0" />}
            <span><b>{check.ok ? "As expected" : "Not what the playbook expected"}:</b> {check.parts.join(" · ")}
              {!check.ok && <span className="block text-[11.5px] opacity-80">Expected: {expectText}</span>}</span>
          </div>
        )}
      </Panel>
    </motion.div>
  );
}

function AlertCard({ a, caseState, autoCase, onVisit }: { a: LiveAlert; caseState?: { caseId?: string; error?: string }; autoCase: boolean; onVisit: (href: string) => void }) {
  const queued = QUEUED.includes(a.priority);
  const login = a.links.find((l) => l.code === "E1");
  const payout = a.links.find((l) => l.code === "E5");
  const gap = login && payout ? (+new Date(payout.t) - +new Date(login.t)) / 1000 : null;
  return (
    <motion.div initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 24 }}>
      <Panel className={cn("overflow-hidden", queued && "ring-1 ring-threat/30")}>
        <div className={cn("flex flex-wrap items-center gap-2 border-b border-line px-5 py-2.5", queued ? "bg-threat-soft/60" : "bg-panel-2")}>
          {queued && <span className="relative flex size-2.5"><span className="absolute inset-0 animate-ping rounded-full bg-threat opacity-60" /><span className="relative size-2.5 rounded-full bg-threat" /></span>}
          <span className={cn("text-[12px] font-semibold", queued ? "text-threat" : "text-muted")}>{queued ? "New alert in the Signal Desk" : "Kept on the watch list"}</span>
          <span className="num ml-auto text-[12px] font-semibold text-ink">{a.id}</span>
        </div>
        <div className="px-5 pt-4">
          <div className="flex flex-wrap items-center gap-1.5"><PriorityPill p={a.priority} /><TypologyChip t={a.typology} label={a.typology_label} /></div>
          <p className="display mt-2 text-[18px] font-semibold leading-snug text-ink">{a.claim}</p>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Metric label="at risk" value={lakh(a.amount)} tone="text-threat" />
            <Metric label="login → money out" value={gap != null ? duration(gap) : "—"} />
            <Metric label="staff · account" value={<span className="block text-[13px] leading-tight">{a.employee_id ?? "none"}<span className="block text-[12px] font-medium text-muted">{a.account_id ?? "—"}</span></span>} />
          </div>
        </div>
        <ol className="mx-5 mt-4 space-y-1 border-l border-line pl-4">
          {a.links.map((l, i) => (
            <li key={`${l.code}-${i}`} className="relative py-0.5">
              <span className={cn("absolute -left-[21px] top-2 size-2.5 rounded-full border-2 border-panel", l.live ? "bg-threat" : "bg-faint")} />
              <div className="flex items-baseline gap-2">
                <Chip tone="faint" className="num !px-1.5 !py-0 !text-[10.5px]">{l.code}</Chip>
                <span className="text-[12.5px] font-medium text-ink">{l.title}</span>
                <span className="num ml-auto shrink-0 text-[11px] text-faint">{dayMonth(l.t)} {hhmm(l.t)}</span>
              </div>
              <p className="ml-[2px] text-[11.5px] leading-snug text-muted">{l.detail}</p>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          {queued && (caseState?.caseId ? (
            <Chip tone="ok"><BriefcaseBusiness size={11} /> Case {caseState.caseId} opened · Case Desk</Chip>
          ) : caseState?.error ? (
            <Chip tone="amber">{caseState.error}</Chip>
          ) : autoCase ? (
            <Chip tone="faint"><Loader2 size={11} className="animate-spin" /> Opening a case…</Chip>
          ) : null)}
          <Link href={`/cases/${a.id}`} onClick={() => onVisit(`/cases/${a.id}`)}
            className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-full bg-primary px-3.5 text-[12.5px] font-medium text-on-primary hover:bg-primary-pressed">
            Open the case file <ArrowRight size={13} />
          </Link>
        </div>
      </Panel>
    </motion.div>
  );
}

function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg bg-panel-2 px-3 py-2">
      <div className={cn("num text-[16px] font-semibold leading-tight text-ink", tone)}>{value}</div>
      <div className="mt-0.5 text-[10.5px] uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}

const FAMILY_TONE: Record<string, Tone> = { RULE: "info", ML: "ai", GRAPH: "amber" };

function Signals({ signals }: { signals: LiveSignal[] }) {
  const seen = new Set<string>();
  const uniq = signals.filter((s) => {
    const k = `${s.detector}|${s.summary}`;
    return seen.has(k) ? false : (seen.add(k), true);
  });
  const detectors = new Set(uniq.map((s) => s.detector)).size;
  return (
    <Panel>
      <PanelHead eyebrow={`Signals · ${uniq.length} from ${detectors} detector${detectors === 1 ? "" : "s"}`} title="What your actions set off" />
      <ul className="space-y-1.5 px-5 pb-3">
        {uniq.slice(0, 10).map((s) => (
          <li key={`${s.detector}|${s.summary}`} className="flex items-start gap-2 text-[12px]">
            <Chip tone={FAMILY_TONE[s.family] ?? "faint"} mono className="mt-0.5 shrink-0">{s.detector}</Chip>
            <span className="leading-snug"><b className="font-medium text-ink">{s.name}</b> <span className="text-muted">· {s.summary}</span></span>
          </li>
        ))}
      </ul>
      <p className="border-t border-line px-5 py-2.5 text-[11.5px] leading-relaxed text-faint">
        A signal on its own never raises an alert. Needle has to connect it to money leaving the bank, and Brief has to grade the evidence.
      </p>
    </Panel>
  );
}

function Alibi({ rows }: { rows: LiveAlibi[] }) {
  const byEmp = new Map<string, LiveAlibi[]>();
  for (const r of rows) byEmp.set(r.employee_id, [...(byEmp.get(r.employee_id) ?? []), r]);
  return (
    <Panel>
      <PanelHead eyebrow="Alibi · staff accesses" title="Was there a legitimate reason?" />
      <div className="space-y-2 px-5 pb-4">
        {[...byEmp.entries()].map(([emp, list]) => {
          const explained = list.every((r) => r.verdict === "EXPLAINED");
          const reasons = [...new Set(list.flatMap((r) => r.checked.filter((c) => c.ok).map((c) => c.template.toLowerCase())))];
          return (
            <div key={emp} className={cn("rounded-lg border p-3", explained ? "border-ok/30 bg-ok-soft/40" : "border-threat/30 bg-threat-soft/40")}>
              <div className="flex items-center gap-2">
                <span className="num text-[12.5px] font-semibold text-ink">{emp}</span>
                <Chip tone={explained ? "ok" : "threat"}>{explained ? "explained" : "unexplained"}</Chip>
                <span className="num ml-auto text-[11px] text-faint">{list.length} access{list.length === 1 ? "" : "es"}</span>
              </div>
              <p className="mt-1 text-[11.5px] text-muted">
                {reasons.length ? `Reasons on record: ${reasons.join(", ")}` : "No ticket, roster, queue item, portfolio or customer contact behind these accesses."}
              </p>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ── the investigation journey: from the alert to a concluded case ───────────

interface Stop { href: string; icon: LucideIcon; title: string; what: string }

function journey(a: LiveAlert): Stop[] {
  return [
    { href: "/signals", icon: Siren, title: "Signal Desk", what: "The alert waits in triage, argued both ways, with the rule that set its priority." },
    { href: `/cases/${a.id}`, icon: BriefcaseBusiness, title: "Case file", what: "Seven dimensions of evidence for and against, benign hypotheses tested, the SLA running." },
    { href: `/replay?alert=${a.id}`, icon: History, title: "Timeline Replay", what: "Watch the chain assemble minute by minute, from the first access to the money leaving." },
    ...(a.employee_id ? [{ href: `/alibi?employee=${a.employee_id}`, icon: ReceiptText, title: "Alibi Ledger", what: `Why did ${a.employee_id} open these accounts? Ticket, roster, queue, portfolio, contact.` }] : []),
    ...(a.account_id ? [{ href: `/trail?account=${a.account_id}`, icon: Route, title: "Money Trail", what: `Follow the money out of ${a.account_id} to the payees and beyond.` }] : []),
    { href: `/council/${a.id}`, icon: Landmark, title: "Investigation Council", what: "Specialist agents debate the evidence and hand a finding, with any dissent, to a human." },
    { href: `/evidence/arguments?alert=${a.id}`, icon: Scale, title: "Prosecution & defence", what: "Every claim with the evidence that supports it and the evidence that cuts against it." },
    { href: `/evidence/missing?alert=${a.id}`, icon: FileQuestion, title: "Missing evidence", what: "What would change the conclusion, and who holds it." },
    { href: `/controls?alert=${a.id}`, icon: FlaskConical, title: "Control Lab", what: "Which control would have broken the chain, how early, and what it costs legitimate work." },
    { href: `/cases/${a.id}`, icon: Gavel, title: "Conclude the case", what: "Propose a decision (escalate, file an STR or close as benign); a second reviewer must approve it." },
  ];
}

function Journey({ pb, sim, alert, onVisit }: { pb: Playbook; sim: Sim; alert: LiveAlert | null; onVisit: (href: string) => void }) {
  if (!alert) {
    const acct = pb.victim(sim.params);
    const stops: Stop[] = pb.expect.alibi
      ? [{ href: `/alibi?employee=${pb.expect.alibi.employee}`, icon: ReceiptText, title: "Alibi Ledger", what: `Every access by ${pb.expect.alibi.employee}, with the reasons Alibi found.` },
        { href: `/entities/${acct}`, icon: Wallet, title: `Account ${acct}`, what: "Its history, signals and any alerts, in the Entity Explorer." }]
      : [{ href: `/entities/${acct}`, icon: Wallet, title: `Account ${acct}`, what: "The signal is on the account's file, waiting to join a chain." },
        { href: `/trail?account=${acct}`, icon: Route, title: "Money Trail", what: "Follow the money in and out of the account." }];
    return (
      <Panel>
        <PanelHead eyebrow="Where to look" title={pb.kind === "twin" ? "SUTRA stayed quiet. Here is why." : "No case, by design"} />
        <p className="px-5 text-[12.5px] leading-relaxed text-muted">{pb.takeaway}</p>
        <Stops stops={stops} visited={sim.visited} onVisit={onVisit} />
      </Panel>
    );
  }
  const stops = journey(alert);
  const hrefs = new Set(stops.map((s) => s.href));
  const seen = [...hrefs].filter((h) => sim.visited.includes(h)).length;
  return (
    <Panel>
      <PanelHead eyebrow={`Investigate ${alert.id} · ${seen} of ${hrefs.size} explored`} title="From alert to a concluded case" />
      <p className="px-5 text-[12.5px] leading-relaxed text-muted">{pb.takeaway}</p>
      <Stops stops={stops} visited={sim.visited} onVisit={onVisit} numbered />
    </Panel>
  );
}

function Stops({ stops, visited, onVisit, numbered }: { stops: Stop[]; visited: string[]; onVisit: (href: string) => void; numbered?: boolean }) {
  return (
    <ol className="space-y-1.5 px-4 pt-3 pb-4">
      {stops.map((s, i) => {
        const Icon = s.icon;
        const seen = visited.includes(s.href) && !(i === stops.length - 1 && numbered);
        return (
          <li key={`${s.href}-${i}`}>
            <Link href={s.href} onClick={() => onVisit(s.href)}
              className="group flex items-start gap-3 rounded-xl border border-line px-3 py-2.5 transition-colors hover:border-line-strong hover:bg-panel-2">
              <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", seen ? "bg-ok-soft text-ok" : "bg-panel-2 text-ink-2")}>
                {seen ? <Check size={15} /> : <Icon size={15} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-semibold text-ink">{numbered && <span className="num mr-1.5 text-faint">{i + 1}.</span>}{s.title}</span>
                <span className="block text-[11.5px] leading-snug text-muted">{s.what}</span>
              </span>
              <ArrowRight size={14} className="mt-2 shrink-0 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
