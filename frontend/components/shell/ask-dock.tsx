"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, ChevronDown, ShieldAlert, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { EvidenceChip } from "@/components/brief/evidence";
import { Chip } from "@/components/ui/primitives";
import { useAlert, useAsk } from "@/lib/api";
import { cn } from "@/lib/format";
import type { AskAnswer } from "@/lib/types";

import { useUI } from "./ui-context";

export function AskDock() {
  const { ask, closeAsk } = useUI();
  return (
    <AnimatePresence>
      {ask && (
        <motion.aside
          initial={{ x: 440, opacity: 0.6 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 440, opacity: 0 }}
          transition={{ type: "spring", stiffness: 360, damping: 36 }}
          className="fixed top-3 right-3 bottom-3 z-[65] flex w-[430px] max-w-[94vw] flex-col overflow-hidden rounded-[2rem] bg-raised shadow-2xl"
        >
          <AskBody key={`${ask.alertId}|${ask.question ?? ""}`} alertId={ask.alertId} question={ask.question} onClose={closeAsk} />
        </motion.aside>
      )}
    </AnimatePresence>
  );
}


/** One conversation. Keyed by case and opening question, so switching either starts fresh. */
function AskBody({ alertId, question, onClose }: { alertId: string; question?: string; onClose: () => void }) {
  const { data: alert } = useAlert(alertId);
  const mutate = useAsk();
  const { mutate: send } = mutate;
  const [q, setQ] = useState("");
  const [thread, setThread] = useState<AskAnswer[]>([]);
  const scroller = useRef<HTMLDivElement>(null);
  const asked = useRef(false);

  // The opening question (from a "Ask SUTRA about this" button) is sent once per conversation.
  useEffect(() => {
    if (!question || asked.current) return;
    asked.current = true;
    send({ alert_id: alertId, question }, { onSuccess: (a) => setThread((t) => [...t, a]) });
  }, [alertId, question, send]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [thread.length]);

  function submit(text: string) {
    if (!text.trim()) return;
    setQ("");
    send({ alert_id: alertId, question: text }, { onSuccess: (a) => setThread((t) => [...t, a]) });
  }

  const pool = alert?.evidence ?? [];
  const suggested = thread.at(-1)?.suggested ?? [
    "Why was this flagged?", "What happened before the payment?", "What argues against this?",
    "Who else is connected to this employee?", "What would have stopped this?",
  ];


  return (
    <>
          <div className="flex items-center justify-between gap-3 bg-orchid px-5 py-4 text-pastel-ink">
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-pastel-ink text-tangerine">
                <Sparkles size={17} />
              </span>
              <div className="min-w-0">
                <div className="display text-[17px] font-semibold">Ask SUTRA</div>
                <div className="text-[11.5px] opacity-75">
                  Answers only from {alert?.id ?? "case"} evidence · every sentence cited or dropped
                </div>
              </div>
            </div>
            <button onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-full bg-paper/70 hover:bg-paper" aria-label="Close">
              <X size={16} />
            </button>
          </div>

          <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {thread.length === 0 && !mutate.isPending && (
              <div className="rounded-3xl bg-panel-2 p-4 text-[12.5px] text-muted">
                SUTRA answers from the case&apos;s graded evidence. It never creates, scores or closes an alert, and it does
                not attribute acts to a person — that stays with the investigator.
              </div>
            )}
            {thread.map((a, i) => (
              <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
                <div className="ml-auto w-fit max-w-[90%] rounded-3xl rounded-br-md bg-primary px-4 py-2.5 text-[13px] text-on-primary">{a.question}</div>
                <div className="flex items-center gap-2">
                  <Chip tone={a.confidence === "HIGH" ? "ok" : a.confidence === "MEDIUM" ? "amber" : "faint"}>
                    {a.confidence} corroboration
                  </Chip>
                  <Chip tone="ai">{a.mode === "llm" ? a.model ?? "Claude" : "deterministic engine"}</Chip>
                </div>
                <ol className="space-y-2">
                  {a.sentences.map((s, j) => (
                    <motion.li key={j} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: j * 0.05 }}
                      className="rounded-2xl bg-panel-2 px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-2">
                      {s.text}{" "}
                      <span className="inline-flex flex-wrap gap-1 align-middle">
                        {s.evidence.map((c) => <EvidenceChip key={c} code={c} pool={pool} />)}
                      </span>
                    </motion.li>
                  ))}
                </ol>
                {a.dropped.length > 0 && (
                  <details className="group rounded-2xl bg-amber-soft px-3.5 py-2.5 text-[12px] text-amber">
                    <summary className="flex cursor-pointer list-none items-center gap-1.5">
                      <ShieldAlert size={13} /> {a.dropped.length} sentence(s) dropped by the verifier
                      <ChevronDown size={13} className="ml-auto transition-transform group-open:rotate-180" />
                    </summary>
                    <ul className="mt-2 space-y-1.5">
                      {a.dropped.map((d, k) => (
                        <li key={k} className="text-ink-2"><s className="opacity-70">{d.text}</s> — <i>{d.reason}</i></li>
                      ))}
                    </ul>
                  </details>
                )}
              </motion.div>
            ))}
            {mutate.isPending && (
              <div className="flex items-center gap-2 text-[12.5px] text-muted">
                <motion.span className="size-2 rounded-full bg-ai" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ repeat: Infinity, duration: 1 }} />
                Reading the evidence…
              </div>
            )}
            {mutate.isError && <div className="text-[12.5px] text-threat">{mutate.error.message}</div>}
          </div>

          <div className="border-t border-line px-5 py-3">
            <div className="mb-2 flex flex-wrap gap-1.5">
              {suggested.slice(0, 5).map((s) => (
                <button key={s} onClick={() => submit(s)} className="rounded-full bg-panel-2 px-3 py-1.5 text-[11.5px] text-ink-2 transition-colors hover:bg-ai-soft hover:text-ai">
                  {s}
                </button>
              ))}
            </div>
            <form onSubmit={(e) => { e.preventDefault(); submit(q); }} className="flex items-center gap-2 rounded-full border border-line bg-panel py-1 pr-1 pl-4 focus-within:border-ink/40">
              <input id="ask-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Why was EMP-0417 accessing A-5520?"
                className="h-10 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-faint" />
              <button type="submit" disabled={!q.trim() || mutate.isPending}
                className={cn("flex size-9 items-center justify-center rounded-full bg-primary text-on-primary transition-opacity", (!q.trim() || mutate.isPending) && "opacity-40")}
                aria-label="Ask">
                <ArrowUp size={15} />
              </button>
            </form>
          </div>
    </>
  );
}
