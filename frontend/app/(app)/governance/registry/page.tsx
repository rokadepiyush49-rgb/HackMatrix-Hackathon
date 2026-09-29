"use client";

import { motion } from "motion/react";
import { Bot, Cpu, Sparkles } from "lucide-react";
import { useState } from "react";

import { AgentAvatar, stanceOf } from "@/components/council/council";
import { Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn, stamp } from "@/lib/format";
import type { CouncilAgent, Registry } from "@/lib/types";

const FAMILY_TONE: Record<string, "threat" | "info" | "ai" | "amber" | "faint"> = { RULE: "info", ML: "ai", GRAPH: "amber", ASSEMBLY: "threat" };

export default function RegistryPage() {
  const { data, error } = useGet<Registry>(["registry"], "/governance/registry");
  const [family, setFamily] = useState<string | null>(null);
  const families = [...new Set(data?.detectors.map((d) => d.family))];

  return (
    <div className="mx-auto max-w-[1500px] p-5">
      <PageHeader eyebrow="Governance · Agents, Models & Rules" title="Everything that can raise a signal, versioned and owned"
        sub="Each detector, model and agent has an owner, a version and plain-language logic. Every evidence pack records the versions that produced it." />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Skeleton className="h-96" />}
      {data && (
        <Tabs defaultValue="detectors">
          <TabsList>
            <TabsTrigger value="detectors">Detectors ({data.detectors.length})</TabsTrigger>
            <TabsTrigger value="models">Models ({Object.keys(data.models).length})</TabsTrigger>
            <TabsTrigger value="agents">Council agents ({data.agents.length})</TabsTrigger>
            <TabsTrigger value="llm">Language model</TabsTrigger>
          </TabsList>
          <TabsContent value="detectors" className="mt-4">
            <div className="mb-3 flex flex-wrap gap-1.5">
              <button onClick={() => setFamily(null)} className={cn("rounded-full border px-3 py-1 text-[12.5px] font-medium", !family ? "border-ink bg-ink text-bg" : "border-line text-muted")}>All</button>
              {families.map((f) => <button key={f} onClick={() => setFamily(f)} className={cn("rounded-full border px-3 py-1 text-[12.5px] font-medium", family === f ? "border-ink bg-ink text-bg" : "border-line text-muted")}>{f.toLowerCase()}</button>)}
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data.detectors.filter((d) => !family || d.family === family).map((d, i) => (
                <motion.div key={d.code} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.02 }}>
                  <Panel className="h-full p-3.5">
                    <div className="flex items-center gap-2">
                      <span className="num rounded bg-panel-2 px-1.5 py-0.5 text-[11px] text-ink">{d.code}</span>
                      <span className="text-[13px] font-semibold text-ink">{d.name}</span>
                      <Chip tone={FAMILY_TONE[d.family] ?? "faint"} className="ml-auto">{d.family.toLowerCase()}</Chip>
                    </div>
                    <p className="mt-2 text-[12px] leading-relaxed text-ink-2">{d.logic}</p>
                    {Object.keys(d.params ?? {}).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">{Object.entries(d.params).map(([k, v]) => <Chip key={k} tone="faint" className="!normal-case">{k}={String(v)}</Chip>)}</div>
                    )}
                    <div className="mt-2 flex items-center justify-between text-[11px] text-faint"><span>v{d.version} · {d.owner}</span><span className="num">{d.signals} signals</span></div>
                  </Panel>
                </motion.div>
              ))}
            </div>
          </TabsContent>
          <TabsContent value="models" className="mt-4">
            <div className="grid gap-4 lg:grid-cols-2">
              {Object.entries(data.models).map(([name, m]) => (
                <Panel key={name} className="p-4">
                  <div className="flex items-center gap-2"><Cpu size={16} className="text-ai" /><span className="text-[14px] font-semibold text-ink">{name}</span><span className="num ml-auto text-[11px] text-faint">v{m.version} · trained {stamp(m.trained_at)}</span></div>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    {Object.entries(m.metrics).filter(([, v]) => typeof v === "number").map(([k, v]) => (
                      <div key={k} className="rounded-md bg-panel-2 px-2 py-1.5"><div className="text-[10.5px] text-faint">{k}</div><div className="num text-[14px] text-ink">{Number(v).toFixed(Number.isInteger(v) ? 0 : 3)}</div></div>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1">{m.features.map((f) => <Chip key={f} tone="faint" className="!normal-case">{f}</Chip>)}</div>
                  <p className="mt-2 text-[11px] text-faint">{String(m.metrics.note ?? "")} Training seed {m.train_seed}, n = {m.n_train.toLocaleString("en-IN")}.</p>
                </Panel>
              ))}
            </div>
          </TabsContent>
          <TabsContent value="agents" className="mt-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {data.agents.map((a) => {
                const st = "stance" in a ? (a as CouncilAgent).stance : "NEUTRAL";
                return (
                  <Panel key={a.id} className="p-3.5">
                    <div className="flex items-center gap-2.5"><AgentAvatar agent={{ icon: a.icon, stance: st }} size={32} />
                      <div><div className="text-[13px] font-semibold text-ink">{a.name}</div><div className={cn("text-[11px]", stanceOf(st).text)}>{a.id === "moderator" ? "Runs the council" : stanceOf(st).label}</div></div>
                    </div>
                    <p className="mt-2 text-[12px] text-muted">{a.job}</p>
                    <div className="mt-2 flex flex-wrap gap-1"><Chip tone="faint">reads Loom evidence</Chip><Chip tone="faint">may request records</Chip><Chip tone="threat">cannot score or close</Chip></div>
                  </Panel>
                );
              })}
            </div>
          </TabsContent>
          <TabsContent value="llm" className="mt-4">
            <Panel className="p-5">
              <div className="flex items-center gap-2"><Sparkles size={18} className="text-ai" /><span className="display text-[16px] font-semibold text-ink">Claude, in a language-only role</span></div>
              <p className="mt-2 text-[13px] text-ink-2">{data.llm.role}</p>
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                {[
                  { t: "Cite or drop", d: "Every sentence must carry evidence codes. The verifier checks codes, amounts, times and IDs against Loom; anything it cannot tie to a record is removed and shown as dropped." },
                  { t: "Structured output", d: "Answers are requested as JSON against a fixed schema, so the interface never parses free text for facts." },
                  { t: "Deterministic fallback", d: "Without an API key, the same answers are composed from the evidence book by rules — the demo never depends on a network call." },
                ].map((x) => <div key={x.t} className="rounded-lg border border-line p-3"><div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink"><Bot size={14} className="text-ai" />{x.t}</div><p className="mt-1 text-[12px] text-muted">{x.d}</p></div>)}
              </div>
            </Panel>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
