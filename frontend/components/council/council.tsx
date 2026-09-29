"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  Check,
  ClipboardList,
  Coins,
  DatabaseZap,
  Gavel,
  Landmark,
  Link2,
  Loader2,
  Receipt,
  Scale,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { EvidenceChip } from "@/components/brief/evidence";
import { Chip, type Tone } from "@/components/ui/primitives";
import { cn } from "@/lib/format";
import type { Council, CouncilAgent, CouncilClaim, CouncilEntry, EvidenceItem } from "@/lib/types";

// ── Identity ───────────────────────────────────────────────────────────────

export const AGENT_ICON: Record<string, LucideIcon> = {
  link: Link2, coins: Coins, user: UserRound, receipt: Receipt, scale: Scale,
  gavel: Gavel, shield: ShieldCheck, clipboard: ClipboardList, landmark: Landmark,
};

const STANCE: Record<string, { tone: Tone; ring: string; text: string; bg: string; dot: string; label: string }> = {
  PROSECUTION: { tone: "threat", ring: "ring-threat/60", text: "text-threat", bg: "bg-threat-soft", dot: "bg-threat", label: "Argues the case" },
  DEFENCE: { tone: "info", ring: "ring-info/60", text: "text-info", bg: "bg-info-soft", dot: "bg-info", label: "Argues the innocent reading" },
  NEUTRAL: { tone: "ai", ring: "ring-ai/60", text: "text-ai", bg: "bg-ai-soft", dot: "bg-ai", label: "Neutral finder" },
};
export const stanceOf = (s: string) => STANCE[s] ?? STANCE.NEUTRAL;

export const STATUS_TONE: Record<string, Tone> = {
  SUPPORTED: "ok", CONTESTED: "amber", UNEXPLAINED: "threat", MISSING: "faint", CONTRADICTORY: "threat",
  RETRIEVED: "ok", NOT_FOUND: "amber", NOT_INGESTED: "faint", REFUTED: "faint",
};
const STATUS_LABEL: Record<string, string> = { NOT_FOUND: "nothing found", NOT_INGESTED: "not ingested" };

const KIND: Record<CouncilEntry["kind"], { tone: Tone; label: string }> = {
  POSITION: { tone: "faint", label: "Position" },
  CHALLENGE: { tone: "amber", label: "Challenge" },
  RESPONSE: { tone: "info", label: "Response" },
  REQUEST: { tone: "ai", label: "Evidence request" },
  RETRIEVAL: { tone: "ai", label: "Retrieval" },
  UPDATE: { tone: "faint", label: "Update" },
  RULING: { tone: "ink", label: "Ruling" },
};

export function AgentAvatar({ agent, size = 32, active = false }: { agent: Pick<CouncilAgent, "icon" | "stance">; size?: number; active?: boolean }) {
  const Icon = AGENT_ICON[agent.icon] ?? UserRound;
  const s = stanceOf(agent.stance);
  return (
    <span
      className={cn("relative grid shrink-0 place-items-center rounded-full border border-line-strong", s.bg, s.text, active && "ring-2", active && s.ring)}
      style={{ width: size, height: size }}
    >
      <Icon size={Math.round(size * 0.48)} />
    </span>
  );
}

// ── Chamber: agents seated round the moderator ─────────────────────────────

// Prosecution-leaning seats on the left, defence directly opposite on the right.
const SEAT_ANGLE: Record<string, number> = {
  defence: 0, evidence: 45, control: 90, money: 135, prosecution: 180, chain: 225, insider: 270, alibi: 315,
};

function seatXY(id: string, i: number): [number, number] {
  const deg = SEAT_ANGLE[id] ?? i * 45;
  const r = (deg * Math.PI) / 180;
  return [50 + 38 * Math.cos(r), 50 + 36 * Math.sin(r)];
}

export function Chamber({ c, current, verdictShown, onPick, picked }: {
  c: Council;
  current: CouncilEntry | null;
  verdictShown: boolean;
  onPick: (id: string | null) => void;
  picked: string | null;
}) {
  const pos = new Map(c.agents.map((a, i) => [a.id, seatXY(a.id, i)] as const));
  pos.set("moderator", [50, 50]);
  const from = current ? pos.get(current.speaker) : undefined;
  const to = current?.target ? pos.get(current.target) : undefined;
  const dissenters = new Set(c.consensus.dissent.map((d) => d.agent));
  const speaking = current?.speaker;

  return (
    <div className="@container relative h-[clamp(340px,34vw,500px)] w-full overflow-hidden rounded-lg border border-line bg-[radial-gradient(ellipse_at_center,var(--panel-2),transparent_70%)]">
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        <ellipse cx="50" cy="50" rx="38" ry="36" fill="none" stroke="currentColor" className="text-line" strokeDasharray="0.6 1.2" vectorEffect="non-scaling-stroke" />
        <ellipse cx="50" cy="50" rx="17" ry="15" fill="none" stroke="currentColor" className="text-line" vectorEffect="non-scaling-stroke" />
        <AnimatePresence>
          {from && to && (
            <motion.line
              key={`${current?.speaker}-${current?.target}-${current?.text.slice(0, 12)}`}
              x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]}
              stroke="currentColor"
              className={current?.kind === "CHALLENGE" ? "text-amber" : current?.kind === "RETRIEVAL" ? "text-ai" : "text-info"}
              strokeWidth={2}
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            />
          )}
        </AnimatePresence>
      </svg>

      {/* Moderator */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
        <motion.div
          animate={speaking === "moderator" ? { scale: 1.08 } : { scale: 1 }}
          className={cn("mx-auto grid size-14 place-items-center rounded-full border border-line-strong bg-raised text-ink shadow-lg",
            speaking === "moderator" && "ring-2 ring-ink/50")}
        >
          <Landmark size={24} />
        </motion.div>
        <div className="mt-1.5 text-[11.5px] font-semibold text-ink">{c.moderator.name}</div>
        <div className="num text-[10px] text-faint">{verdictShown ? "ruling recorded" : current ? `round ${current.round}` : "convening"}</div>
      </div>

      {c.agents.map((a, i) => {
        const [x, y] = pos.get(a.id)!;
        const s = stanceOf(a.stance);
        const active = speaking === a.id;
        const targeted = current?.target === a.id;
        return (
          <motion.button
            key={a.id}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: active ? 1.06 : 1 }}
            transition={{ delay: i * 0.05, type: "spring", stiffness: 260, damping: 22 }}
            onClick={() => onPick(picked === a.id ? null : a.id)}
            style={{ left: `${x}%`, top: `${y}%` }}
            className={cn(
              "absolute w-[clamp(100px,25%,172px)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border bg-panel px-2 py-1.5 text-left shadow-md transition-colors @[560px]:px-2.5 @[560px]:py-2",
              active ? cn("border-transparent ring-2", s.ring) : targeted ? "border-amber/60" : picked === a.id ? "border-ink/60" : "border-line hover:border-line-strong",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="hidden @[520px]:block"><AgentAvatar agent={a} size={26} active={active} /></span>
              <div className="min-w-0">
                <div className="line-clamp-2 text-[11px] font-semibold leading-tight text-ink">{a.name}</div>
                <div className={cn("text-[10px] leading-tight", s.text)}>{a.strength}</div>
              </div>
            </div>
            {verdictShown && (
              <motion.div initial={{ opacity: 0, y: 3 }} animate={{ opacity: 1, y: 0 }} className="mt-1.5">
                {dissenters.has(a.id)
                  ? <Chip tone="amber">dissent</Chip>
                  : <Chip tone="ok"><Check size={10} /> agrees</Chip>}
              </motion.div>
            )}
            {active && (
              <span className="absolute -right-1 -top-1 flex size-3">
                <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", s.dot)} />
                <span className={cn("relative size-3 rounded-full border-2 border-panel", s.dot)} />
              </span>
            )}
          </motion.button>
        );
      })}
    </div>
  );
}

// ── Transcript entry ───────────────────────────────────────────────────────

export function RetrievalStatus({ status, animate }: { status: string; animate: boolean }) {
  const reduce = useReducedMotion();
  const [done, setDone] = useState(!animate || !!reduce);
  useEffect(() => {
    if (done) return;
    const t = setTimeout(() => setDone(true), 750);
    return () => clearTimeout(t);
  }, [done]);
  if (!done) return <Chip tone="ai"><Loader2 size={10} className="animate-spin" /> querying</Chip>;
  return (
    <motion.span initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}>
      <Chip tone={STATUS_TONE[status] ?? "faint"}>{STATUS_LABEL[status] ?? status.toLowerCase()}</Chip>
    </motion.span>
  );
}

export function Entry({ e, c, pool, fresh }: { e: CouncilEntry; c: Council; pool: EvidenceItem[]; fresh: boolean }) {
  const byId = (id: string | null) => (id === "moderator" ? c.moderator : c.agents.find((a) => a.id === id));
  const who = byId(e.speaker);
  const target = byId(e.target);
  const k = KIND[e.kind];

  if (e.kind === "RULING") {
    return (
      <div className="my-2 rounded-lg border border-line-strong bg-raised px-4 py-3">
        <div className="mb-1 flex items-center gap-2"><Gavel size={14} className="text-ink" /><span className="eyebrow !text-ink">Moderator ruling</span></div>
        <p className="text-[13px] leading-relaxed text-ink">{e.text}</p>
      </div>
    );
  }

  const isRetrieval = e.kind === "RETRIEVAL";
  return (
    <div className={cn("flex gap-3 py-2.5", isRetrieval && "ml-10 rounded-lg border border-ai/25 bg-ai-soft/40 px-3")}>
      {!isRetrieval && who && <AgentAvatar agent={{ icon: who.icon, stance: (who as { stance?: CouncilAgent["stance"] }).stance ?? "NEUTRAL" }} size={30} />}
      {isRetrieval && <DatabaseZap size={16} className="mt-0.5 shrink-0 text-ai" />}
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px]">
          <span className="font-semibold text-ink">{who?.name ?? e.speaker}</span>
          {target && (<><ArrowRight size={11} className="text-faint" /><span className="text-muted">{target.name}</span></>)}
          <Chip tone={k.tone}>{k.label}</Chip>
          {e.claim && <Chip tone="faint">{e.claim}</Chip>}
          {e.status && (isRetrieval
            ? <RetrievalStatus status={e.status} animate={fresh} />
            : <Chip tone={STATUS_TONE[e.status] ?? "faint"}>{STATUS_LABEL[e.status] ?? e.status.toLowerCase()}</Chip>)}
        </div>
        <p className={cn("text-[12.5px] leading-relaxed", e.kind === "CHALLENGE" ? "text-ink italic" : "text-ink-2")}>
          {e.kind === "CHALLENGE" ? `“${e.text}”` : e.text}
        </p>
        {e.evidence.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">{e.evidence.map((code) => <EvidenceChip key={code} code={code} pool={pool} />)}</div>
        )}
      </div>
    </div>
  );
}

// ── Claims ledger ──────────────────────────────────────────────────────────

const TALLY_ORDER = ["SUPPORTED", "CONTESTED", "UNEXPLAINED", "MISSING", "CONTRADICTORY"] as const;
const BAR: Record<string, string> = { SUPPORTED: "bg-ok", CONTESTED: "bg-amber", UNEXPLAINED: "bg-threat", MISSING: "bg-faint", CONTRADICTORY: "bg-threat/60" };

export function TallyBar({ tally }: { tally: Record<string, number> }) {
  const total = TALLY_ORDER.reduce((s, k) => s + (tally[k] ?? 0), 0) || 1;
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-line">
        {TALLY_ORDER.map((k, i) => (
          <motion.span key={k} className={cn("h-full", BAR[k])}
            initial={{ width: 0 }} animate={{ width: `${((tally[k] ?? 0) / total) * 100}%` }} transition={{ delay: 0.1 + i * 0.08, duration: 0.6 }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
        {TALLY_ORDER.map((k) => (
          <span key={k} className="flex items-center gap-1.5 text-muted">
            <span className={cn("size-2 rounded-sm", BAR[k])} />{k.toLowerCase()} <b className="num text-ink">{tally[k] ?? 0}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export function ClaimRow({ cl, c, pool }: { cl: CouncilClaim; c: Council; pool: EvidenceItem[] }) {
  const owner = c.agents.find((a) => a.id === cl.owner);
  return (
    <div className="border-b border-line py-3 last:border-0">
      <div className="flex items-start gap-2.5">
        {owner && <AgentAvatar agent={owner} size={24} />}
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-1.5">
            <Chip tone="faint">{cl.id}</Chip>
            <Chip tone={STATUS_TONE[cl.status]}>{cl.status.toLowerCase()}</Chip>
            <span className="truncate text-[11px] text-muted">{owner?.name}</span>
          </div>
          <p className="text-[12.5px] leading-snug text-ink">{cl.text}</p>
          <p className="mt-1 text-[11.5px] text-muted">{cl.interpretation}</p>
          {cl.counterargument && (
            <p className="mt-1 rounded-md border border-amber/25 bg-amber-soft px-2 py-1 text-[11.5px] text-amber">Counter: {cl.counterargument}</p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1">
            {cl.evidence.slice(0, 8).map((code) => <EvidenceChip key={code} code={code} pool={pool} />)}
            {cl.evidence.length > 8 && <span className="text-[10.5px] text-faint">+{cl.evidence.length - 8}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
