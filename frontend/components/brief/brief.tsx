"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, CircleDashed, CircleHelp, Loader2, Minus, Scale, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Chip, LevelBar, Tip } from "@/components/ui/primitives";
import { cn, pct } from "@/lib/format";
import type { AlertDetail, AlibiCard, EvidenceItem } from "@/lib/types";

import { EvidenceChip, Grade } from "./evidence";

// ── Why suspicious? ─────────────────────────────────────────────────────────

export function WhySuspicious({ a }: { a: AlertDetail }) {
  const dims = a.dims;
  const high = dims.filter((d) => d.level === "HIGH").length;
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-line bg-panel-2 p-3">
        <div className="eyebrow mb-1">Priority rule that fired</div>
        <p className="text-[12.5px] leading-relaxed text-ink">{a.lattice_rule}</p>
        <p className="mt-1.5 text-[11.5px] text-muted">No weighted score — priority comes from readable rules over the {dims.length} dimensions below ({high} High).</p>
      </div>
      {dims.map((d, i) => (
        <motion.div key={d.key} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
          className="rounded-lg border border-line px-3 py-2.5">
          <div className="flex items-center gap-3">
            <span className="w-[128px] shrink-0 text-[12.5px] font-semibold text-ink">{d.label}</span>
            <LevelBar level={d.level} />
            <Chip tone={d.level === "HIGH" ? "threat" : d.level === "ELEVATED" ? "amber" : d.level === "LOW" ? "ok" : "faint"}>{d.level}</Chip>
          </div>
          <p className="mt-1.5 text-[12px] leading-snug text-ink-2">{d.summary}</p>
          {(d.supporting.length > 0 || d.contradicting.length > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {d.supporting.slice(0, 6).map((c) => <EvidenceChip key={c} code={c} pool={a.evidence} />)}
              {d.contradicting.length > 0 && <span className="mx-1 text-[10.5px] text-ok">against</span>}
              {d.contradicting.map((c) => <EvidenceChip key={c} code={c} pool={a.evidence} className="!border-ok/40 !text-ok" />)}
            </div>
          )}
        </motion.div>
      ))}
      {a.contributions?.length > 0 && <Contributions a={a} />}
    </div>
  );
}

function Contributions({ a }: { a: AlertDetail }) {
  const top = a.contributions.slice(0, 7);
  const max = Math.max(...top.map((c) => Math.abs(c.contribution)), 0.01);
  return (
    <div className="rounded-lg border border-ai/25 bg-ai-soft/40 p-3">
      <div className="mb-1 flex items-center justify-between">
        <span className="eyebrow !text-ai">M5 chain classifier · exact contributions</span>
        {a.classifier_p != null && <Chip tone="ai">p {a.classifier_p.toFixed(2)} · synthetic calibration</Chip>}
      </div>
      <p className="mb-2 text-[11px] text-muted">Standardised logistic regression: each bar is coefficient × value — the whole decision, not an approximation.</p>
      {top.map((c) => (
        <div key={c.feature} className="grid grid-cols-[1fr_120px] items-center gap-2 py-[3px]">
          <span className="truncate text-[11.5px] text-ink-2">{c.label}</span>
          <div className="relative h-2.5">
            <div className="absolute left-1/2 top-0 h-full w-px bg-line-strong" />
            <motion.div initial={{ width: 0 }} animate={{ width: `${(Math.abs(c.contribution) / max) * 50}%` }}
              className={cn("absolute top-0 h-full rounded-sm", c.contribution >= 0 ? "left-1/2 bg-threat" : "right-1/2 bg-ok")} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Prosecution & Defence ───────────────────────────────────────────────────

export function ProsecutionDefence({ a }: { a: AlertDetail }) {
  const arg = a.argument;
  const defenceEv = a.evidence.filter((e) => e.rebuts.length > 0);
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-line-strong bg-panel-2 p-3">
        <div className="eyebrow mb-1">Claim</div>
        <p className="display text-[15px] font-semibold leading-snug text-ink">{arg.claim}</p>
        <p className="mt-1.5 text-[11.5px] text-amber">{arg.attribution.note}</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <div className="eyebrow mb-2 flex items-center gap-1.5 !text-threat"><TriangleAlert size={12} /> Prosecution · grounds</div>
          <ul className="space-y-1.5">
            {arg.grounds.map((g, i) => (
              <motion.li key={g.code} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
                className="flex gap-2 rounded-md border border-threat/15 bg-threat-soft/40 px-2 py-1.5 text-[11.5px] leading-snug text-ink-2">
                <EvidenceChip code={g.code} pool={a.evidence} className="h-fit shrink-0" />
                <span>{g.text}</span>
              </motion.li>
            ))}
          </ul>
        </div>
        <div>
          <div className="eyebrow mb-2 flex items-center gap-1.5 !text-ok"><ShieldCheck size={12} /> Defence · explanations tested</div>
          <ul className="space-y-1.5">
            {arg.rebuttals.map((r, i) => (
              <motion.li key={r.hypothesis} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
                className={cn("rounded-md border px-2.5 py-2 text-[11.5px] leading-snug",
                  r.status === "open" ? "border-amber/40 bg-amber-soft/50" : r.status === "supported" ? "border-ok/40 bg-ok-soft/60" : "border-line bg-panel-2")}>
                <div className="flex items-center gap-2">
                  {r.status === "refuted" ? <X size={13} className="text-muted" /> : r.status === "supported" ? <Check size={13} className="text-ok" /> : <CircleHelp size={13} className="text-amber" />}
                  <span className="font-semibold text-ink">{r.hypothesis}</span>
                  <Chip tone={r.status === "open" ? "amber" : r.status === "supported" ? "ok" : "faint"} className="ml-auto">{r.status}</Chip>
                </div>
                <p className="mt-1 text-ink-2">{r.note}</p>
                {r.codes.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{r.codes.map((c) => <EvidenceChip key={c} code={c} pool={a.evidence} />)}</div>}
              </motion.li>
            ))}
            {defenceEv.map((e) => (
              <li key={e.code} className="flex gap-2 rounded-md border border-ok/25 bg-ok-soft/40 px-2 py-1.5 text-[11.5px] text-ink-2">
                <EvidenceChip code={e.code} pool={a.evidence} className="h-fit shrink-0" /> <span>{e.summary}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Box title="Warrant" icon={<Scale size={12} />}>{arg.warrant.text}</Box>
        <Box title="Backing">{arg.backing.join(" · ")}</Box>
        <Box title="Qualifier">{arg.qualifier.text}</Box>
      </div>
    </div>
  );
}

function Box({ title, children, icon }: { title: string; children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line p-2.5">
      <div className="eyebrow mb-1 flex items-center gap-1">{icon}{title}</div>
      <div className="text-[11.5px] leading-snug text-ink-2">{children}</div>
    </div>
  );
}

// ── Alibi resolution (animated) ─────────────────────────────────────────────

const TEMPLATE_LABEL: Record<string, string> = {
  TICKET: "Service ticket",
  PORTFOLIO: "Customer portfolio",
  QUEUE: "Workflow queue",
  INTERACTION: "Customer interaction",
  ROSTER: "Rostered shift",
};

export function AlibiResolution({ card, title, replayKey }: { card: AlibiCard; title?: string; replayKey?: string }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    setStep(0);
    const id = setInterval(() => setStep((s) => (s >= card.checked.length ? s : s + 1)), 380);
    return () => clearInterval(id);
  }, [card, replayKey]);
  const done = step >= card.checked.length;
  const found = card.checked.slice(0, step).filter((c) => c.ok).length;
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="eyebrow">{title ?? "Alibi check"}</span>
        <AnimatePresence mode="wait">
          {done ? (
            <motion.span key="v" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
              <Chip tone={card.verdict === "EXPLAINED" ? "ok" : card.verdict === "PARTIAL" ? "amber" : "threat"}>{card.verdict}</Chip>
            </motion.span>
          ) : (
            <motion.span key="s" className="flex items-center gap-1 text-[11px] text-muted"><Loader2 size={12} className="animate-spin" /> Searching…</motion.span>
          )}
        </AnimatePresence>
      </div>
      <div className="mb-2.5 flex items-center gap-2">
        <span className="display text-[20px] font-extrabold text-ink"><span className={cn(found === 0 && done ? "text-threat" : found >= 2 ? "text-ok" : "")}>{found}</span> / 5</span>
        <span className="text-[11.5px] text-muted">legitimate reasons found</span>
        <div className="ml-auto flex gap-1">
          {card.checked.map((c, i) => (
            <motion.span key={i} className={cn("h-2 w-6 rounded-full", i < step ? (c.ok ? "bg-ok" : "bg-threat/70") : "bg-line")}
              animate={{ opacity: i === step ? [0.3, 1, 0.3] : 1 }} transition={{ repeat: i === step ? Infinity : 0, duration: 0.8 }} />
          ))}
        </div>
      </div>
      <ul className="space-y-1">
        {card.checked.map((c, i) => (
          <li key={c.template} className="flex items-start gap-2 text-[11.5px]">
            <span className="mt-[1px] shrink-0">
              {i < step ? (c.ok ? <Check size={13} className="text-ok" /> : <X size={13} className="text-threat" />) : i === step ? <Loader2 size={13} className="animate-spin text-muted" /> : <CircleDashed size={13} className="text-faint" />}
            </span>
            <span className="w-[128px] shrink-0 font-medium text-ink">{TEMPLATE_LABEL[c.template] ?? c.template}</span>
            <span className={cn("text-muted", i >= step && "opacity-0")}>{c.note}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Missing evidence & completeness ─────────────────────────────────────────

const EXPECTED = [
  { system: "IAM", label: "IAM entitlements" },
  { system: "CBS app audit", label: "CBS access audit" },
  { system: "CBS", label: "CBS state changes & openings" },
  { system: "Payments switch", label: "Transactions" },
  { system: "HRMS", label: "HR roster" },
  { system: "Digital channel", label: "Digital sessions & devices" },
  { system: "VPN gateway", label: "Staff VPN sessions" },
];

export function MissingEvidence({ a }: { a: AlertDetail }) {
  const present = new Set(a.evidence.map((e) => e.source_system));
  const relevant = EXPECTED.filter((x) => a.typology === "INSIDER_ATO" || !["IAM", "HRMS", "VPN gateway", "CBS app audit"].includes(x.system));
  const have = relevant.filter((x) => present.has(x.system));
  const missing = a.argument.missing;
  const complete = have.length / (relevant.length + missing.length);
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3">
        <span className="display text-[30px] font-extrabold leading-none text-ink">{pct(complete, 0)}</span>
        <span className="text-[12px] text-muted">evidence completeness — SUTRA says what it does not know</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-panel-2">
        <motion.div className="h-full rounded-full bg-ok" initial={{ width: 0 }} animate={{ width: `${complete * 100}%` }} transition={{ duration: 0.8 }} />
      </div>
      <ul className="space-y-1">
        {relevant.map((x) => (
          <li key={x.system} className="flex items-center gap-2 text-[12px]">
            {present.has(x.system) ? <Check size={13} className="text-ok" /> : <Minus size={13} className="text-faint" />}
            <span className={present.has(x.system) ? "text-ink" : "text-faint"}>{x.label}</span>
          </li>
        ))}
        {missing.map((m) => (
          <li key={m} className="flex items-center gap-2 text-[12px]">
            <CircleDashed size={13} className="text-amber" />
            <span className="text-amber">{m}</span>
          </li>
        ))}
      </ul>
      <div className="rounded-lg border border-line bg-panel-2 p-2.5 text-[11.5px] text-ink-2">
        <b className="text-ink">Next best evidence to collect:</b> {missing[0] ?? "—"}
      </div>
    </div>
  );
}

export function EvidenceTable({ items }: { items: EvidenceItem[] }) {
  return (
    <div className="divide-y divide-line rounded-lg border border-line">
      {items.map((e) => (
        <div key={e.code} className="flex items-start gap-2 px-3 py-2">
          <EvidenceChip code={e.code} pool={items} className="mt-[1px] shrink-0" />
          <Grade e={e} />
          <div className="min-w-0 flex-1">
            <div className="text-[12px] leading-snug text-ink-2">{e.summary}</div>
            <div className="mt-0.5 font-mono text-[10px] text-faint">{e.source_system} · {e.source_table}</div>
          </div>
          {e.rebuts.length > 0 && <Tip content="Defence evidence"><span><ShieldCheck size={13} className="text-ok" /></span></Tip>}
        </div>
      ))}
    </div>
  );
}
