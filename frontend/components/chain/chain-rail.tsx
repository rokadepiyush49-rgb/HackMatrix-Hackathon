"use client";

import { AnimatePresence, motion } from "motion/react";
import { Scissors } from "lucide-react";
import { useMemo, useState } from "react";

import { CountUp, Tip } from "@/components/ui/primitives";
import { cn, dayMonth, duration, hhmm, inr } from "@/lib/format";
import type { ChainLink } from "@/lib/types";

const LANE_TONE: Record<string, string> = {
  IAM: "text-ai",
  SOC: "text-amber",
  FRAUD: "text-threat",
  AML: "text-info",
  HR: "text-ok",
};

export interface RailNode {
  key: string;
  code: string;
  t: string;
  title: string;
  detail: string;
  lane: string;
  links: ChainLink[];
}

/** Collapse runs of layering links (E5′ / E6) into one grouped node so the rail stays readable. */
export function railNodes(links: ChainLink[]): RailNode[] {
  const out: RailNode[] = [];
  for (const lk of links) {
    const layering = lk.code === "E5′" || lk.code === "E6";
    const last = out.at(-1);
    if (layering && last && (last.code === "LAYER")) {
      last.links.push(lk);
      continue;
    }
    if (layering) {
      out.push({ key: `layer-${lk.id}`, code: "LAYER", t: lk.t, title: "", detail: "", lane: "AML", links: [lk] });
      continue;
    }
    out.push({ key: lk.id, code: lk.code, t: lk.t, title: lk.title, detail: lk.detail, lane: lk.lane, links: [lk] });
  }
  for (const n of out) {
    if (n.code === "LAYER") {
      const loops = n.links.filter((l) => l.code === "E6").length;
      const cash = n.links.filter((l) => l.title === "Cash-out").length;
      n.title = loops ? "Layering · loop closes" : "Layering";
      n.detail = `${n.links.length - loops - cash} forwards · ${cash} cash-outs${loops ? ` · ${loops} loop${loops > 1 ? "s" : ""}` : ""}`;
    }
  }
  return out;
}

export function ChainRail({
  links,
  latencyS,
  leadS,
  activeCode,
  onSelect,
  asOf,
  severAt,
  compact = false,
  className,
}: {
  links: ChainLink[];
  latencyS?: number | null;
  leadS?: number | null;
  activeCode?: string | null;
  onSelect?: (node: RailNode) => void;
  asOf?: string | null;
  severAt?: string | null;
  compact?: boolean;
  className?: string;
}) {
  const nodes = useMemo(() => railNodes(links), [links]);
  const [hover, setHover] = useState<string | null>(null);
  const cut = severAt ? nodes.findIndex((n) => n.code === severAt || n.links.some((l) => l.code === severAt)) : -1;
  const col = compact ? 132 : 152;

  return (
    <div className={cn("relative", className)}>
      {(latencyS || leadS) && !compact && (
        <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1">
          {latencyS ? (
            <div className="flex items-baseline gap-2">
              <span className="eyebrow !text-threat">Access → money</span>
              <span className="display text-[28px] font-extrabold leading-none text-threat">
                <CountUp value={Math.round(latencyS / 60)} format={(v) => `${Math.round(v)}`} />
                <span className="ml-1 text-[15px] font-bold">min</span>
              </span>
            </div>
          ) : null}
          {leadS ? (
            <div className="text-[12.5px] text-ink-2">
              SUTRA found the enabling privilege <b className="text-ink">{duration(leadS)}</b> before the transaction.
            </div>
          ) : null}
        </div>
      )}
      <div className="overflow-x-auto pb-2">
        <div className="relative" style={{ width: nodes.length * col + 24, minWidth: "100%" }}>
          {/* spine */}
          <div className="absolute left-3 right-3 top-[34px] h-px bg-line" />
          <div className="flex">
            {nodes.map((n, i) => {
              const future = asOf ? n.t > asOf : false;
              const severed = cut >= 0 && i >= cut;
              const active = activeCode && (n.code === activeCode || n.links.some((l) => l.code === activeCode));
              const next = nodes[i + 1];
              return (
                <div key={n.key} className="relative shrink-0 px-1.5" style={{ width: col }}>
                  {/* connector to next */}
                  {next && (
                    <motion.div
                      className={cn("absolute left-1/2 top-[33px] h-[3px] origin-left rounded-full",
                        severed || (cut >= 0 && i + 1 >= cut) ? "bg-line-strong" : "bg-threat")}
                      style={{ width: col }}
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1, opacity: future || (asOf && next.t > asOf) ? 0.15 : 1 }}
                      transition={{ delay: 0.15 + i * 0.12, duration: 0.3, ease: "easeOut" }}
                    />
                  )}
                  {cut >= 0 && i === cut && (
                    <motion.div initial={{ scale: 0, rotate: -40 }} animate={{ scale: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 400 }}
                      className="absolute -left-2 top-[22px] z-10 flex size-6 items-center justify-center rounded-full border border-ok bg-ok-soft text-ok">
                      <Scissors size={12} />
                    </motion.div>
                  )}
                  <button
                    onClick={() => onSelect?.(n)}
                    onMouseEnter={() => setHover(n.key)}
                    onMouseLeave={() => setHover(null)}
                    className={cn("group relative block w-full text-left transition-opacity", (future || severed) && "opacity-30")}
                  >
                    <div className="num mb-1.5 h-4 text-[11px] text-muted">
                      {i === 0 || dayMonth(n.t) !== dayMonth(nodes[i - 1].t) ? <span className="text-faint">{dayMonth(n.t)} </span> : null}
                      {hhmm(n.t)}
                    </div>
                    <motion.div
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ delay: 0.1 + i * 0.12, type: "spring", stiffness: 500, damping: 22 }}
                      className={cn(
                        "relative z-10 flex size-[18px] items-center justify-center rounded-full border-2",
                        n.code === "E0" ? "border-ai bg-bg" : n.code === "LAYER" ? "border-info bg-info-soft" : "border-threat bg-threat",
                        active && "ring-4 ring-threat/25",
                      )}
                    >
                      {n.code === "LAYER" && <span className="num text-[9px] font-bold text-info">{n.links.length}</span>}
                    </motion.div>
                    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 + i * 0.12 }} className="mt-2 pr-2">
                      <div className="flex items-center gap-1.5">
                        <span className={cn("num text-[10px] font-semibold", LANE_TONE[n.lane])}>{n.code === "LAYER" ? "E5′–E6" : n.code}</span>
                        <span className="text-[9.5px] font-mono tracking-wider text-faint">{n.lane}</span>
                      </div>
                      <div className={cn("text-[12.5px] font-semibold leading-tight text-ink", active && "text-threat")}>{n.title}</div>
                      {!compact && <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted">{n.detail}</div>}
                    </motion.div>
                  </button>
                  <AnimatePresence>
                    {hover === n.key && n.code === "LAYER" && (
                      <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                        className="absolute left-2 top-full z-30 mt-1 w-[300px] rounded-lg border border-line-strong bg-raised p-2.5 shadow-xl">
                        {n.links.map((l) => (
                          <div key={l.id} className="flex items-baseline gap-2 py-0.5 text-[11.5px]">
                            <span className="num w-10 shrink-0 text-faint">{hhmm(l.t)}</span>
                            <span className={cn("shrink-0 font-mono text-[10px]", l.code === "E6" ? "text-threat" : "text-info")}>{l.code}</span>
                            <span className="text-ink-2">{l.detail}</span>
                          </div>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function LaneLegend() {
  return (
    <div className="flex flex-wrap gap-3 text-[11px] text-muted">
      {Object.entries({ IAM: "IAM team", SOC: "SOC / insider risk", FRAUD: "Fraud ops", AML: "AML" }).map(([k, v]) => (
        <Tip key={k} content={`${v} would see only these links`}>
          <span className="flex items-center gap-1.5">
            <span className={cn("font-mono text-[10px] font-semibold", LANE_TONE[k])}>{k}</span> {v}
          </span>
        </Tip>
      ))}
    </div>
  );
}

export const money = inr;
