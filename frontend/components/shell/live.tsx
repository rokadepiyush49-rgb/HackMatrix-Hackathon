"use client";

import { AnimatePresence, motion } from "motion/react";
import { Radio, Square } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { Chip } from "@/components/ui/primitives";
import { cn, hhmm, inr } from "@/lib/format";

export interface LiveEvent {
  type: "signal" | "link" | "alert";
  t: string;
  detector?: string;
  summary?: string;
  alert_id?: string;
  priority?: string;
  code?: string;
  title?: string;
  detail?: string;
  lane?: string;
  claim?: string;
  amount?: number;
}

interface LiveState {
  running: boolean;
  clock: string | null;
  events: LiveEvent[];
  start: () => void;
  stop: () => void;
}

const Ctx = createContext<LiveState | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState(false);
  const [clock, setClock] = useState<string | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const es = useRef<EventSource | null>(null);

  const stop = useCallback(() => {
    es.current?.close();
    es.current = null;
    setRunning(false);
  }, []);

  const start = useCallback(() => {
    stop();
    setEvents([]);
    const src = new EventSource("/api/sutra/stream/replay?speed=60");
    es.current = src;
    setRunning(true);
    src.addEventListener("start", (e) => setClock(JSON.parse((e as MessageEvent).data).start));
    for (const type of ["signal", "link", "alert"] as const) {
      src.addEventListener(type, (e) => {
        const ev = { type, ...JSON.parse((e as MessageEvent).data) } as LiveEvent;
        setClock(ev.t);
        setEvents((prev) => [...prev, ev].slice(-200));
      });
    }
    src.addEventListener("end", () => stop());
    src.onerror = () => stop();
  }, [stop]);

  useEffect(() => stop, [stop]);
  return <Ctx.Provider value={{ running, clock, events, start, stop }}>{children}</Ctx.Provider>;
}

export function useLive() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}

export function LivePill() {
  const { running, clock, start, stop } = useLive();
  return (
    <button
      onClick={running ? stop : start}
      className={cn(
        "flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-4 text-[12.5px] font-medium shadow-sm transition-[color,box-shadow] hover:shadow-md",
        running ? "bg-coral-soft text-pastel-ink" : "bg-panel text-ink-2 hover:text-ink",
      )}
      title="Replays the evening of 21 Sep 2026 at 60× from stored events"
    >
      {running ? <Square size={12} className="fill-current" /> : <Radio size={14} />}
      {running ? (
        <span className="num">Replay · {hhmm(clock, true)} IST</span>
      ) : (
        <span>Replay<span className="hidden xl:inline"> 21 Sep evening</span></span>
      )}
    </button>
  );
}

export function LiveToasts() {
  const { events, running } = useLive();
  const shown = events.filter((e) => e.type !== "signal" || !["R5", "R6", "M2"].includes(e.detector ?? "")).slice(-4);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[360px] flex-col gap-2">
      <AnimatePresence initial={false}>
        {running &&
          shown.map((e) => (
            <motion.div
              key={`${e.type}-${e.t}-${e.code ?? e.detector ?? e.alert_id}`}
              layout
              initial={{ opacity: 0, x: 40, scale: 0.96 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40 }}
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
              className={cn(
                "pointer-events-auto rounded-3xl border bg-raised px-4 py-3 shadow-xl",
                e.type === "alert" ? "border-coral" : "border-transparent",
              )}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className="num text-[11px] text-faint">{hhmm(e.t, true)}</span>
                {e.type === "alert" && <Chip tone="threat">New {e.priority}</Chip>}
                {e.type === "link" && <Chip tone="info">{e.lane} · {e.code}</Chip>}
                {e.type === "signal" && <Chip tone="ai">{e.detector}</Chip>}
              </div>
              {e.type === "alert" ? (
                <Link href={`/cases/${e.alert_id}`} className="block text-[12.5px] text-ink hover:underline">
                  {e.claim} · <b>{inr(e.amount)}</b>
                </Link>
              ) : (
                <div className="text-[12.5px] text-ink-2">{e.type === "link" ? `${e.title} — ${e.detail}` : e.summary}</div>
              )}
            </motion.div>
          ))}
      </AnimatePresence>
    </div>
  );
}
