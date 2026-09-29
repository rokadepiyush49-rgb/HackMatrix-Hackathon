"use client";

import { motion } from "motion/react";
import { EyeOff, FileCheck2, Gauge, Hand, Scale, ShieldCheck, Sparkles, Users } from "lucide-react";

import { PageHeader, Panel } from "@/components/ui/primitives";

const PRINCIPLES = [
  { icon: Hand, t: "Humans decide", d: "No model, rule or agent opens, scores or closes a case. SUTRA argues; an investigator proposes; a second person approves." },
  { icon: Gauge, t: "No opaque risk score", d: "Alerts carry seven named dimensions at NONE/LOW/ELEVATED/HIGH and the lattice rule that set their priority — never a single number to trust blindly." },
  { icon: FileCheck2, t: "Evidence or it didn't happen", d: "Every claim cites evidence graded for reliability (A–D) and credibility (1–4). Model outputs are grade C and cannot carry a case alone." },
  { icon: Scale, t: "Innocent explanations first", d: "Alibi looks for tickets, portfolios, queues, customer presence and rosters before anything is called suspicious. The Defence Agent must test the innocent reading." },
  { icon: EyeOff, t: "Pseudonymous by default", d: "Staff appear by role and branch. Revealing a name needs a reason, a second approver, expires after 4 hours and is written to the audit chain." },
  { icon: Sparkles, t: "Language model, language only", d: "Claude drafts narratives and answers questions with citations. A verifier drops any sentence it cannot tie to a record. Without a key, a deterministic engine takes over." },
  { icon: Users, t: "Proportionate", d: "Twin scenarios prove the system stays quiet on legitimate look-alikes: pension camps, kirana deposits, college fees, declared relatives." },
  { icon: ShieldCheck, t: "Auditable end to end", d: "Hash-chained audit log, SHA-256 evidence manifests, versioned detectors and model cards in every pack. Synthetic data only — no real customer or employee." },
];

export default function Policy() {
  return (
    <div className="mx-auto max-w-[1200px] p-5">
      <PageHeader eyebrow="Governance · Responsible AI" title="How SUTRA is allowed to behave"
        sub="These are enforced in code and tested in the Twin Scenario Lab — not aspirations on a slide." />
      <div className="grid gap-3 md:grid-cols-2">
        {PRINCIPLES.map((p, i) => (
          <motion.div key={p.t} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Panel className="flex h-full gap-3 p-4">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-panel-2 text-ai"><p.icon size={18} /></span>
              <div><div className="text-[14px] font-semibold text-ink">{p.t}</div><p className="mt-1 text-[12.5px] leading-relaxed text-muted">{p.d}</p></div>
            </Panel>
          </motion.div>
        ))}
      </div>
      <p className="mt-4 text-[11.5px] text-faint">Aligned with RBI&apos;s FREE-AI principles on explainability, human oversight and accountability, and with the Digital Personal Data Protection Act&apos;s purpose limitation and minimisation. SUTRA is a hackathon prototype on fictional data.</p>
    </div>
  );
}
