"use client";

import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  useNodesInitialized,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "motion/react";
import { Banknote, Building2, KeyRound, Landmark, Smartphone, User, UserCog, Wallet } from "lucide-react";
import { useEffect, useId, useMemo } from "react";

import { cn, inr } from "@/lib/format";
import type { GraphEdge, GraphNode } from "@/lib/types";

// ── layout ─────────────────────────────────────────────────────────────────

export type LayoutMode = "chain" | "radial" | "tree";

function layered(nodes: GraphNode[], edges: GraphEdge[]): Record<string, { x: number; y: number }> {
  const col: Record<string, number> = {};
  const money = edges.filter((e) => e.kind === "PAID" || e.kind === "money");
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  for (const n of nodes) {
    if (n.kind === "employee") col[n.id] = 0;
    else if (n.kind === "entitlement") col[n.id] = 0;
    else if (n.role === "staff_device") col[n.id] = 1;
    else if (n.kind === "customer") col[n.id] = 1;
    else if (n.role === "victim") col[n.id] = 2;
    else if (n.role === "new_device") col[n.id] = 2;
  }
  // money BFS from victims (and from any account with no inbound money edge)
  const inbound = new Set(money.map((e) => e.target));
  let frontier = nodes.filter((n) => n.role === "victim" || (n.kind === "account" && !inbound.has(n.id) && col[n.id] === undefined && money.some((e) => e.source === n.id))).map((n) => n.id);
  frontier.forEach((id) => (col[id] ??= 2));
  const seen = new Set(frontier);
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const e of money.filter((m) => m.source === id)) {
        if (seen.has(e.target)) continue;
        seen.add(e.target);
        col[e.target] = Math.max(col[e.target] ?? 0, (col[id] ?? 2) + 1);
        next.push(e.target);
      }
    }
    frontier = next;
  }
  const maxCol = Math.max(3, ...Object.values(col));
  for (const n of nodes) {
    if (n.kind === "cash") col[n.id] = maxCol + (col[n.id] === maxCol ? 0 : 1);
    if (col[n.id] === undefined) {
      const src = edges.find((e) => e.target === n.id && col[e.source] !== undefined);
      col[n.id] = src ? col[src.source] + 1 : 1;
    }
  }
  const groups: Record<number, string[]> = {};
  const firstT = (id: string) => edges.filter((e) => e.source === id || e.target === id).map((e) => e.t ?? "").filter(Boolean).sort()[0] ?? "";
  for (const n of nodes) (groups[col[n.id]] ??= []).push(n.id);
  const pos: Record<string, { x: number; y: number }> = {};
  for (const [c, ids] of Object.entries(groups)) {
    ids.sort((a, b) => {
      const ka = byId[a].kind === "entitlement" ? "0" : firstT(a);
      const kb = byId[b].kind === "entitlement" ? "0" : firstT(b);
      return ka.localeCompare(kb);
    });
    ids.forEach((id, i) => {
      pos[id] = { x: Number(c) * 230, y: (i - (ids.length - 1) / 2) * 104 };
    });
  }
  return pos;
}

function radial(nodes: GraphNode[], edges: GraphEdge[], root?: string): Record<string, { x: number; y: number }> {
  const r0 = root ?? nodes.find((n) => n.root)?.id ?? nodes[0]?.id;
  const depth: Record<string, number> = { [r0]: 0 };
  let frontier = [r0];
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier)
      for (const e of edges) {
        const other = e.source === id ? e.target : e.target === id ? e.source : null;
        if (other && depth[other] === undefined) {
          depth[other] = depth[id] + 1;
          next.push(other);
        }
      }
    frontier = next;
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const rings: Record<number, string[]> = {};
  for (const n of nodes) (rings[depth[n.id] ?? 3] ??= []).push(n.id);
  const pos: Record<string, { x: number; y: number }> = {};
  // Each BFS depth fills as many concentric sub-rings as it needs so cards never overlap;
  // flagged entities sit on the innermost ring.
  const SPACING = 230;
  let R = 0;
  for (const d of Object.keys(rings).map(Number).sort((a, b) => a - b)) {
    const ids = rings[d].slice().sort((a, b) => Number(!!byId.get(b)?.flagged) - Number(!!byId.get(a)?.flagged)
      || (byId.get(a)?.kind ?? "").localeCompare(byId.get(b)?.kind ?? ""));
    if (d === 0) { ids.forEach((id) => (pos[id] = { x: 0, y: 0 })); continue; }
    for (let k = 0; ids.length; k++) {
      R += k === 0 ? 250 : 150;
      const chunk = ids.splice(0, Math.max(6, Math.floor((2 * Math.PI * R) / SPACING)));
      chunk.forEach((id, i) => {
        const a = (i / chunk.length) * Math.PI * 2 + d * 0.4 + k * 0.25;
        pos[id] = { x: Math.cos(a) * R, y: Math.sin(a) * R * 0.8 };
      });
    }
  }
  return pos;
}

function tree(nodes: GraphNode[]): Record<string, { x: number; y: number }> {
  const tier = (n: GraphNode) => (n.kind === "employee" ? 0 : n.kind === "account" ? 1 : 2);
  const groups: Record<number, GraphNode[]> = {};
  nodes.forEach((n) => (groups[tier(n)] ??= []).push(n));
  // Long tiers wrap into staggered rows so a 10-account cluster stays legible.
  const PER_ROW = 5, DX = 200, DY = 96, GAP = 150;
  const pos: Record<string, { x: number; y: number }> = {};
  let y = 0;
  for (const t of Object.keys(groups).map(Number).sort((a, b) => a - b)) {
    const ns = groups[t];
    const rows = Math.ceil(ns.length / PER_ROW);
    ns.forEach((n, i) => {
      const r = Math.floor(i / PER_ROW);
      const inRow = Math.min(PER_ROW, ns.length - r * PER_ROW);
      const c = i % PER_ROW;
      pos[n.id] = { x: (c - (inRow - 1) / 2) * DX + (r % 2 ? DX / 4 : 0), y: y + r * DY };
    });
    y += (rows - 1) * DY + GAP;
  }
  return pos;
}

// ── nodes ──────────────────────────────────────────────────────────────────

const ICON = { employee: UserCog, account: Wallet, external: Landmark, cash: Banknote, device: Smartphone, customer: User, entitlement: KeyRound, phone: Smartphone };

type NodeData = GraphNode & { dim?: boolean; focus?: boolean; pulse?: number } & Record<string, unknown>;

function EntityNode({ data }: NodeProps<Node<NodeData>>) {
  const Icon = ICON[data.kind] ?? Building2;
  const role = data.role;
  const tone =
    data.kind === "employee" ? "border-threat/70 bg-threat-soft" :
    role === "victim" ? "border-amber/70 bg-amber-soft" :
    (data.mule_p ?? 0) >= 0.5 || role === "mule" ? "border-threat/50 bg-panel" :
    data.kind === "entitlement" ? "border-ai/60 border-dashed bg-ai-soft" :
    role === "new_device" ? "border-ai/60 bg-ai-soft" :
    data.kind === "cash" ? "border-line-strong bg-panel-2" :
    data.flagged ? "border-threat/40 bg-panel" : "border-line-strong bg-panel";
  return (
    <motion.div
      initial={{ scale: 0.6, opacity: 0 }}
      animate={{ scale: 1, opacity: data.dim ? 0.18 : 1 }}
      transition={{ type: "spring", stiffness: 380, damping: 26, delay: (data.pulse ?? 0) * 0.04 }}
      className={cn("relative w-[172px] rounded-lg border px-2.5 py-2 shadow-sm", tone, data.focus && "ring-2 ring-info/60", data.root && "ring-2 ring-threat/50")}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-line-strong" />
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-line-strong" />
      <div className="flex items-center gap-1.5">
        <Icon size={13} className={cn(data.kind === "employee" ? "text-threat" : data.kind === "entitlement" || role === "new_device" ? "text-ai" : "text-muted")} />
        <span className="num truncate text-[11.5px] font-semibold text-ink">{data.label}</span>
        {data.mule_p != null && data.mule_p >= 0.5 && (
          <span className="ml-auto rounded bg-threat px-1 font-mono text-[9px] font-bold text-white" title="Mule-likeness (M6)">M6 {data.mule_p.toFixed(2)}</span>
        )}
      </div>
      {data.sub && <div className="mt-0.5 truncate text-[10.5px] text-muted">{data.sub}</div>}
      {role && role !== "" && role !== "device" && (
        <div className={cn("mt-1 inline-block rounded px-1 font-mono text-[9px] uppercase tracking-wider",
          role === "insider" ? "bg-threat text-white" : role === "victim" ? "bg-amber text-black" : role === "new_device" ? "bg-ai text-white" : "bg-panel-2 text-muted")}>
          {role.replace("_", " ")}
        </div>
      )}
    </motion.div>
  );
}

// ── edges ──────────────────────────────────────────────────────────────────

type EdgeData = GraphEdge & { dim?: boolean; particles?: boolean; selected?: boolean } & Record<string, unknown>;

function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<Edge<EdgeData>>) {
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const k = data?.kind ?? "";
  const isMoney = k === "PAID" || k === "money";
  const stroke =
    isMoney ? "var(--threat)" :
    k === "privilege" || k === "CHANGED" ? "var(--threat)" :
    k === "PAYEE" ? "var(--amber)" :
    k === "APPROVED" || k === "HOLDS" || k === "ER_MATCH" || k === "USED_DEVICE" ? "var(--ai)" :
    k === "SHARED_DEVICE" || k === "SHARED_PHONE" ? "var(--ai)" : "var(--line-strong)";
  const width = isMoney ? Math.min(1.4 + Math.log10((data?.amount ?? 1000) + 1) * 0.55, 4.2) : 1.3;
  const dash = k === "PAYEE" || k === "ER_MATCH" || k === "ACCESSED" ? "5 4" : k === "APPROVED" || k === "HOLDS" ? "2 4" : undefined;
  const opacity = data?.dim ? 0.08 : 1;
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke, strokeWidth: data?.selected ? width + 1.5 : width, strokeDasharray: dash, opacity, transition: "opacity .35s" }} />
      {isMoney && data?.particles && !data?.dim && (
        <circle r={2.6} fill="var(--threat)">
          <animateMotion dur={`${1.6 + ((data.amount ?? 0) % 7) / 10}s`} repeatCount="indefinite" path={path} />
        </circle>
      )}
      {(isMoney || k === "CHANGED" || k === "PAYEE") && !data?.dim && (
        <EdgeLabelRenderer>
          <div
            style={{ transform: `translate(-50%, -50%) translate(${lx}px,${ly}px)` }}
            className={cn("nodrag nopan pointer-events-none absolute rounded border px-1 font-mono text-[9.5px]",
              isMoney ? "border-threat/40 bg-bg text-threat" : "border-line bg-bg text-muted")}
          >
            {isMoney ? inr(data?.amount) : data?.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { entity: EntityNode };
const edgeTypes = { flow: FlowEdge };

// ── component ──────────────────────────────────────────────────────────────

export interface EntityGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  layout?: LayoutMode;
  asOf?: string | null;
  particles?: boolean;
  focusId?: string | null;
  selectedEdge?: string | null;
  onNodeClick?: (n: GraphNode) => void;
  onEdgeClick?: (e: GraphEdge) => void;
  className?: string;
  root?: string;
}

function Inner({ nodes, edges, layout = "chain", asOf, particles = true, focusId, selectedEdge, onNodeClick, onEdgeClick, root, graphId }: EntityGraphProps & { graphId: string }) {
  const pos = useMemo(
    () => (layout === "radial" ? radial(nodes, edges, root) : layout === "tree" ? tree(nodes) : layered(nodes, edges)),
    [nodes, edges, layout, root],
  );
  const appear = useMemo(() => {
    const m: Record<string, string> = {};
    for (const e of edges) {
      if (!e.t) continue;
      for (const id of [e.source, e.target]) if (!m[id] || e.t < m[id]) m[id] = e.t;
    }
    return m;
  }, [edges]);

  const rfNodes: Node<NodeData>[] = useMemo(
    () =>
      nodes.map((n, i) => ({
        id: n.id,
        type: "entity",
        position: pos[n.id] ?? { x: 0, y: 0 },
        data: { ...n, pulse: i, focus: focusId === n.id, dim: !!asOf && !!appear[n.id] && appear[n.id] > asOf && !["employee", "customer"].includes(n.kind) && n.role !== "victim" },
      })),
    [nodes, pos, asOf, appear, focusId],
  );
  const rfEdges: Edge<EdgeData>[] = useMemo(
    () =>
      edges
        .filter((e) => pos[e.source] && pos[e.target])
        .map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          type: "flow",
          data: { ...e, particles, selected: selectedEdge === e.id, dim: !!asOf && !!e.t && e.t > asOf },
        })),
    [edges, pos, asOf, particles, selectedEdge],
  );

  const { fitView } = useReactFlow();
  const measured = useNodesInitialized();
  useEffect(() => {
    if (!measured) return;
    const t = setTimeout(() => fitView({ padding: 0.12, duration: 450, maxZoom: 1.1 }), 30);
    return () => clearTimeout(t);
  }, [measured, nodes.length, layout, fitView]);
  // refit when the panel itself changes size (layout settling, sidebar collapse, window resize)
  useEffect(() => {
    const el = document.querySelector(`[data-graph="${graphId}"]`);
    if (!el || !measured) return;
    let t: ReturnType<typeof setTimeout>;
    const ro = new ResizeObserver(() => {
      clearTimeout(t);
      t = setTimeout(() => fitView({ padding: 0.12, duration: 300, maxZoom: 1.1 }), 120);
    });
    ro.observe(el);
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [measured, fitView, graphId]);

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      minZoom={0.25}
      maxZoom={1.6}
      proOptions={{ hideAttribution: true }}
      nodesDraggable
      onNodeClick={(_, n) => onNodeClick?.(n.data as GraphNode)}
      onEdgeClick={(_, e) => onEdgeClick?.(e.data as GraphEdge)}
    >
      <Background gap={28} size={1} color="var(--bg-grid)" />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}

export function EntityGraph(props: EntityGraphProps) {
  const graphId = useId();
  return (
    <div className={cn("h-full w-full", props.className)} data-graph={graphId}>
      <ReactFlowProvider>
        <Inner {...props} graphId={graphId} />
      </ReactFlowProvider>
    </div>
  );
}
