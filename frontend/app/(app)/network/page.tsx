"use client";

import { AnimatePresence, motion } from "motion/react";
import { Crosshair, ExternalLink, Filter, Flag } from "lucide-react";
import { Suspense, useMemo, useState } from "react";

import { EntityGraph } from "@/components/graph/entity-graph";
import { EntitySearch } from "@/components/graph/entity-search";
import { Button, ButtonLink, Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useAlerts, useGet } from "@/lib/api";
import { cn } from "@/lib/format";
import { useParam } from "@/lib/params";
import type { GraphEdge, GraphNode } from "@/lib/types";

interface Hood { root: string; nodes: GraphNode[]; edges: GraphEdge[] }

const EDGE_KINDS: { k: string; label: string; tone: "threat" | "amber" | "info" | "ai" | "ok" | "faint" }[] = [
  { k: "PAID", label: "money", tone: "threat" },
  { k: "APPROVED", label: "opened / approved", tone: "amber" },
  { k: "ACCESSED", label: "staff access", tone: "info" },
  { k: "OWNS", label: "owns", tone: "faint" },
  { k: "USED_DEVICE", label: "shared device", tone: "ai" },
  { k: "ER_MATCH", label: "identity match", tone: "amber" },
];

function Network() {
  const [entity, setEntity] = useParam("entity");
  const [hopsP, setHops] = useParam("hops");
  const { data: alerts } = useAlerts();
  const root = entity ?? alerts?.find((a) => a.typology === "INSIDER_ATO")?.employee_id ?? "EMP-0417";
  const hops = hopsP === "2" ? 2 : 1;
  const { data, error, isFetching } = useGet<Hood>(["hood", root, hops], `/graph/neighborhood?entity=${root}&hops=${hops}`, { placeholderData: (p) => p });
  const [off, setOff] = useState<Set<string>>(new Set());
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [noExternal, setNoExternal] = useState(false);
  const [sel, setSel] = useState<GraphNode | null>(null);

  const view = useMemo(() => {
    if (!data) return null;
    const byId = new Map(data.nodes.map((n) => [n.id, n]));
    const keepNode = (id: string) => {
      const n = byId.get(id);
      if (!n) return false;
      if (n.root) return true;
      if (noExternal && (n.kind === "external" || n.kind === "cash")) return false;
      if (flaggedOnly && !n.flagged) return false;
      return true;
    };
    const edges = data.edges.filter((e) => !off.has(e.kind) && keepNode(e.source) && keepNode(e.target));
    const ids = new Set<string>([data.root, ...edges.flatMap((e) => [e.source, e.target])]);
    return { nodes: data.nodes.filter((n) => ids.has(n.id)), edges };
  }, [data, off, flaggedOnly, noExternal]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    data?.edges.forEach((e) => (c[e.kind] = (c[e.kind] ?? 0) + 1));
    return c;
  }, [data]);

  const toggle = (k: string) => setOff((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const reroot = (id: string) => { setSel(null); setEntity(id); };

  return (
    <div className="mx-auto max-w-[1600px] p-5">
      <PageHeader eyebrow="Intelligence · Risk Network" title="Who and what sits around this entity"
        sub="Staff access, account openings, shared devices, identity matches and money — in one neighbourhood. Red rings mark entities already in an active chain."
        right={<EntitySearch onPick={(h) => h.kind !== "alert" && reroot(h.id)} placeholder="Centre the network on…" />} />

      <Panel className="mb-4 flex flex-wrap items-center gap-2 p-3">
        <Filter size={14} className="text-faint" />
        {EDGE_KINDS.filter((e) => counts[e.k]).map((e) => (
          <button key={e.k} onClick={() => toggle(e.k)} className={cn("transition-opacity", off.has(e.k) && "opacity-35")}>
            <Chip tone={e.tone}>{e.label} · {counts[e.k]}</Chip>
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-line" />
        <button onClick={() => setFlaggedOnly((v) => !v)} className={cn("rounded-md border px-2 py-0.5 text-[12px]", flaggedOnly ? "border-threat/50 text-threat" : "border-line text-muted")}>
          <Flag size={11} className="mr-1 inline" />in active chains only
        </button>
        <button onClick={() => setNoExternal((v) => !v)} className={cn("rounded-md border px-2 py-0.5 text-[12px]", noExternal ? "border-ink text-ink" : "border-line text-muted")}>
          hide other banks
        </button>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[12px] text-muted">Hops</span>
          <div className="flex rounded-md border border-line p-0.5">
            {[1, 2].map((h) => (
              <button key={h} onClick={() => setHops(h === 1 ? null : "2")} className={cn("num rounded px-2.5 py-0.5 text-[12px]", hops === h ? "bg-ink text-bg" : "text-muted")}>{h}</button>
            ))}
          </div>
          {view && <span className="num text-[11.5px] text-faint">{view.nodes.length} nodes · {view.edges.length} links</span>}
          {isFetching && <Chip tone="ai">expanding…</Chip>}
        </div>
      </Panel>

      {error && <ErrorBox error={error} />}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Panel className="overflow-hidden">
          <div className="h-[620px]">
            {view ? <EntityGraph nodes={view.nodes} edges={view.edges} layout="radial" root={root} particles={false} focusId={sel?.id} onNodeClick={setSel} /> : <Skeleton className="m-4 h-[580px]" />}
          </div>
        </Panel>
        <Panel className="h-fit">
          <PanelHead eyebrow="Inspector" title={sel ? sel.label : "Click a node"} />
          <div className="px-4 pb-4">
            <AnimatePresence mode="wait">
              {sel ? (
                <motion.div key={sel.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-3">
                  <div className="flex flex-wrap gap-1.5">
                    <Chip tone="faint">{sel.kind}</Chip>
                    {sel.flagged && <Chip tone="threat">in an active chain</Chip>}
                    {sel.root && <Chip tone="info">centre</Chip>}
                    {sel.mule_p != null && sel.mule_p >= 0.5 && <Chip tone="ai">M6 {sel.mule_p.toFixed(2)}</Chip>}
                  </div>
                  {sel.sub && <p className="text-[12.5px] text-ink-2">{sel.sub}</p>}
                  <div className="space-y-1 text-[12px]">
                    {data?.edges.filter((e) => e.source === sel.id || e.target === sel.id).slice(0, 8).map((e) => (
                      <div key={e.id} className="flex items-center gap-1.5 text-muted">
                        <Chip tone={EDGE_KINDS.find((k) => k.k === e.kind)?.tone ?? "faint"}>{EDGE_KINDS.find((k) => k.k === e.kind)?.label ?? e.kind}</Chip>
                        <span className="num truncate text-ink-2">{e.source === sel.id ? `→ ${e.target}` : `← ${e.source}`}</span>
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {!sel.root && sel.kind !== "cash" && <Button size="sm" variant="outline" onClick={() => reroot(sel.id)}><Crosshair size={13} /> Centre here</Button>}
                    {["employee", "account", "customer", "external"].includes(sel.kind) && sel.id !== "X-ATM" && (
                      <ButtonLink size="sm" href={`/entities/${sel.id}`}><ExternalLink size={13} /> Dossier</ButtonLink>
                    )}
                  </div>
                </motion.div>
              ) : (
                <motion.p key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[12.5px] text-muted">
                  Select any node to see how it connects, open its dossier, or re-centre the network on it. Switch to 2 hops to see second-degree links.
                </motion.p>
              )}
            </AnimatePresence>
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default function RiskNetwork() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[620px]" /></div>}><Network /></Suspense>;
}
