"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "motion/react";
import { ChevronLeft, ChevronRight, Copy, Database, Fingerprint, X } from "lucide-react";
import { useState } from "react";

import { useUI } from "@/components/shell/ui-context";
import { Chip, type Tone } from "@/components/ui/primitives";
import { cn, stamp } from "@/lib/format";
import type { EvidenceItem } from "@/lib/types";

const REL: Record<string, { label: string; tone: Tone }> = {
  A: { label: "System of record", tone: "ok" },
  B: { label: "Operational log", tone: "info" },
  C: { label: "SUTRA model output", tone: "ai" },
  D: { label: "LLM-extracted", tone: "amber" },
};
const CRED: Record<number, string> = {
  1: "Corroborated by an independent system",
  2: "Consistent, not independently confirmed",
  3: "Uncorroborated",
  4: "Contradicted by other evidence",
};

export function Grade({ e }: { e: Pick<EvidenceItem, "reliability" | "credibility"> }) {
  const r = REL[e.reliability] ?? REL.C;
  return (
    <Chip tone={r.tone} className="!normal-case">
      {e.reliability}
      {e.credibility}
    </Chip>
  );
}

/** A clickable evidence code — opens the source-record drawer. */
export function EvidenceChip({ code, pool, className }: { code: string; pool: EvidenceItem[]; className?: string }) {
  const { openEvidence } = useUI();
  const e = pool.find((x) => x.code === code);
  const tone = e?.reliability === "C" ? "text-ai border-ai/30" : e?.rebuts.length ? "text-ok border-ok/30" : "text-ink-2 border-line-strong";
  return (
    <button
      onClick={(ev) => {
        ev.stopPropagation();
        openEvidence(code, pool);
      }}
      title={e?.summary}
      className={cn("inline-flex items-center rounded-full border bg-panel-2 px-2 font-mono text-[10.5px] leading-[18px] transition-colors hover:border-info hover:text-info", tone, className)}
    >
      {code}
    </button>
  );
}

export function EvidenceSheet() {
  const { evidence, closeEvidence, openEvidence } = useUI();
  const [copied, setCopied] = useState(false);
  const e = evidence?.item;
  const pool = evidence?.pool ?? [];
  const idx = e ? pool.findIndex((x) => x.code === e.code) : -1;
  const step = (d: number) => {
    const n = pool[idx + d];
    if (n) openEvidence(n.code, pool);
  };
  const copy = async () => {
    if (!e) return;
    try {
      await navigator.clipboard.writeText(e.sha256);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <Dialog.Root open={!!e} onOpenChange={(o) => !o && closeEvidence()}>
      <AnimatePresence>
        {e && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div className="fixed inset-0 z-[70] bg-pastel-ink/30 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </Dialog.Overlay>
            <Dialog.Content asChild aria-describedby={undefined}>
              <motion.aside
                initial={{ x: 480 }}
                animate={{ x: 0 }}
                exit={{ x: 480 }}
                transition={{ type: "spring", stiffness: 380, damping: 38 }}
                className="fixed top-3 right-3 bottom-3 z-[71] flex w-[460px] max-w-[94vw] flex-col overflow-hidden rounded-[2rem] bg-raised shadow-2xl"
              >
                <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
                  <div className="flex items-center gap-2">
                    <Dialog.Title className="display text-[18px] font-bold text-ink">{e.code}</Dialog.Title>
                    <Grade e={e} />
                    {e.rebuts.length > 0 ? <Chip tone="ok">Defence</Chip> : <Chip tone="threat">Supports claim</Chip>}
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => step(-1)} disabled={idx <= 0} className="rounded-full p-1.5 text-muted hover:bg-panel-2 disabled:opacity-30" aria-label="Previous evidence">
                      <ChevronLeft size={16} />
                    </button>
                    <span className="num text-[11px] text-faint">{idx + 1}/{pool.length}</span>
                    <button onClick={() => step(1)} disabled={idx >= pool.length - 1} className="rounded-full p-1.5 text-muted hover:bg-panel-2 disabled:opacity-30" aria-label="Next evidence">
                      <ChevronRight size={16} />
                    </button>
                    <Dialog.Close className="ml-1 rounded-full p-1.5 text-muted hover:bg-panel-2" aria-label="Close">
                      <X size={16} />
                    </Dialog.Close>
                  </div>
                </div>
                <motion.div key={e.code} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
                  <div>
                    <div className="eyebrow mb-1">{e.kind.replaceAll("_", " ")}</div>
                    <p className="text-[14px] leading-relaxed text-ink">{e.summary}</p>
                  </div>
                  <div className="rounded-3xl bg-panel-2 p-4">
                    <div className="eyebrow mb-2 flex items-center gap-1.5"><Database size={12} /> Provenance</div>
                    <dl className="grid grid-cols-[110px_1fr] gap-y-1.5 text-[12.5px]">
                      <dt className="text-muted">Source system</dt><dd className="text-ink">{e.source_system}</dd>
                      <dt className="text-muted">Table · record</dt><dd className="num break-all text-ink">{e.source_table} · {e.source_ref}</dd>
                      <dt className="text-muted">Observed</dt><dd className="num text-ink">{stamp(e.observed_at)} <span className="text-faint">(valid time)</span></dd>
                      {e.ingested_at && (<><dt className="text-muted">Ingested</dt><dd className="num text-ink">{stamp(e.ingested_at)} <span className="text-faint">(system time)</span></dd></>)}
                      <dt className="text-muted">Reliability</dt><dd className="text-ink">{e.reliability} — {REL[e.reliability]?.label}</dd>
                      <dt className="text-muted">Credibility</dt><dd className="text-ink">{e.credibility} — {CRED[e.credibility]}</dd>
                    </dl>
                  </div>
                  {e.entities.length > 0 && (
                    <div>
                      <div className="eyebrow mb-1.5">Entities</div>
                      <div className="flex flex-wrap gap-1.5">{e.entities.map((x) => <Chip key={x} tone="info">{x}</Chip>)}</div>
                    </div>
                  )}
                  <div>
                    <div className="eyebrow mb-1.5">Record facts</div>
                    <pre className="max-h-64 overflow-auto rounded-2xl bg-panel-2 p-3.5 font-mono text-[11px] leading-relaxed text-ink-2">
                      {JSON.stringify(e.facts, null, 2)}
                    </pre>
                  </div>
                  <div className="rounded-3xl border border-line p-4">
                    <div className="eyebrow mb-1.5 flex items-center gap-1.5"><Fingerprint size={12} /> Integrity</div>
                    <div className="flex items-center gap-2">
                      <code className="num flex-1 break-all text-[11px] text-ink-2">{e.sha256}</code>
                      <button onClick={copy} className="rounded-full p-1.5 text-muted hover:bg-panel-2" aria-label="Copy hash">
                        <Copy size={14} />
                      </button>
                    </div>
                    {copied && <div className="mt-1 text-[11px] text-ok">Hash copied</div>}
                  </div>
                </motion.div>
              </motion.aside>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}
