"use client";

import { motion } from "motion/react";
import { ArrowRight, Banknote, Factory, Fingerprint, Landmark, Smartphone, UserX } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EntityGraph } from "@/components/graph/entity-graph";
import { Button, Chip, CountUp, Empty, ErrorBox, PageHeader, Panel, PanelHead, Skeleton, Tip } from "@/components/ui/primitives";
import { useAlerts, useGet } from "@/lib/api";
import { cn, dayMonth, inr } from "@/lib/format";
import type { EmployeeCard, GraphEdge, GraphNode } from "@/lib/types";

interface Cluster {
  signal_id: string;
  employee: EmployeeCard;
  summary: string;
  stats: {
    accounts: number; baseline: number; deviation: number; burst_p: number; shared_accounts: number;
    shared_devices: number; shared_phones: number; presenceless: number; inflow: number; cash_out: number;
  };
  accounts: {
    id: string; opened_at: string; mode: string; self_approved: boolean; segment: string; devices: string[];
    inflow: number; cash_out: number; mule_p: number | null; presenceless: boolean;
  }[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
}

/** Openings over the detection window against the employee's usual pace. */
function BurstStrip({ c }: { c: Cluster }) {
  const times = c.accounts.map((a) => new Date(a.opened_at).getTime()).sort((a, b) => a - b);
  const end = times[times.length - 1] + 2 * 86400e3;
  const start = end - 62 * 86400e3;
  const W = 640, H = 92, x = (t: number) => 24 + ((t - start) / (end - start)) * (W - 48);
  const weeks = Array.from({ length: 9 }, (_, i) => start + i * 7 * 86400e3);
  // Cumulative count vs the baseline pace (baseline accounts per 60 days).
  const pts = times.map((t, i) => [x(t), H - 16 - ((i + 1) / c.accounts.length) * (H - 34)] as const);
  const base = [[x(start), H - 16], [x(end), H - 16 - (c.stats.baseline / c.accounts.length) * (H - 34)]] as const;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${c.accounts.length} openings in 60 days against a baseline of ${c.stats.baseline}`}>
      {weeks.map((w) => (
        <g key={w}>
          <line x1={x(w)} x2={x(w)} y1={10} y2={H - 16} stroke="currentColor" className="text-line" strokeDasharray="2 3" />
          <text x={x(w)} y={H - 3} textAnchor="middle" fontSize="10" fill="currentColor" className="text-faint">{dayMonth(new Date(w).toISOString())}</text>
        </g>
      ))}
      <line x1={base[0][0]} y1={base[0][1]} x2={base[1][0]} y2={base[1][1]} stroke="currentColor" className="text-ok" strokeWidth={1.5} strokeDasharray="5 4" />
      <text x={base[1][0] - 4} y={base[1][1] - 5} textAnchor="end" fontSize="10" fill="currentColor" className="text-ok">usual pace ({c.stats.baseline}/60d)</text>
      <motion.polyline points={[[x(start), H - 16], ...pts].map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" className="text-threat" strokeWidth={2}
        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.4, ease: "easeOut" }} />
      {pts.map(([px, py], i) => (
        <motion.circle key={i} cx={px} cy={py} r={3.5} fill="currentColor" className="text-threat" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 0.3 + i * 0.1 }} />
      ))}
    </svg>
  );
}

export default function MuleFactory() {
  const router = useRouter();
  const { data, error, isLoading } = useGet<Cluster[]>(["mule"], "/mule/clusters");
  const { data: alerts } = useAlerts();
  const [focus, setFocus] = useState<string | null>(null);
  const alert = alerts?.find((a) => a.typology === "MULE_FACTORY");
  const c = data?.[0];

  const shared = new Map<string, string[]>();
  c?.accounts.forEach((a) => a.devices.forEach((d) => shared.set(d, [...(shared.get(d) ?? []), a.id])));

  return (
    <div className="mx-auto max-w-[1560px] p-5">
      <PageHeader eyebrow="Intelligence · Mule Factory" title="Accounts made to receive stolen money"
        sub="G4 looks for one employee opening accounts faster than their own baseline, without the customer present, that then share devices or phones and pass money straight through. Each signal on its own is common; together they are a factory."
        right={alert && <>
          <Button variant="ai" onClick={() => router.push(`/council/${alert.id}`)}><Landmark size={14} /> Council</Button>
          <Button variant="primary" onClick={() => router.push(`/cases/${alert.id}`)}>Open case <ArrowRight size={14} /></Button>
        </>} />
      {error && <ErrorBox error={error} />}
      {isLoading && <Skeleton className="h-[480px]" />}
      {data && data.length === 0 && <Empty title="No mule factory detected" icon={<Factory size={28} />}>G4 found no cluster in this window.</Empty>}

      {c && (
        <>
          <Panel className="mb-4 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="ai">G4 · mule factory</Chip><span className="num text-[11px] text-faint">{c.signal_id}</span>
              <span className="text-[12.5px] text-muted">Opened &amp; approved by</span>
              <Link href={`/entities/${c.employee.id}`} className="text-[13px] font-semibold text-ink hover:text-info">{c.employee.pseudonym}</Link>
              <span className="num text-[11px] text-faint">{c.employee.id}</span>
            </div>
            <p className="mt-2 text-[13.5px] leading-relaxed text-ink">{c.summary}</p>
          </Panel>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {[
              { k: "Accounts in 60 days", v: c.stats.accounts, sub: `usual pace ${c.stats.baseline}`, icon: Factory, tone: "text-threat" },
              { k: "Burst probability", v: c.stats.burst_p, f: (v: number) => (v < 0.001 ? "<0.001" : v.toFixed(3)), sub: "Poisson, vs own baseline", icon: Factory, tone: "text-threat" },
              { k: "Opened without customer", v: c.stats.presenceless, sub: `of ${c.stats.accounts} · self-approved KYC`, icon: UserX, tone: "text-amber" },
              { k: "Share a device or phone", v: c.stats.shared_accounts, sub: `${c.stats.shared_devices} devices · ${c.stats.shared_phones} phone`, icon: Smartphone, tone: "text-amber" },
              { k: "Money in", v: c.stats.inflow, f: (v: number) => inr(v), sub: "fan-in from victims", icon: Banknote, tone: "text-ink" },
              { k: "Cashed out", v: c.stats.cash_out, f: (v: number) => inr(v), sub: `${Math.round((c.stats.cash_out / Math.max(1, c.stats.inflow)) * 100)}% of inflow`, icon: Banknote, tone: "text-threat" },
            ].map((x, i) => (
              <motion.div key={x.k} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                <Panel className="h-full p-3.5">
                  <div className="flex items-center gap-1.5 text-[11.5px] text-muted"><x.icon size={13} />{x.k}</div>
                  <div className={cn("display mt-1 text-[24px] font-extrabold leading-none", x.tone)}><CountUp value={x.v} format={x.f} /></div>
                  <div className="mt-1 text-[11px] text-faint">{x.sub}</div>
                </Panel>
              </motion.div>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Panel className="overflow-hidden">
              <PanelHead eyebrow="Constellation" title="Who opened what, and what they share"
                right={<span className="text-[11.5px] text-faint">Drag to explore · red badge = M6 mule-likeness</span>} />
              <div className="h-[480px] border-t border-line">
                <EntityGraph nodes={c.graph.nodes} edges={c.graph.edges} layout="tree" particles={false} focusId={focus}
                  onNodeClick={(n) => setFocus(n.id === focus ? null : n.id)} />
              </div>
            </Panel>
            <div className="space-y-4">
              <Panel>
                <PanelHead eyebrow="Deviation" title="Openings against the employee's own pace" />
                <div className="px-4 pb-3"><BurstStrip c={c} /></div>
                <p className="px-4 pb-4 text-[11.5px] text-muted">
                  The dashed line is how many accounts this employee would normally open in the same period. The red line is what happened.
                </p>
              </Panel>
              <Panel>
                <PanelHead eyebrow="Shared identifiers" title="One device, several 'customers'" />
                <div className="space-y-2 px-4 pb-4">
                  {[...shared.entries()].filter(([, ids]) => ids.length > 1).map(([d, ids]) => (
                    <div key={d} className="flex flex-wrap items-center gap-1.5 rounded-md border border-amber/25 bg-amber-soft/30 px-2.5 py-2 text-[12px]">
                      <Fingerprint size={13} className="text-amber" /><span className="num font-semibold text-ink">{d}</span>
                      <span className="text-muted">used by</span>
                      {ids.map((id) => <button key={id} onClick={() => setFocus(id)} className="num rounded bg-panel-2 px-1.5 text-ink-2 hover:text-info">{id}</button>)}
                    </div>
                  ))}
                  {c.stats.shared_phones > 0 && <p className="text-[11.5px] text-muted">{c.stats.shared_phones} phone number is also registered on more than one of these accounts.</p>}
                </div>
              </Panel>
            </div>
          </div>

          <Panel className="mt-4 overflow-hidden">
            <PanelHead eyebrow="Accounts" title={`${c.accounts.length} accounts in the cluster`} />
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-[12px]">
                <thead><tr className="border-b border-line text-left">
                  {["Account", "Opened", "Mode", "KYC", "Segment", "Devices", "Money in", "Cashed out", "M6 mule-likeness"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 eyebrow">{h}</th>)}
                </tr></thead>
                <tbody>
                  {c.accounts.slice().sort((a, b) => a.opened_at.localeCompare(b.opened_at)).map((a, i) => (
                    <motion.tr key={a.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.03 }}
                      onMouseEnter={() => setFocus(a.id)} className={cn("border-b border-line last:border-0 hover:bg-panel-2", focus === a.id && "bg-panel-2")}>
                      <td className="num whitespace-nowrap px-3 py-2"><Link href={`/entities/${a.id}`} className="text-ink hover:text-info">{a.id}</Link></td>
                      <td className="num whitespace-nowrap px-3 py-2 text-muted">{dayMonth(a.opened_at)}</td>
                      <td className="px-3 py-2">{a.presenceless ? <Chip tone="amber">no customer present</Chip> : <Chip tone="faint">{a.mode.toLowerCase()}</Chip>}</td>
                      <td className="px-3 py-2">{a.self_approved ? <Chip tone="threat">self-approved</Chip> : <Chip tone="ok">second approver</Chip>}</td>
                      <td className="px-3 py-2 text-ink-2">{a.segment.toLowerCase()}</td>
                      <td className="num px-3 py-2">{a.devices.map((d) => <span key={d} className={cn("mr-1", (shared.get(d)?.length ?? 0) > 1 ? "text-amber" : "text-muted")}>{d}</span>)}</td>
                      <td className="num whitespace-nowrap px-3 py-2 text-ink">{inr(a.inflow)}</td>
                      <td className="num whitespace-nowrap px-3 py-2 text-threat">{a.cash_out ? inr(a.cash_out) : "—"}</td>
                      <td className="px-3 py-2">
                        {a.mule_p !== null ? (
                          <Tip content="M6 model output (grade C evidence) — explained by TreeSHAP on the entity page">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-20 overflow-hidden rounded-full bg-line"><div className="h-full bg-ai" style={{ width: `${a.mule_p * 100}%` }} /></div>
                              <span className="num text-[11px] text-ai">{a.mule_p.toFixed(2)}</span>
                            </div>
                          </Tip>
                        ) : <span className="text-faint">—</span>}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
