"use client";

// Which engine argued the case (Groq agents or the deterministic script), how much of the evidence the
// agents reviewed, and the harness trace behind every claim: calls, tokens, claims dropped and why.

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, CircleSlash, Cpu, Loader2, ScrollText, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button, Chip, Tip } from "@/components/ui/primitives";
import { api, useGet } from "@/lib/api";
import { cn } from "@/lib/format";
import type { Council, CouncilRunStatus, CouncilStatus, CouncilTrace } from "@/lib/types";

const ENGINE_LABEL = { llm: "Groq agents", hybrid: "Groq agents + deterministic fallback", deterministic: "Deterministic council" };

/** Engine, model, coverage and the button that convenes the agents (runs in the background; polled). */
export function EngineBar({ id, c, onRun }: { id: string; c: Council; onRun?: (runId: string) => void }) {
  const qc = useQueryClient();
  const { data: status } = useGet<CouncilStatus>(["council-status"], "/council/status", { staleTime: 60_000 });
  const [sitting, setSitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function convene() {
    setErr(null);
    setSitting(true);
    try {
      const r = await api<{ run_id: string }>(`/council/${id}/runs`, { method: "POST", body: JSON.stringify({ engine: "auto" }) });
      onRun?.(r.run_id);
      // The council sits in the background; poll until it rules (bounded by the server's own deadline).
      for (let i = 0; i < 360; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        const s = await api<CouncilRunStatus>(`/council/runs/${r.run_id}?trace=false`);
        if (s.status !== "RUNNING") {
          if (s.status === "FAILED") setErr(s.error ?? "The council run failed");
          break;
        }
      }
      await qc.invalidateQueries({ queryKey: ["council", id] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not convene the council");
    } finally {
      setSitting(false);
    }
  }

  const engine = c.engine ?? "deterministic";
  const cov = c.coverage;
  const llmReady = status?.effective_engine === "llm";
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
      <span className={cn("inline-flex items-center gap-1.5 text-[12.5px] font-semibold", engine === "deterministic" ? "text-ink-2" : "text-ai")}>
        {engine === "deterministic" ? <Cpu size={14} /> : <Bot size={14} />} {ENGINE_LABEL[engine]}
      </span>
      {c.model && engine !== "deterministic" && <Chip tone="ai" mono>{c.model}</Chip>}
      {cov && (
        <Tip content={cov.unreviewed.length ? `Not reviewed by an agent: ${cov.unreviewed.slice(0, 12).join(", ")}` : "Every evidence item reached at least one agent"}>
          <span><Chip tone={cov.partial ? "amber" : "ok"}>{cov.reviewed}/{cov.evidence_total} evidence items reviewed</Chip></span>
        </Tip>
      )}
      {c.stats.llm_calls !== undefined && <Chip tone="faint" mono>{c.stats.llm_calls} calls · {(c.stats.tokens ?? 0).toLocaleString("en-IN")} tokens</Chip>}
      {c.run?.stale && (
        <Chip tone="amber"><AlertTriangle size={11} /> case revised since this run — convene again</Chip>
      )}
      {c.fallback_reason && (
        <Tip content={c.fallback_reason}><span><Chip tone="amber"><CircleSlash size={11} /> agents unavailable: deterministic fallback</Chip></span></Tip>
      )}
      <div className="ml-auto flex items-center gap-2">
        {sitting && <span className="inline-flex items-center gap-1.5 text-[12px] text-ai"><Loader2 size={13} className="animate-spin" /> Council sitting…</span>}
        {err && <span className="text-[12px] text-threat">{err}</span>}
        <Tip content={llmReady ? `Runs the agents on ${status?.model}; every claim is checked by SUTRA's harness`
          : "No Groq key on the API server — this runs the deterministic council. Set GROQ_API_KEY to use agents."}>
          <span>
            <Button size="sm" variant="ai" onClick={convene} disabled={sitting}>
              <Sparkles size={13} /> {llmReady ? "Convene AI agents" : "Re-run council"}
            </Button>
          </span>
        </Tip>
      </div>
    </div>
  );
}

const STEP_TONE: Record<string, "ok" | "amber" | "threat" | "faint" | "info"> = {
  OK: "ok", REPAIRED: "amber", CACHED: "info", INVALID: "threat", FAILED: "threat", SKIPPED: "amber", PENDING: "faint",
};

/** Every agent call the harness made, and every claim it dropped or downgraded, with the reason. */
export function TraceTab({ runId }: { runId?: string }) {
  const { data, isLoading } = useGet<CouncilRunStatus>(["council-run-trace", runId], runId ? `/council/runs/${runId}` : null);
  if (!runId) {
    return <p className="text-[12.5px] text-muted">This view is the deterministic council computed on request. Convene the agents to get a harness trace.</p>;
  }
  if (isLoading || !data?.trace) return <p className="text-[12.5px] text-muted">Loading the trace…</p>;
  const t: CouncilTrace = data.trace;
  const dropped = t.steps.flatMap((s) => s.dropped.map((d) => ({ ...d, agent: s.agent })));
  const adjusted = t.steps.flatMap((s) => s.adjusted.map((d) => ({ ...d, agent: s.agent })));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5 text-[12px]">
        <Chip tone="faint" mono>{t.usage.calls} calls</Chip>
        <Chip tone="faint" mono>{t.usage.tokens.toLocaleString("en-IN")} tokens</Chip>
        <Chip tone="faint" mono>{t.usage.seconds}s</Chip>
        <Chip tone="faint" mono>prompts {t.prompt_version}</Chip>
        <Chip tone={dropped.length ? "amber" : "ok"}>{dropped.length} claims dropped</Chip>
        <Chip tone={adjusted.length ? "amber" : "ok"}>{adjusted.length} statuses lowered</Chip>
      </div>
      {t.fallbacks.length > 0 && (
        <div className="rounded-md border border-amber/30 bg-amber-soft/50 p-2.5 text-[12px] text-amber">
          {t.fallbacks.map((f) => <div key={f.agent}><b>{f.agent}</b>: {f.reason} — deterministic part used</div>)}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-[12px]">
          <thead><tr className="text-left text-[10.5px] uppercase tracking-wide text-faint">
            <th className="py-1.5 pr-2">Agent</th><th className="pr-2">Round</th><th className="pr-2">Step</th><th className="pr-2">Status</th>
            <th className="pr-2 text-right">Tokens</th><th className="pr-2 text-right">ms</th><th>Records</th>
          </tr></thead>
          <tbody>
            {t.steps.map((s, i) => (
              <tr key={i} className="border-t border-line align-top">
                <td className="py-1.5 pr-2 font-medium text-ink">{s.agent}</td>
                <td className="num pr-2 text-muted">{s.round}</td>
                <td className="pr-2 text-muted">{s.purpose}{s.batch ? ` · part ${s.batch}` : ""}</td>
                <td className="pr-2"><Tip content={s.error ?? (s.validation_errors.join("; ") || "valid")}><span><Chip tone={STEP_TONE[s.status] ?? "faint"}>{s.status.toLowerCase()}</Chip></span></Tip></td>
                <td className="num pr-2 text-right text-ink-2">{(s.prompt_tokens + s.completion_tokens).toLocaleString("en-IN")}</td>
                <td className="num pr-2 text-right text-ink-2">{s.ms.toLocaleString("en-IN")}</td>
                <td className="num text-muted">{s.evidence_sent.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(dropped.length > 0 || adjusted.length > 0) && (
        <div>
          <div className="eyebrow mb-1.5 flex items-center gap-1.5"><ScrollText size={12} /> What the harness refused</div>
          <div className="space-y-1.5">
            {dropped.map((d, i) => (
              <div key={`d${i}`} className="rounded-md border border-line p-2 text-[11.5px]">
                <span className="font-semibold text-ink">{d.agent}</span> <span className="text-threat">dropped</span>: <span className="text-ink-2">“{d.text}”</span>
                <div className="text-muted">{d.reason}</div>
              </div>
            ))}
            {adjusted.map((d, i) => (
              <div key={`a${i}`} className="rounded-md border border-line p-2 text-[11.5px]">
                <span className="font-semibold text-ink">{d.agent}</span> <span className="text-amber">{d.from.toLowerCase()} → {d.to.toLowerCase()}</span>: <span className="text-ink-2">“{d.text}”</span>
                <div className="text-muted">{d.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
