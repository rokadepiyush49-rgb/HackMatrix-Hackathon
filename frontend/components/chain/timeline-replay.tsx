"use client";

import { AnimatePresence, motion } from "motion/react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Chip, Tip } from "@/components/ui/primitives";
import { cn, dayMonth, duration, hhmm, inr } from "@/lib/format";
import type { Replay, StatePoint } from "@/lib/types";

const LANES = ["IAM", "HR", "SOC", "FRAUD", "AML"] as const;
const LANE_COLOR: Record<string, string> = { IAM: "bg-ai", HR: "bg-ok", SOC: "bg-amber", FRAUD: "bg-threat", AML: "bg-info" };

function at<T extends StatePoint>(series: T[] | undefined, iso: string): T | undefined {
  if (!series?.length) return undefined;
  let cur = series[0];
  for (const p of series) if (p.t === null || p.t <= iso) cur = p;
  return cur;
}

export function useAsOf(replay?: Replay) {
  const [asOf, setAsOf] = useState<string | null>(null);
  return { asOf, setAsOf };
}

export function TimelineReplay({ replay, asOf, onAsOf, focusAccount }: {
  replay: Replay; asOf: string | null; onAsOf: (iso: string | null) => void; focusAccount?: string | null;
}) {
  const evening = replay.events.filter((e) => e.lane !== "IAM");
  const precursor = replay.events.filter((e) => e.lane === "IAM");
  const t0 = new Date(evening[0]?.t ?? replay.window.start).getTime() - 10 * 60_000;
  const t1 = new Date(evening.at(-1)?.t ?? replay.window.end).getTime() + 8 * 60_000;
  const span = t1 - t0;
  const [playing, setPlaying] = useState(false);
  const raf = useRef<number | null>(null);
  const cur = asOf ? new Date(asOf).getTime() : t1;
  const frac = Math.min(1, Math.max(0, (cur - t0) / span));

  const setFrac = useCallback((f: number) => {
    const t = t0 + Math.min(1, Math.max(0, f)) * span;
    onAsOf(new Date(t).toISOString());
  }, [t0, span, onAsOf]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let f = frac >= 0.999 ? 0 : frac;
    const tick = (now: number) => {
      f += (now - last) / 14000;
      last = now;
      if (f >= 1) {
        setFrac(1);
        setPlaying(false);
        return;
      }
      setFrac(f);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  const iso = new Date(cur).toISOString();
  const victim = focusAccount ?? replay.nodes.find((n) => n.role === "victim")?.id ?? Object.keys(replay.state)[0];
  const st = victim ? replay.state[victim] : undefined;
  const mobile = at(st?.mobile, iso);
  const limit = at(st?.limit, iso);
  const balance = at(st?.balance, iso);
  const payees = (st?.payees ?? []).filter((p) => p.t && p.t <= iso && p.t >= replay.window.start);
  const pw = (st?.password ?? []).filter((p) => p.t && p.t <= iso);
  const grant = replay.nodes.find((n) => n.kind === "entitlement");
  const grantExpired = grant?.expiry ? grant.expiry < iso : false;
  const known = replay.events.filter((e) => e.t <= iso).length;

  const ticks = useMemo(() => {
    const out: number[] = [];
    const step = span > 3 * 3600_000 ? 30 * 60_000 : 15 * 60_000;
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push(t);
    return out;
  }, [t0, t1, span]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => setPlaying((p) => !p)} className="flex size-8 items-center justify-center rounded-md bg-ink text-bg" aria-label={playing ? "Pause replay" : "Play replay"}>
          {playing ? <Pause size={14} /> : <Play size={14} className="translate-x-[1px]" />}
        </button>
        <button onClick={() => { setPlaying(false); onAsOf(null); }} className="flex size-8 items-center justify-center rounded-md border border-line text-muted hover:text-ink" aria-label="Reset to now">
          <RotateCcw size={14} />
        </button>
        <div className="text-[13px] text-ink-2">
          What did the bank know at <span className="display text-[18px] font-extrabold text-ink">{hhmm(iso)}</span> on {dayMonth(iso)}?
        </div>
        <Chip tone="info" className="ml-auto">{known}/{replay.events.length} events known · bitemporal as-of</Chip>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_280px]">
        {/* lanes */}
        <div className="rounded-lg border border-line bg-panel-2 p-3">
          <div className="grid grid-cols-[64px_120px_1fr] gap-y-1.5">
            {LANES.map((lane) => (
              <div key={lane} className="contents">
                <div className="flex h-7 items-center font-mono text-[10px] tracking-wider text-muted">{lane}</div>
                {/* precursor gutter (days earlier) */}
                <div className="relative flex h-7 items-center gap-1 border-r border-dashed border-line-strong pr-2">
                  {precursor.filter((e) => (lane === "IAM" ? true : false)).map((e, i) => (
                    <Tip key={i} content={<><b>{e.title}</b><br />{e.detail}<br /><span className="num text-faint">{dayMonth(e.t)} {hhmm(e.t)}</span></>}>
                      <span className={cn("rounded px-1 font-mono text-[9.5px] text-white", iso >= e.t ? "bg-ai" : "bg-ai/30")}>{dayMonth(e.t)}</span>
                    </Tip>
                  ))}
                </div>
                <div className="relative h-7">
                  <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
                  {evening.filter((e) => e.lane === lane).map((e, i) => {
                    const x = (new Date(e.t).getTime() - t0) / span;
                    const past = e.t <= iso;
                    return (
                      <Tip key={i} content={<><b>{e.code} · {e.title}</b><br />{e.detail}<br /><span className="num text-faint">{hhmm(e.t, true)}</span></>}>
                        <motion.button
                          className={cn("absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg", LANE_COLOR[lane])}
                          style={{ left: `${x * 100}%` }}
                          animate={{ scale: past ? 1 : 0.6, opacity: past ? 1 : 0.25 }}
                          onClick={() => onAsOf(e.t)}
                          aria-label={`${e.title} at ${hhmm(e.t)}`}
                        />
                      </Tip>
                    );
                  })}
                </div>
              </div>
            ))}
            {/* axis */}
            <div />
            <div className="text-right font-mono text-[9.5px] text-faint">days earlier →</div>
            <div className="relative h-5">
              {ticks.map((t) => (
                <span key={t} className="num absolute -translate-x-1/2 text-[9.5px] text-faint" style={{ left: `${((t - t0) / span) * 100}%` }}>
                  {hhmm(new Date(t).toISOString())}
                </span>
              ))}
            </div>
          </div>
          {/* scrubber */}
          <div className="relative ml-[184px] mt-1 h-6">
            <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-line" />
            <div className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-threat/70" style={{ width: `${frac * 100}%` }} />
            <input
              type="range" min={0} max={1000} value={Math.round(frac * 1000)}
              onChange={(e) => { setPlaying(false); setFrac(Number(e.target.value) / 1000); }}
              className="absolute inset-0 w-full cursor-grab appearance-none bg-transparent [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-bg [&::-webkit-slider-thumb]:bg-threat [&::-webkit-slider-thumb]:shadow"
              aria-label="As-of time"
            />
          </div>
        </div>

        {/* state panel */}
        <div className="rounded-lg border border-line p-3">
          <div className="eyebrow mb-2">State of {victim} as of {hhmm(iso)}</div>
          <StateRow label="Registered mobile" value={String(mobile?.value ?? "—")} changed={!!mobile?.t} note={mobile?.auth ? `by ${mobile.by} · ${mobile.auth}` : undefined} />
          <StateRow label="Per-txn limit" value={typeof limit?.value === "number" ? inr(limit.value) : String(limit?.value ?? "—")} changed={!!limit?.t} note={limit?.auth ? `by ${limit.by} · ${limit.auth}` : undefined} />
          <StateRow label="Balance" value={typeof balance?.value === "number" ? inr(balance.value) : "—"} changed={!!balance?.t} />
          <StateRow label="Password" value={pw.length ? "reset" : "unchanged"} changed={pw.length > 0} />
          <div className="mt-1.5 border-t border-line pt-1.5">
            <div className="text-[11px] text-muted">New payees</div>
            <AnimatePresence initial={false}>
              {payees.length === 0 && <motion.div key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[12px] text-faint">none yet</motion.div>}
              {payees.map((p) => (
                <motion.div key={p.payee} initial={{ opacity: 0, x: -8, height: 0 }} animate={{ opacity: 1, x: 0, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                  className="num text-[12px] text-threat">+ {p.payee} <span className="text-faint">{p.name}</span></motion.div>
              ))}
            </AnimatePresence>
          </div>
          {grant && (
            <div className="mt-1.5 border-t border-line pt-1.5 text-[11.5px]">
              <span className="text-muted">Override grant {grant.label}: </span>
              {grantExpired ? <span className="font-semibold text-threat">past expiry, still active</span> : <span className="text-ok">within validity</span>}
            </div>
          )}
        </div>
      </div>

      {replay.deltas.length > 0 && (
        <div>
          <div className="eyebrow mb-1.5">What changed before the money moved?</div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {replay.deltas.map((d) => (
              <button key={d.code + d.t} onClick={() => onAsOf(d.t)} className="rounded-lg border border-line px-3 py-2 text-left hover:border-line-strong">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-amber">{d.code}</span>
                  <span className="text-[12.5px] font-semibold text-ink">{d.title}</span>
                  <span className="num ml-auto text-[11px] text-threat">−{duration(d.before_payment_s)}</span>
                </div>
                <div className="mt-0.5 line-clamp-1 text-[11px] text-muted">{d.detail}</div>
                {d.base_rate && <div className="mt-0.5 text-[10.5px] text-faint">{d.base_rate}</div>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StateRow({ label, value, changed, note }: { label: string; value: string; changed?: boolean; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-[3px]">
      <span className="text-[11px] text-muted">{label}</span>
      <span className="text-right">
        <AnimatePresence mode="popLayout">
          <motion.span key={value} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
            className={cn("num block text-[12.5px]", changed ? "text-threat" : "text-ink")}>{value}</motion.span>
        </AnimatePresence>
        {note && <span className="block text-[10px] text-faint">{note}</span>}
      </span>
    </div>
  );
}
