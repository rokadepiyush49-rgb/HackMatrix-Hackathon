"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Activity, ArrowRight, Building2, ExternalLink, Check, CheckCircle2, Eye, FlaskConical, Gauge, Landmark, Link2, Loader2, PenLine, Play, Radio,
  RotateCcw, Scale, ShieldCheck, Siren, Square, TimerReset, Volume2, VolumeX, X, type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { TypologyChip } from "@/components/chain/alert-bits";
import { ComposeForm } from "@/components/live/compose-form";
import { idleRun, useLiveRun, type RunState } from "@/components/live/use-live-run";
import { Button, ButtonLink, Chip, CountUp, Dot, Empty, ErrorBox, PageHeader, Panel, PanelHead, PriorityPill, Skeleton, type Tone } from "@/components/ui/primitives";
import { ApiError, useGet, useMe, useOpenCase } from "@/lib/api";
import { cn, dayMonth, duration, hhmm, inr } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { LiveAlert, LiveAlibi, LiveFeedRow, LiveLink, LiveSignal, LiveStatus, LiveVerdict, Strand } from "@/lib/types";
import { PERSONAS, speak, stopSpeaking, useVoices, useVoiceSetting, useVoiceSupported } from "@/lib/voice";

const SPEEDS = [
  { v: 120, label: "120×" },
  { v: 240, label: "240×" },
  { v: 600, label: "600×" },
  { v: 0, label: "Instant" },
];

// Source systems by what they tell an investigator: staff actions, master data, customer channels,
// money movement, and the paperwork that explains staff actions.
const SYSTEM_TONE: Record<string, Tone> = {
  "VPN gateway": "amber", "Branch SSO": "amber", "CBS application audit": "amber", IAM: "amber",
  "Core banking": "ai", "Digital banking": "info", "Device registry": "info",
  "Service desk": "ok", "UIDAI eKYC": "ok", HRMS: "ok",
};
const systemTone = (s: string): Tone => SYSTEM_TONE[s] ?? "faint";
const LANE_TONE: Record<string, Tone> = { IAM: "ai", SOC: "amber", FRAUD: "threat", AML: "info", HR: "ok" };
const FAMILY_TONE: Record<string, Tone> = { RULE: "info", ML: "ai", GRAPH: "amber" };
const STRAND: Record<Strand, { label: string; tone: Tone }> = {
  attack: { label: "attack", tone: "threat" }, camp: { label: "pension camp", tone: "ok" }, routine: { label: "routine", tone: "faint" },
};
const REASON: Record<string, string> = {
  TICKET: "ticket", PORTFOLIO: "portfolio", QUEUE: "work queue", INTERACTION: "customer contact", ROSTER: "roster",
};

type Mode = "evening" | "yours" | "bank";
const SOURCE: Record<Mode, string> = { evening: "tonight's feed", yours: "your input", bank: "Kestrel Bank" };
type Filter = "all" | "linked" | "staff" | "money";
// Two decimals, as the chain itself words amounts (₹14.15 L, not ₹14.2 L).
const lakh = (v: number) => (v >= 1e5 ? `₹${(v / 1e5).toFixed(2)} L` : inr(v));
const STAFF_TABLES = new Set(["access_event", "state_change", "work_item"]);
const FEED_DAY = "2026-09-22";

const SUB: Record<Mode, string> = {
  evening: "The evening of 22 Sep is held back from the bank's systems. Press play and SUTRA ingests it row by row from the source systems, re-runs every engine on the full 90-day window, and shows what it found — with the real timings. Somewhere in the traffic is an insider takeover, and a legitimate pension camp that looks like one.",
  yours: "Now you are the member of staff. Choose who logs in, when, what paperwork exists, what changes and where the money goes. Your choices become the rows each bank system would record, and SUTRA judges them exactly as it judges tonight's feed — try to get past it.",
  bank: "Kestrel Bank is a working test bank: a staff core-banking console and customer NetBanking. Whatever you do there is recorded by the bank's systems and lands here as it happens. Press Run detection now, as the 15-minute job would, and see what SUTRA makes of it.",
};

const hashStore = {
  subscribe: (cb: () => void) => {
    window.addEventListener("hashchange", cb);
    return () => window.removeEventListener("hashchange", cb);
  },
  get: () => window.location.hash,
};

/** Which mode a run belongs to; null while connecting (it belongs to whichever mode started it). */
function ownerOf(r: RunState): Mode | null {
  if (r.phase === "idle" || !r.scope) return null;
  return r.scope === "yours" ? "yours" : r.scope === "bank" ? "bank" : "evening";
}

export default function LiveOps() {
  const router = useRouter();
  const reduce = useReducedMotion();
  const { data: me } = useMe();
  const status = useGet<LiveStatus>(["live-status"], "/live/status", { refetchInterval: (q) => (q.state.data?.busy ? 2000 : false) });
  const [speed, setSpeed] = useState(240);
  const [voiceOn, setVoiceOn] = useVoiceSetting();
  const voices = useVoices();
  const canSpeak = useVoiceSupported();
  const [confirmReset, setConfirmReset] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [modeChoice, setMode] = useState<Mode | null>(null);
  const [editing, setEditing] = useState(false);

  const announce = (text: string) => {
    if (voiceOn) speak(text, PERSONAS.announcer, voices);
  };
  const hash = useSyncExternalStore(hashStore.subscribe, hashStore.get, () => "");
  const { state, attach, start, compose, detectBank, reset, cancel } = useLiveRun({
    onAlert: (a) => {
      if (a.new && ["P1", "P2"].includes(a.priority)) {
        const login = a.links.find((l) => l.code === "E1");
        const payout = a.links.find((l) => l.code === "E5");
        const gap = login && payout ? ` Money left ${duration((+new Date(payout.t) - +new Date(login.t)) / 1000)} after the login.` : "";
        announce(`New ${a.priority} alert, ${a.id}. ${a.claim}. ${lakh(a.amount)} at risk.${gap}`);
      }
    },
    onDone: (r, kind, scope) => {
      status.refetch();
      if (kind !== "feed") return;
      if (scope === "yours" || scope === "bank") {
        if (r.verdict && !["alert", "watch"].includes(r.verdict.outcome)) announce(r.verdict.headline);
      } else if (!(r.new ?? []).length) announce("Tonight's feed is in. No new alerts.");
    },
  });

  // Re-attach to the latest run on load: a reload mid-demo picks up exactly where it was.
  const attached = useRef(false);
  useEffect(() => {
    const run = status.data?.run;
    if (!attached.current && run) {
      attached.current = true;
      attach(run.id);
    }
  }, [status.data?.run, attach]);
  useEffect(() => stopSpeaking, []);

  const st = status.data;
  // A finished undo leaves nothing to look at in its mode, so the page opens on tonight's feed again.
  const last = st?.run && !(st.run.kind === "reset" && st.run.finished) ? st.run.scope : null;
  const mode: Mode = modeChoice ?? (hash === "#bank" ? "bank" : last === "yours" ? "yours" : last === "bank" ? "bank" : "evening");
  const owner = ownerOf(state);
  const run = owner === null || owner === mode ? state : idleRun;
  const busy = !!st?.busy || ["connecting", "streaming", "detecting"].includes(state.phase);
  const played = !!st && st.pending === 0;
  const yoursIn = (st?.yours.ingested ?? 0) > 0;
  const bankIn = (st?.bank?.ingested ?? 0) > 0;
  const spanS = st?.feed_start && st.feed_end ? (+new Date(st.feed_end) - +new Date(st.feed_start)) / 1000 : 0;

  const go = async (fn: () => Promise<void>) => {
    setActionError(null);
    try {
      await fn();
      status.refetch();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Could not reach the API.");
    }
  };
  const undo = (scope: "all" | "yours" | "bank") => {
    setConfirmReset(false);
    setEditing(false);
    go(() => reset(scope));
  };

  let action: ReactNode = null;
  if (state.phase === "streaming") {
    action = <Button variant="outline" onClick={() => go(cancel)}><Square size={13} /> Stop</Button>;
  } else if (mode === "evening") {
    action = played || yoursIn ? (confirmReset ? (
      <>
        <Button variant="danger" disabled={busy} onClick={() => undo("all")}><RotateCcw size={14} /> Undo everything &amp; re-detect</Button>
        <Button variant="ghost" onClick={() => setConfirmReset(false)}>Keep</Button>
      </>
    ) : played ? (
      <Button variant="outline" disabled={busy} onClick={() => setConfirmReset(true)}><RotateCcw size={14} /> Reset demo</Button>
    ) : (
      <>
        <Button variant="ghost" disabled={busy} onClick={() => setConfirmReset(true)}><RotateCcw size={14} /> Reset</Button>
        <Button variant="primary" disabled={busy || !st?.pending} onClick={() => go(() => start(speed))}><Play size={14} /> Play tonight&apos;s feed</Button>
      </>
    )) : (
      <Button variant="primary" disabled={busy || !st?.pending} onClick={() => go(() => start(speed))}><Play size={14} /> Play tonight&apos;s feed</Button>
    );
  } else if (mode === "bank") {
    action = (
      <>
        {bankIn && (confirmReset ? (
          <>
            <Button variant="danger" disabled={busy} onClick={() => undo("bank")}><RotateCcw size={14} /> Undo bank activity &amp; re-detect</Button>
            <Button variant="ghost" onClick={() => setConfirmReset(false)}>Keep</Button>
          </>
        ) : (
          <Button variant="outline" disabled={busy} onClick={() => setConfirmReset(true)}><RotateCcw size={14} /> Undo bank activity</Button>
        ))}
        <Button variant="primary" disabled={busy || !bankIn} onClick={() => go(detectBank)}><Play size={14} /> Run detection now</Button>
      </>
    );
  } else if (yoursIn) {
    action = confirmReset ? (
      <>
        <Button variant="danger" disabled={busy} onClick={() => undo("yours")}><RotateCcw size={14} /> Undo my input &amp; re-detect</Button>
        <Button variant="ghost" onClick={() => setConfirmReset(false)}>Keep</Button>
      </>
    ) : (
      <Button variant="outline" disabled={busy} onClick={() => setConfirmReset(true)}><RotateCcw size={14} /> Undo my input</Button>
    );
  }

  const yoursLeft = run.kind === "feed" && run.phase !== "idle" && !editing
    ? <YourRowsPanel run={run} canEdit={!busy} onEdit={() => setEditing(true)} />
    : <ComposeForm busy={busy} onSend={async (spec) => {
      setActionError(null);
      await compose(spec, speed);
      setEditing(false);
      setConfirmReset(false);
      status.refetch();
    }} />;

  return (
    <div className="mx-auto max-w-[1680px] p-5">
      <PageHeader
        eyebrow="Live Ops · end to end, nothing pre-computed"
        title={<>From raw events to a <span className="text-threat">P1</span>, live</>}
        sub={SUB[mode]}
        right={<>
          {canSpeak && (
            <Button size="sm" variant={voiceOn ? "ai" : "ghost"} onClick={() => setVoiceOn(!voiceOn)} aria-pressed={voiceOn}
              title="Read new alerts and verdicts aloud (your browser's speech, offline)">
              {voiceOn ? <Volume2 size={14} /> : <VolumeX size={14} />} Voice {voiceOn ? "on" : "off"}
            </Button>
          )}
          <div className="flex items-center rounded-full border border-line bg-panel p-0.5" role="radiogroup" aria-label="Replay speed">
            {SPEEDS.map((s) => (
              <button key={s.v} role="radio" aria-checked={speed === s.v} aria-label={s.label} disabled={busy} onClick={() => setSpeed(s.v)}
                title={s.v ? `≈ ${duration(Math.min(spanS / s.v, 600))} for the evening` : "No pauses between events"}
                className={cn("rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-50",
                  speed === s.v ? "bg-primary text-on-primary" : "text-muted hover:text-ink")}>
                {s.label}
              </button>
            ))}
          </div>
          {action}
        </>}
      />

      {status.error && <ErrorBox error={status.error} />}
      {actionError && <div className="mb-4 rounded-lg border border-threat/30 bg-threat-soft px-4 py-2.5 text-[13px] text-threat">{actionError}</div>}
      {!st && !status.error && <Skeleton className="h-[640px]" />}
      {st && st.total === 0 && (
        <Empty title="No live feed in this database" icon={<Radio size={18} />}>
          Load the demo world with <code className="num">make seed</code> — it holds back the evening of 22 Sep for this page.
        </Empty>
      )}

      {st && st.total > 0 && (
        <>
          <ModeTabs mode={mode} st={st} onChange={(m) => { setMode(m); setConfirmReset(false); }} />
          <MissionBar st={st} run={run} mode={mode} reduce={!!reduce} />
          <div className={cn("mt-4 grid grid-cols-1 gap-4 xl:items-start",
            mode === "evening" ? "xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.85fr)_minmax(0,1.2fr)]"
              : "xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.78fr)_minmax(0,1.15fr)]")}>
            {mode === "evening" ? <InputPanel st={st} run={run} /> : mode === "bank" ? <BankFeedPanel run={run} /> : yoursLeft}
            <EnginePanel st={st} run={run} />
            <OutputPanel run={run} mode={mode} played={played}
              canOpen={!!me && ["L2_INVESTIGATOR", "VIGILANCE", "L1_ANALYST"].includes(me.role)}
              onOpened={(alertId) => router.push(`/cases/${alertId}`)} />
          </div>
        </>
      )}
    </div>
  );
}

// ── where the input comes from ─────────────────────────────────────────────

function ModeTabs({ mode, st, onChange }: { mode: Mode; st: LiveStatus; onChange: (m: Mode) => void }) {
  const tab = (m: Mode, icon: ReactNode, title: string, sub: string, badge?: string) => (
    <button role="tab" aria-selected={mode === m} onClick={() => onChange(m)}
      className={cn("flex items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors",
        mode === m ? "border-ink bg-panel shadow-xs" : "border-line bg-panel/60 hover:bg-panel")}>
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", mode === m ? "bg-primary text-on-primary" : "bg-panel-2 text-muted")}>{icon}</span>
      <span className="min-w-0">
        <span className="flex items-center gap-2 text-[14px] font-semibold text-ink">{title}{badge && <Chip tone="ai">{badge}</Chip>}</span>
        <span className="block text-[12px] text-muted">{sub}</span>
      </span>
    </button>
  );
  return (
    <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3" role="tablist" aria-label="Where the input comes from">
      {tab("evening", <Radio size={17} />, "Tonight's feed", `${st.total} raw events held back from the bank's systems — press play`,
        st.ingested ? "played" : undefined)}
      {tab("yours", <PenLine size={17} />, "Your input", "You act as a member of staff — SUTRA judges what you do",
        st.yours.ingested ? `${st.yours.ingested} rows in` : undefined)}
      {tab("bank", <Building2 size={17} />, "Kestrel Bank", "A working test bank — do it there, judge it here",
        st.bank?.ingested ? `${st.bank.ingested} rows in` : undefined)}
    </div>
  );
}

// ── the bar across the top: clock, ingest progress, stage ticks, elapsed ────

function MissionBar({ st, run, mode, reduce }: { st: LiveStatus; run: RunState; mode: Mode; reduce: boolean }) {
  const bankRows = st.bank?.ingested ?? 0;
  const ingested = mode === "bank" ? bankRows : run.kind === "feed" ? run.events.length : mode === "evening" ? st.ingested : 0;
  const total = mode === "bank" ? bankRows : run.total || (mode === "evening" ? st.total : 0);
  const clock = run.clock ?? (mode === "evening" ? (st.pending ? st.feed_start : st.feed_end) : null);
  const stages = run.stages.length ? run.stages : st.stages;
  const doneStages = stages.filter((s) => run.progress[s.key]?.status === "done").length;
  const live = run.phase === "streaming" || run.phase === "detecting";
  const now = useNow(live ? 200 : 60_000);
  const ticking = live && run.startedAt && now ? (now - +new Date(run.startedAt)) / 1000 : 0;
  const elapsed = run.result?.elapsed ?? Math.max(ticking, ...Object.values(run.progress).map((p) => p.elapsed ?? 0));
  const idle = mode === "evening" ? (st.pending ? { tone: "faint", label: "ready" } : { tone: "ok", label: "tonight's feed is in" })
    : mode === "bank" ? { tone: "faint", label: bankRows ? "waiting for a detection run" : "waiting for the bank" }
      : { tone: "faint", label: "waiting for your input" };
  const phase = {
    idle,
    connecting: { tone: "info", label: "connecting" },
    streaming: { tone: "threat", label: "ingesting" },
    detecting: { tone: "ai", label: "detecting" },
    done: { tone: "ok", label: run.kind === "reset" ? "reset complete" : "complete" },
    cancelled: { tone: "amber", label: "stopped" },
    error: { tone: "threat", label: "failed" },
  }[run.phase] as { tone: Tone; label: string };

  return (
    <Panel className="grid grid-cols-1 items-center gap-4 p-4 md:grid-cols-[auto_minmax(0,1fr)_auto]">
      <div className="flex items-center gap-3">
        <div className="grid size-11 place-items-center rounded-xl bg-primary text-on-primary">{mode === "evening" ? <Radio size={20} /> : mode === "bank" ? <Building2 size={20} /> : <PenLine size={20} />}</div>
        <div>
          <div className="num display text-[26px] font-semibold leading-none text-ink" aria-live="off">{clock ? hhmm(clock, true) : "—"}</div>
          <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-muted">
            <Dot tone={live ? "threat" : "faint"} pulse={live && !reduce} /> IST · {clock ? dayMonth(clock) : "22 Sep"} · bank time
          </div>
        </div>
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[12px]">
          <span className="text-muted"><b className="num text-ink">{ingested}</b> / {total} source rows ingested</span>
          <span className="text-muted"><b className="num text-ink">{doneStages}</b> / {stages.length} stages</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-panel-2">
          <motion.div className="h-full rounded-full bg-threat" initial={false} animate={{ width: `${total ? (ingested / total) * 100 : 0}%` }}
            transition={{ duration: reduce ? 0 : 0.25 }} />
        </div>
        <div className="mt-1.5 grid gap-1" style={{ gridTemplateColumns: `repeat(${Math.max(stages.length, 1)}, minmax(0, 1fr))` }}>
          {stages.map((s) => {
            const p = run.progress[s.key]?.status;
            return <div key={s.key} title={s.label} className={cn("h-1 rounded-full", p === "done" ? "bg-ok" : p === "running" ? "animate-pulse bg-ai" : "bg-panel-2")} />;
          })}
        </div>
      </div>
      <div className="flex items-center gap-3 md:justify-end">
        <div className="text-right">
          <div className="num text-[22px] font-semibold leading-none text-ink">{elapsed ? `${elapsed.toFixed(1)} s` : "—"}</div>
          <div className="mt-1 text-[11px] text-faint">wall-clock</div>
        </div>
        <Chip tone={phase.tone}>{phase.label}</Chip>
      </div>
    </Panel>
  );
}

// ── input: the raw rows as they arrive ─────────────────────────────────────

function useCited(alerts: LiveAlert[]) {
  return useMemo(() => {
    const m = new Map<string, { code: string; alert: string }>();
    for (const a of alerts.filter((x) => x.new)) for (const [ref, code] of Object.entries(a.cited)) if (!m.has(ref)) m.set(ref, { code, alert: a.id });
    return m;
  }, [alerts]);
}

function systemCounts(rows: LiveFeedRow[]): [string, number][] {
  const m = new Map<string, number>();
  for (const r of rows) m.set(r.system, (m.get(r.system) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

function RowItem({ r, cite, strand, enter, dim }: {
  r: LiveFeedRow; cite?: { code: string; alert: string }; strand?: Strand; enter: boolean; dim?: boolean;
}) {
  // Rows from earlier days (an old grant, a roster) show their date rather than a time that looks like tonight.
  const tonight = r.t.slice(0, 10) === FEED_DAY;
  return (
    <motion.div initial={enter ? { opacity: 0, y: -6 } : false} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
      className={cn("grid grid-cols-[58px_minmax(0,1fr)] gap-2 rounded-md px-2 py-1.5", cite && "bg-threat-soft/60 ring-1 ring-inset ring-threat/25",
        dim && "opacity-70")}>
      <span className="num pt-0.5 text-[11px] text-faint">{tonight ? hhmm(r.t, true) : <>{dayMonth(r.t)}<br />{hhmm(r.t)}</>}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone={systemTone(r.system)} className="!px-2 !py-0 !text-[10.5px]">{r.system}</Chip>
          {cite && <span className="num rounded bg-threat px-1.5 text-[10.5px] font-semibold text-on-primary" title={`Cited by ${cite.alert}`}>{cite.code}</span>}
          {strand && <Chip tone={STRAND[strand].tone} className="!px-2 !py-0 !text-[10.5px]">{STRAND[strand].label}</Chip>}
          <span className="num text-[10.5px] text-faint">{r.ref}</span>
        </div>
        <p className="mt-0.5 text-[12px] leading-snug text-ink-2">{r.summary}</p>
      </div>
    </motion.div>
  );
}

function InputPanel({ st, run }: { st: LiveStatus; run: RunState }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [reveal, setReveal] = useState(false);
  const finished = run.phase === "done" && run.kind === "feed";
  const resetting = run.kind === "reset" && run.phase !== "done";
  const showQueue = run.phase === "idle" || (run.kind === "reset" && run.phase === "done");
  // Before a run: what is queued. After: the full feed, with ground truth on request.
  const feed = useGet<LiveFeedRow[]>(["live-feed", reveal && finished], `/live/feed${reveal && finished ? "?reveal=true" : ""}`,
    { enabled: showQueue || finished });
  const truth = useMemo(() => new Map((feed.data ?? []).map((r) => [r.ref, r.strand])), [feed.data]);
  const cited = useCited(run.alerts);

  const rows: LiveFeedRow[] = useMemo(() => (run.kind === "feed" && run.events.length ? run.events
    : showQueue ? (feed.data ?? []).filter((r) => (st.pending ? !r.ingested : true)) : []),
  [run.kind, run.events, showQueue, feed.data, st.pending]);
  const systems = useMemo(() => systemCounts(rows), [rows]);
  const shown = rows.filter((r) =>
    filter === "all" ? true : filter === "linked" ? cited.has(r.ref) : filter === "staff" ? STAFF_TABLES.has(r.table) : r.table === "txn");
  const queued = showQueue && st.pending > 0;
  // Queued rows read like the evening ahead (oldest first); arriving rows stack newest on top.
  const ordered = queued ? shown : [...shown].reverse();

  return (
    <Panel className="flex min-h-[640px] flex-col">
      <PanelHead eyebrow={`Input · ${systems.length || "—"} source systems`} title={queued ? "Queued for tonight" : "Raw events, as they land"}
        right={<Chip tone={run.phase === "streaming" ? "threat" : "faint"}>{rows.length} rows</Chip>} />
      <div className="flex flex-wrap gap-1.5 px-5 pb-3">
        {systems.map(([s, n]) => <Chip key={s} tone={systemTone(s)}>{s} <span className="num opacity-70">{n}</span></Chip>)}
      </div>
      {(cited.size > 0 || finished) && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-5 py-2">
          {([["all", "All"], ["linked", `Linked by SUTRA · ${cited.size}`], ["staff", "Staff actions"], ["money", "Money"]] as [Filter, string][]).map(([k, label]) => (
            <button key={k} onClick={() => setFilter(k)}
              className={cn("rounded-full border px-2.5 py-0.5 text-[12px] font-medium", filter === k ? "border-ink bg-ink text-bg" : "border-line text-muted hover:text-ink")}>
              {label}
            </button>
          ))}
          {finished && (
            <button onClick={() => setReveal((v) => !v)} className={cn("ml-auto inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12px] font-medium",
              reveal ? "border-ai/40 bg-ai-soft text-ai" : "border-line text-muted hover:text-ink")}>
              <Eye size={12} /> {reveal ? "Hide" : "Reveal"} ground truth
            </button>
          )}
        </div>
      )}
      <div className="max-h-[560px] flex-1 overflow-y-auto border-t border-line px-3 py-2" aria-live="off">
        {queued && <p className="px-2 pb-2 text-[12px] text-muted">These rows are not in Loom yet. Nothing about them has been scored, linked or explained.</p>}
        {resetting && <p className="px-2 py-6 text-center text-[12.5px] text-faint">Taking the rows back out of Loom…</p>}
        {!rows.length && !resetting && !showQueue && <p className="px-2 py-6 text-center text-[12.5px] text-faint">Waiting for the first row…</p>}
        {ordered.slice(0, 260).map((r) => (
          <RowItem key={r.seq} r={r} cite={cited.get(r.ref)} strand={reveal ? truth.get(r.ref) : undefined}
            enter={run.phase === "streaming"} dim={queued} />
        ))}
      </div>
    </Panel>
  );
}

function YourRowsPanel({ run, canEdit, onEdit }: { run: RunState; canEdit: boolean; onEdit: () => void }) {
  const cited = useCited(run.alerts);
  const systems = useMemo(() => systemCounts(run.events), [run.events]);
  const ordered = [...run.events].reverse();
  return (
    <Panel className="flex min-h-[640px] flex-col">
      <PanelHead eyebrow={`Your input · ${systems.length || "—"} bank systems`} title="Your actions, as the bank recorded them"
        right={<Button size="sm" variant="outline" disabled={!canEdit} onClick={onEdit}><PenLine size={13} /> Change the input</Button>} />
      <div className="flex flex-wrap gap-1.5 px-5 pb-3">
        {systems.map(([s, n]) => <Chip key={s} tone={systemTone(s)}>{s} <span className="num opacity-70">{n}</span></Chip>)}
        {cited.size > 0 && <Chip tone="threat">{cited.size} linked by SUTRA</Chip>}
      </div>
      <div className="max-h-[560px] flex-1 overflow-y-auto border-t border-line px-3 py-2" aria-live="off">
        {!run.events.length && <p className="px-2 py-6 text-center text-[12.5px] text-faint">Sending your rows to the bank…</p>}
        {ordered.map((r) => <RowItem key={r.seq} r={r} cite={cited.get(r.ref)} enter={run.phase === "streaming"} />)}
      </div>
      <p className="border-t border-line px-5 py-2.5 text-[11.5px] leading-relaxed text-faint">
        Each row is what that system would have logged for your choices, tokenised like every other row. Nothing in it says
        &ldquo;suspicious&rdquo; — that is for SUTRA to work out. <b className="font-medium text-muted">Undo my input</b> takes them back out.
      </p>
    </Panel>
  );
}

function BankFeedPanel({ run }: { run: RunState }) {
  const rows = useGet<LiveFeedRow[]>(["live-bank-activity"], "/live/bank-activity", { refetchInterval: 3000 });
  const cited = useCited(run.alerts);
  const list = useMemo(() => rows.data ?? [], [rows.data]);
  const systems = useMemo(() => systemCounts(list), [list]);
  return (
    <Panel className="flex min-h-[640px] flex-col">
      <PanelHead eyebrow={`Input · recorded by Kestrel Bank · ${systems.length || "—"} systems`} title="The bank's records, as they happen"
        right={<a href="/bank" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-full bg-primary px-3 py-1 text-[12px] font-medium text-on-primary">
          Open Kestrel Bank <ExternalLink size={12} /></a>} />
      <div className="flex flex-wrap gap-1.5 px-5 pb-3">
        {systems.map(([sys, n]) => <Chip key={sys} tone={systemTone(sys)}>{sys} <span className="num opacity-70">{n}</span></Chip>)}
        {cited.size > 0 && <Chip tone="threat">{cited.size} linked by SUTRA</Chip>}
      </div>
      <div className="max-h-[560px] flex-1 overflow-y-auto border-t border-line px-3 py-2" aria-live="off">
        {!list.length && (
          <div className="px-2 py-8 text-center text-[12.5px] text-muted">
            <p className="font-medium text-ink">Nothing has happened in the bank yet.</p>
            <p className="mx-auto mt-1 max-w-[42ch]">Open Kestrel Bank, sign in as a member of staff or a customer, and act. Each action appears here within a few seconds.</p>
          </div>
        )}
        {[...list].reverse().map((r) => <RowItem key={r.seq} r={r} cite={cited.get(r.ref)} enter={false} />)}
      </div>
    </Panel>
  );
}

// ── processing: every engine, with real timings ─────────────────────────────

function EnginePanel({ st, run }: { st: LiveStatus; run: RunState }) {
  const stages = run.stages.length ? run.stages : st.stages;
  // seconds each stage took: the gap between its finish and the previous finish
  const took: Record<string, number | null> = {};
  let last = 0;
  for (const s of stages) {
    const p = run.progress[s.key];
    took[s.key] = p?.status === "done" && p.elapsed != null ? p.elapsed - last : null;
    if (p?.status === "done" && p.elapsed != null) last = p.elapsed;
  }
  return (
    <Panel className="flex flex-col">
      <PanelHead eyebrow="Processing · same code as the scheduled job" title="Every engine, for real" />
      <ol className="space-y-1.5 px-4 pb-3">
        {stages.map((s, i) => {
          const p = run.progress[s.key];
          const secs = took[s.key];
          const state = p?.status ?? "pending";
          return (
            <motion.li key={s.key} layout="position"
              className={cn("rounded-lg border px-3 py-2 transition-colors", state === "running" ? "border-ai/40 bg-ai-soft/50" : state === "done" ? "border-line bg-panel" : "border-dashed border-line")}>
              <div className="flex items-center gap-2.5">
                <span className={cn("grid size-6 shrink-0 place-items-center rounded-full text-[11px] num",
                  state === "done" ? "bg-ok-soft text-ok" : state === "running" ? "bg-ai text-on-primary" : "border border-line text-faint")}>
                  {state === "done" ? <Check size={13} /> : state === "running" ? <Loader2 size={13} className="animate-spin" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={cn("text-[13px] font-semibold", state === "pending" ? "text-muted" : "text-ink")}>{s.label}</span>
                    {secs != null && <span className="num text-[11px] text-faint">{secs < 0.05 ? "<0.1" : secs.toFixed(1)} s</span>}
                  </div>
                  <p className="text-[11.5px] leading-snug text-muted">{p?.detail ?? s.what}</p>
                </div>
              </div>
            </motion.li>
          );
        })}
      </ol>
      <div className="mt-auto border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">
        <Gauge size={12} className="mr-1 inline" /> Re-reads all 90 days every run — no shortcut for the demo. In production the same
        pipeline runs every 15 minutes as a Kubernetes CronJob; alert IDs, triage state and open cases survive each run.
      </div>
    </Panel>
  );
}

// ── output: what SUTRA concluded ────────────────────────────────────────────

function OutputPanel({ run, mode, played, canOpen, onOpened }: {
  run: RunState; mode: Mode; played: boolean; canOpen: boolean; onOpened: (alertId: string) => void;
}) {
  const fresh = run.alerts.filter((a) => a.new);
  const updated = run.alerts.filter((a) => !a.new);
  const verdict = run.kind === "feed" ? run.result?.verdict : null;
  const waiting = run.kind !== "reset" && !fresh.length && !verdict;

  return (
    <div className="flex flex-col gap-4">
      {run.kind === "reset" ? <ResetCard run={run} mode={mode} />
        : waiting ? <WaitingCard run={run} mode={mode} played={played} /> : null}
      {verdict && <VerdictBanner v={verdict} mode={mode} />}

      <AnimatePresence>
        {fresh.map((a) => <NewAlert key={a.id} a={a} mode={mode} canOpen={canOpen} onOpened={onOpened} />)}
      </AnimatePresence>

      {updated.length > 0 && (
        <Panel>
          <PanelHead eyebrow={`Existing alerts that now cite ${mode === "evening" ? "tonight" : SOURCE[mode]}`}
            title={`${updated.length} updated, same IDs`} />
          <div className="space-y-1.5 px-4 pb-4">
            {updated.map((a) => {
              const added = a.links.filter((l) => l.live);
              return (
                <div key={a.id} className="rounded-lg border border-line p-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="num text-[12px] font-semibold text-ink">{a.id}</span>
                    <PriorityPill p={a.priority} />
                    <TypologyChip t={a.typology} label={a.typology_label} />
                  </div>
                  <p className="mt-1 text-[12px] text-ink-2">{added.map((l) => `${l.code} ${l.title} — ${l.detail}`).join(" · ") || "Evidence now includes these rows"}</p>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      {run.alibi.length > 0 && <AlibiPanel rows={run.alibi} mode={mode} />}
      {run.phase === "done" && run.signals.length > 0 && <SignalsPanel signals={run.signals} mode={mode} />}
      {run.phase === "done" && run.kind === "feed" && run.result?.truth && <TruthPanel run={run} />}
    </div>
  );
}

function ResetCard({ run, mode }: { run: RunState; mode: Mode }) {
  const done = run.phase === "done";
  return (
    <Panel className="p-5">
      <div className="eyebrow mb-1">{mode === "yours" ? "Undo your input" : mode === "bank" ? "Undo bank activity" : "Reset"}</div>
      <p className="display text-[18px] font-semibold text-ink">
        {mode === "yours" ? (done ? "Your input is out of the bank again" : "Taking your rows back out…")
          : mode === "bank" ? (done ? "Kestrel Bank is back to how it was" : "Undoing what was done in Kestrel Bank…")
            : (done ? "Back to the start of the evening" : "Undoing tonight…")}
      </p>
      <p className="mt-1 text-[12.5px] text-muted">
        {run.result?.undone != null ? `${run.result.undone} rows removed, balances and master data restored, detection re-run on the history. ` : ""}
        Alerts that existed before keep their IDs and any case opened on them.
      </p>
      {run.result?.scenarios && <p className="mt-2 text-[12.5px] text-ok"><CheckCircle2 size={13} className="mr-1 inline" />{run.result.scenarios.passed}/{run.result.scenarios.total} scenario checks pass</p>}
    </Panel>
  );
}

function WaitingCard({ run, mode, played }: { run: RunState; mode: Mode; played: boolean }) {
  const title = mode === "bank"
    ? { idle: "Waiting for a detection run", detecting: "SUTRA is re-reading all 90 days, the bank's new records included…" }[run.phase as "idle"] ?? "Working…"
    : mode === "yours"
    ? { idle: "Nothing sent yet", streaming: "Your rows are reaching the bank's systems…", detecting: "SUTRA is re-reading all 90 days, your rows included…" }[run.phase as "idle"] ?? "Waiting"
    : run.phase === "idle" ? (played ? "Tonight's feed is already in Loom" : "No alert yet — nothing has happened")
      : run.phase === "streaming" ? "The evening is coming in…" : run.phase === "detecting" ? "Following the thread…"
        : run.phase === "done" ? "No new alert tonight" : "Waiting";
  const body = mode === "bank"
    ? "Use Kestrel Bank in another window, then press Run detection now. In production this happens every 15 minutes on its own."
    : mode === "yours"
    ? "SUTRA sees only the rows the bank's systems record. It will say whether your actions add up to a chain from a staff privilege to money leaving the bank — and why."
    : run.phase === "idle" ? (played ? "Its alerts are in the Signal Desk. Reset the demo to watch the evening arrive again."
      : "Alerts appear here only when detection finds a chain from a staff privilege to money leaving the bank.")
      : "SUTRA will not raise anything until a staff action, a takeover and a payout are connected by records.";
  return (
    <Panel className="grid min-h-[260px] place-items-center p-6 text-center">
      <div>
        <div className="mx-auto mb-3 grid size-12 place-items-center rounded-2xl bg-panel-2 text-faint"><ShieldCheck size={22} /></div>
        <p className="display text-[17px] font-semibold text-ink">{title}</p>
        <p className="mx-auto mt-1 max-w-[46ch] text-[12.5px] text-muted">{body}</p>
      </div>
    </Panel>
  );
}

const VERDICT: Record<LiveVerdict["outcome"], { text: string; ring: string; icon: LucideIcon; label: string }> = {
  alert: { text: "text-threat", ring: "ring-threat/30", icon: Siren, label: "Caught" },
  watch: { text: "text-amber", ring: "ring-amber/30", icon: Eye, label: "On the watch list" },
  updated: { text: "text-ai", ring: "ring-ai/30", icon: Link2, label: "Linked to an existing alert" },
  explained: { text: "text-ok", ring: "ring-ok/30", icon: ShieldCheck, label: "Explained — no alert" },
  signals: { text: "text-info", ring: "ring-info/30", icon: Activity, label: "Signals only — no alert" },
};

function VerdictBanner({ v, mode }: { v: LiveVerdict; mode: Mode }) {
  const s = VERDICT[v.outcome];
  const Icon = s.icon;
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: "spring", stiffness: 260, damping: 24 }}>
      <Panel className={cn("p-5 ring-1", s.ring)}>
        <div className={cn("eyebrow flex items-center gap-1.5", s.text)}><Icon size={13} /> {s.label} · SUTRA&apos;s verdict on {mode === "bank" ? "what happened in Kestrel Bank" : SOURCE[mode]}</div>
        <p className="display mt-1.5 text-[19px] font-semibold leading-snug text-ink">{v.headline}</p>
        <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{v.detail}</p>
      </Panel>
    </motion.div>
  );
}

function NewAlert({ a, mode, canOpen, onOpened }: { a: LiveAlert; mode: Mode; canOpen: boolean; onOpened: (alertId: string) => void }) {
  const open = useOpenCase();
  const login = a.links.find((l) => l.code === "E1");
  const payout = a.links.find((l) => l.code === "E5");
  const gap = login && payout ? (+new Date(payout.t) - +new Date(login.t)) / 1000 : null;
  return (
    <motion.div initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 24 }}>
      <Panel className="overflow-hidden ring-1 ring-threat/30">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-threat-soft/60 px-5 py-2.5">
          <span className="relative flex size-2.5"><span className="absolute inset-0 animate-ping rounded-full bg-threat opacity-60" /><span className="relative size-2.5 rounded-full bg-threat" /></span>
          <span className="text-[12px] font-semibold text-threat">New alert from {SOURCE[mode]}</span>
          <span className="num ml-auto text-[12px] font-semibold text-ink">{a.id}</span>
        </div>
        <div className="px-5 pt-4">
          <div className="flex flex-wrap items-center gap-1.5"><PriorityPill p={a.priority} /><TypologyChip t={a.typology} label={a.typology_label} /></div>
          <p className="display mt-2 text-[19px] font-semibold leading-snug text-ink">{a.claim}</p>
          <div className="mt-3 grid grid-cols-3 gap-3">
            <Metric label="at risk" value={<CountUp value={a.amount} format={lakh} />} tone="text-threat" />
            <Metric label="login → money out" value={gap != null ? duration(gap) : "—"} />
            <Metric label="staff → account" value={<span className="num block text-[14px] leading-tight">{a.employee_id ?? "—"}<span className="block text-[12.5px] font-medium text-muted">{a.account_id ?? "—"}</span></span>} />
          </div>
        </div>
        <ol className="mx-5 mt-4 space-y-1 border-l border-line pl-4">
          {a.links.map((l, i) => <ChainStep key={`${l.code}-${i}`} l={l} i={i} />)}
        </ol>
        <div className="mt-4 flex flex-wrap gap-2 border-t border-line px-5 py-3">
          <ButtonLink size="sm" variant="ai" href={`/council/${a.id}`}><Landmark size={13} /> Convene the Council</ButtonLink>
          <ButtonLink size="sm" href={`/replay?alert=${a.id}`}><TimerReset size={13} /> Replay the evening</ButtonLink>
          <ButtonLink size="sm" href={`/evidence/arguments?alert=${a.id}`}><Scale size={13} /> Prosecution &amp; defence</ButtonLink>
          <ButtonLink size="sm" href={`/controls?alert=${a.id}`}><FlaskConical size={13} /> Which control stops it</ButtonLink>
          {canOpen && (
            <Button size="sm" variant="primary" disabled={open.isPending}
              onClick={() => open.mutate(a.id, { onSuccess: () => onOpened(a.id) })}>
              Open case <ArrowRight size={13} />
            </Button>
          )}
        </div>
        {open.error && <p className="px-5 pb-3 text-[12px] text-threat">{open.error.message}</p>}
      </Panel>
    </motion.div>
  );
}

function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg bg-panel-2 px-3 py-2">
      <div className={cn("num text-[18px] font-semibold leading-tight text-ink", tone)}>{value}</div>
      <div className="mt-0.5 text-[10.5px] uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}

function ChainStep({ l, i }: { l: LiveLink; i: number }) {
  return (
    <motion.li initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.15 + i * 0.07 }} className="relative py-0.5">
      <span className={cn("absolute -left-[21px] top-2 size-2.5 rounded-full border-2 border-panel", l.live ? "bg-threat" : "bg-faint")} />
      <div className="flex items-baseline gap-2">
        <Chip tone={LANE_TONE[l.lane] ?? "faint"} className="!px-1.5 !py-0 !text-[10.5px] num">{l.code}</Chip>
        <span className="text-[12.5px] font-medium text-ink">{l.title}</span>
        <span className="num ml-auto shrink-0 text-[11px] text-faint">{dayMonth(l.t)} {hhmm(l.t)}</span>
      </div>
      <p className="ml-[2px] text-[11.5px] leading-snug text-muted">{l.detail}</p>
    </motion.li>
  );
}

type AlibiState = "explained" | "partly explained" | "unexplained";

function AlibiPanel({ rows, mode }: { rows: LiveAlibi[]; mode: Mode }) {
  const byEmp = new Map<string, LiveAlibi[]>();
  for (const r of rows) byEmp.set(r.employee_id, [...(byEmp.get(r.employee_id) ?? []), r]);
  const groups = [...byEmp.entries()].map(([emp, list]) => {
    const templates = new Map<string, { ok: boolean; ref: string | null }>();
    for (const r of list) for (const c of r.checked) {
      const prev = templates.get(c.template);
      if (!prev || (!prev.ok && c.ok)) templates.set(c.template, { ok: c.ok, ref: c.ref });
    }
    const found = [...templates.entries()].filter(([, v]) => v.ok).map(([t]) => REASON[t] ?? t.toLowerCase());
    const state: AlibiState = list.every((r) => r.verdict === "EXPLAINED") ? "explained" : found.length ? "partly explained" : "unexplained";
    return { emp, list, templates, found, state };
  }).sort((a, b) => Number(a.state === "explained") - Number(b.state === "explained"));
  const TONE: Record<AlibiState, Tone> = { explained: "ok", "partly explained": "amber", unexplained: "threat" };
  return (
    <Panel>
      <PanelHead eyebrow={`Alibi · staff accesses in ${SOURCE[mode]}`} title="Was there a legitimate reason?" />
      <div className="grid gap-2.5 px-4 pb-4 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        {groups.map(({ emp, list, templates, found, state }) => (
          <motion.div key={emp} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
            className={cn("rounded-lg border p-3", state === "explained" ? "border-ok/30 bg-ok-soft/40"
              : state === "unexplained" ? "border-threat/30 bg-threat-soft/40" : "border-amber/30 bg-amber-soft/40")}>
            <div className="flex items-center gap-2">
              <span className="num whitespace-nowrap text-[12.5px] font-semibold text-ink">{emp}</span>
              <Chip tone={TONE[state]}>{state}</Chip>
              <span className="num ml-auto whitespace-nowrap text-[11px] text-faint">{list.length} access{list.length === 1 ? "" : "es"}</span>
            </div>
            <p className="mt-1 text-[11.5px] text-muted">
              {found.length} of {templates.size} reasons found{found.length ? ` — ${found.join(", ")}` : " — no ticket, roster, queue, portfolio or customer contact"}
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {[...templates.entries()].map(([t, v]) => (
                <span key={t} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium",
                  v.ok ? "bg-ok-soft text-ok" : "bg-panel-2 text-faint line-through decoration-faint/60")}>
                  {v.ok ? <Check size={10} /> : <X size={10} />}{REASON[t] ?? t.toLowerCase()}{v.ok && v.ref ? ` · ${v.ref}` : ""}
                </span>
              ))}
            </div>
            {list.some((r) => r.action) && (
              <ul className="mt-2 space-y-0.5 border-t border-line/70 pt-1.5">
                {list.map((r) => (
                  <li key={r.ref} className="flex items-center gap-2 text-[11px]">
                    <span className="num text-faint">{hhmm(r.t)}</span>
                    <span className="text-ink-2">{(r.action ?? "").replaceAll("_", " ").toLowerCase()}</span>
                    <span className={cn("ml-auto font-medium", r.verdict === "EXPLAINED" ? "text-ok" : r.verdict === "UNEXPLAINED" ? "text-threat" : "text-amber")}>
                      {r.verdict.toLowerCase()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </motion.div>
        ))}
      </div>
    </Panel>
  );
}

function SignalsPanel({ signals, mode }: { signals: LiveSignal[]; mode: Mode }) {
  const [all, setAll] = useState(false);
  const seen = new Set<string>();
  const uniq = signals.filter((s) => {
    const k = `${s.detector}|${s.summary}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  const detectors = new Set(uniq.map((s) => s.detector));
  const shown = all ? uniq : uniq.slice(0, 8);
  return (
    <Panel>
      <PanelHead eyebrow={`Signals · ${uniq.length} from ${detectors.size} detector${detectors.size === 1 ? "" : "s"}`}
        title={`What ${SOURCE[mode]} set off`} />
      <ul className="space-y-1.5 px-4 pb-2">
        {shown.map((s) => (
          <li key={`${s.detector}|${s.summary}`} className="flex items-start gap-2 text-[12px]">
            <Chip tone={FAMILY_TONE[s.family] ?? "faint"} mono className="mt-0.5 shrink-0">{s.detector}</Chip>
            <span className="leading-snug"><b className="font-medium text-ink">{s.name}</b> <span className="text-muted">— {s.summary}</span></span>
          </li>
        ))}
      </ul>
      {uniq.length > 8 && (
        <button onClick={() => setAll((v) => !v)} className="mx-4 mb-2 text-[12px] font-medium text-info hover:underline">
          {all ? "Show fewer" : `Show all ${uniq.length}`}
        </button>
      )}
      <p className="border-t border-line px-4 py-2.5 text-[11.5px] leading-relaxed text-faint">
        A signal on its own never raises an alert. Needle has to connect a staff privilege to money leaving the bank, and Brief has to grade the evidence.
      </p>
    </Panel>
  );
}

function TruthPanel({ run }: { run: RunState }) {
  const t = run.result?.truth ?? {};
  const rows: [Strand, string][] = [["attack", "Insider takeover (injected)"], ["camp", "Pension camp (legitimate)"], ["routine", "Routine customer traffic"]];
  const legit = (t.camp?.events ?? 0) + (t.routine?.events ?? 0);
  const falseHits = (t.camp?.cited ?? 0) + (t.routine?.cited ?? 0);
  return (
    <Panel>
      <PanelHead eyebrow={`Ground truth · ${legit} legitimate rows tonight`} title={falseHits === 0 ? "No false alarm" : `${falseHits} legitimate rows cited`}
        right={run.result?.scenarios && <Chip tone={run.result.scenarios.passed === run.result.scenarios.total ? "ok" : "threat"}>
          <CheckCircle2 size={11} /> {run.result.scenarios.passed}/{run.result.scenarios.total} scenario checks</Chip>} />
      <div className="space-y-2.5 px-5 pb-4">
        {rows.map(([k, label]) => {
          const v = t[k];
          if (!v) return null;
          const share = v.events ? v.cited / v.events : 0;
          return (
            <div key={k}>
              <div className="mb-1 flex items-baseline justify-between text-[12px]">
                <span className="text-ink-2">{label}</span>
                <span className="num text-muted"><b className="text-ink">{v.cited}</b> of {v.events} rows cited by a queued alert</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
                <motion.div className={cn("h-full rounded-full", k === "attack" ? "bg-threat" : "bg-ok")} initial={{ width: 0 }} animate={{ width: `${share * 100}%` }} transition={{ duration: 0.6 }} />
              </div>
            </div>
          );
        })}
        <p className="pt-1 text-[11.5px] leading-relaxed text-faint">
          Labels come from the simulator, never from SUTRA. The attack rows no alert cites are context around the chain —
          a customer search, logins, the new device&apos;s record, small ATM withdrawals. Use “Reveal ground truth” on the feed
          to see every row&apos;s label beside what SUTRA linked.
        </p>
      </div>
    </Panel>
  );
}
