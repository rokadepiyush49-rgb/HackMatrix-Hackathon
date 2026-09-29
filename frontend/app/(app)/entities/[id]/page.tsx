"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "motion/react";
import { Activity, AlertTriangle, ArrowRight, Building2, EyeOff, KeyRound, Network, Smartphone, UserCog, Users, Wallet, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { DimBars } from "@/components/chain/alert-bits";
import { Button, ButtonLink, Chip, CountUp, Empty, ErrorBox, PageHeader, Panel, PanelHead, PriorityPill, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Tip } from "@/components/ui/primitives";
import { useGet, useMe, usePost } from "@/lib/api";
import { cn, dayMonth, inr, pct, stamp } from "@/lib/format";
import type { AlertSummary, EmployeeCard } from "@/lib/types";

// ── payloads ───────────────────────────────────────────────────────────────

interface Ent { id: string; permission: string; granted_by: string; reason: string; request_ref: string | null; valid_from: string; intended_expiry: string | null; revoked_at: string | null; flags: string[] }
interface Signal { id: string; detector: string; summary: string; t: string }
interface Employee {
  kind: "employee"; id: string; card: EmployeeCard; branch: string; hire_date: string; tenure_years: number;
  entitlements: Ent[];
  baseline: { hour_rates: number[]; peer_hour_rates: number[]; sessions_90d: number; after20_sessions: number; peer_after20_share: number; approvals_60d: number; approvals_baseline_60d: number };
  alibi: { explained: number; partial: number; unexplained: number; coverage: number; recent: { access_id: string; t: string; verdict: string; action: string; account_id: string; reasons: number }[] };
  approved_accounts: { id: string; opened_at: string; mode: string; self_opened: boolean }[];
  relationships: { customer_id: string; type: string; confidence: number; detail: { fields?: Record<string, string>; declared?: boolean } }[];
  alerts: AlertSummary[]; signals: Signal[];
}
interface Account {
  kind: "account"; id: string; holder_name: string; bank: string; type: string; status: string; status_since: string | null;
  opened_at: string | null; opening_mode: string | null; opened_by: EmployeeCard | null; kyc_approved_by: EmployeeCard | null;
  balance: number | null; limit: number | null; customer: { id: string; segment: string; branch_id: string; rm: string | null } | null;
  state_changes: { t: string; field: string; old: string; new: string; by: string; auth: string }[];
  payees: { t: string; account: string; name: string }[];
  flows: { in: number; in_count: number; out: number; out_count: number };
  top_counterparties: { account: string; amount: number; count: number }[];
  recent_txns: { id: string; t: string; from: string; to: string; amount: number; channel: string; narration: string }[];
  devices: { id: string; sessions: number }[];
  mule: { p: number; contributions: { label: string; value: number; feature: string; contribution: number }[] } | null;
  alerts: AlertSummary[]; signals: Signal[];
}
interface Customer {
  kind: "customer"; id: string; segment: string; branch_id: string; created_at: string; rm: string | null;
  accounts: { id: string; status: string; balance: number }[]; relationships: Employee["relationships"]; alerts: AlertSummary[];
}
type Dossier = Employee | Account | Customer;

// ── shared bits ────────────────────────────────────────────────────────────

const FLAG: Record<string, { label: string; tone: "threat" | "amber" | "ai"; why: string }> = {
  EXPIRED_BUT_ACTIVE: { label: "expired, still active", tone: "threat", why: "Past its intended expiry and never revoked" },
  TOXIC_COMBINATION: { label: "toxic combination", tone: "amber", why: "Together with another permission this breaks segregation of duties" },
  OUTSIDE_ROLE: { label: "outside role", tone: "ai", why: "Not part of this role's baseline entitlements" },
};

function Fact({ k, children }: { k: string; children: ReactNode }) {
  return <div className="min-w-0"><div className="text-[11px] text-faint">{k}</div><div className="truncate text-[13px] text-ink">{children}</div></div>;
}

function Related({ alerts, signals }: { alerts: AlertSummary[]; signals?: Signal[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <div className="eyebrow mb-2">Chains involving this entity</div>
        {alerts.length === 0 && <p className="text-[12px] text-muted">None.</p>}
        <div className="space-y-1.5">
          {alerts.map((a) => (
            <Link key={a.id} href={`/cases/${a.id}`} className="flex items-center gap-2 rounded-md border border-line px-2.5 py-2 hover:border-line-strong">
              <PriorityPill p={a.priority} /><span className="num text-[11px] text-faint">{a.id}</span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-ink">{a.summary ?? a.claim}</span>
              <DimBars dims={a.dims} className="hidden sm:flex" />
            </Link>
          ))}
        </div>
      </div>
      {signals && (
        <div>
          <div className="eyebrow mb-2">Detector signals ({signals.length})</div>
          <div className="max-h-[320px] space-y-1 overflow-y-auto">
            {signals.map((s) => (
              <div key={s.id} className="flex gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-panel-2">
                <Chip tone="ai">{s.detector}</Chip><span className="min-w-0 flex-1 text-ink-2">{s.summary}</span><span className="num shrink-0 text-[11px] text-faint">{dayMonth(s.t)}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-faint">Signals are ingredients, not alerts. Most never join a chain.</p>
        </div>
      )}
    </div>
  );
}

// ── employee ───────────────────────────────────────────────────────────────

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Heat({ rates, title, flagHours }: { rates: number[]; title: string; flagHours?: Set<number> }) {
  const max = Math.max(...rates, 1e-9);
  return (
    <div>
      <div className="eyebrow mb-1.5">{title}</div>
      <div className="grid grid-cols-[28px_repeat(24,minmax(0,1fr))] gap-[2px]">
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} className="num text-center text-[8.5px] text-faint">{h % 6 === 0 ? h : ""}</span>)}
        {DAYS.map((d, di) => (
          <div key={d} className="contents">
            <span className="text-[10px] leading-[14px] text-faint">{d}</span>
            {Array.from({ length: 24 }, (_, h) => {
              const i = di * 24 + h, v = rates[i] ?? 0;
              return (
                <Tip key={h} content={`${d} ${String(h).padStart(2, "0")}:00 · ${pct(v, 2)} of sessions`}>
                  <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: (di * 24 + h) * 0.002 }}
                    className={cn("h-[14px] rounded-[2px]", flagHours?.has(i) && "ring-1 ring-threat")}
                    style={{ background: v ? `color-mix(in oklab, var(--info) ${Math.round(18 + (v / max) * 82)}%, transparent)` : "var(--panel-2)" }} />
                </Tip>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function UnmaskButton({ employee }: { employee: string }) {
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const post = usePost<{ employee_id: string; reason: string }, { id: string; status: string }>("/governance/unmask", [["unmask"]]);
  if (!me?.capabilities.includes("unmask:request")) return null;
  return (
    <Dialog.Root open={open} onOpenChange={(o) => { setOpen(o); if (!o) post.reset(); }}>
      <Dialog.Trigger asChild><Button variant="outline"><EyeOff size={14} /> Request unmask</Button></Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-black/50 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[81] w-[440px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line-strong bg-raised p-5 shadow-2xl">
          <Dialog.Title className="display text-[17px] font-semibold text-ink">Request the name behind {employee}</Dialog.Title>
          <Dialog.Description className="mt-1 text-[12.5px] text-muted">
            Staff stay pseudonymous by default. A second person with approval rights must agree; access lasts 4 hours and is written to the audit chain.
          </Dialog.Description>
          {post.data ? (
            <p className="mt-4 rounded-md bg-ok-soft px-3 py-2 text-[12.5px] text-ok">Request {post.data.id} is {post.data.status.toLowerCase()} — waiting for a second approver in Governance → Approvals.</p>
          ) : (
            <>
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="Why do you need the name? (at least 10 characters)"
                className="mt-4 w-full rounded-md border border-line-strong bg-panel p-2.5 text-[12.5px] text-ink outline-none focus:border-info" />
              {post.error && <p className="mt-2 text-[12px] text-threat">{post.error.message}</p>}
              <div className="mt-3 flex justify-end gap-2">
                <Dialog.Close asChild><Button variant="ghost">Cancel</Button></Dialog.Close>
                <Button variant="primary" disabled={reason.trim().length < 10 || post.isPending} onClick={() => post.mutate({ employee_id: employee, reason })}>Submit request</Button>
              </div>
            </>
          )}
          <Dialog.Close className="absolute right-3 top-3 rounded p-1 text-faint hover:bg-panel-2" aria-label="Close"><X size={15} /></Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function EmployeeView({ d }: { d: Employee }) {
  const b = d.baseline;
  const late = new Set(d.alibi.recent.filter((r) => r.verdict === "UNEXPLAINED").map((r) => {
    const t = new Date(r.t);
    const ist = new Date(t.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    return ((ist.getDay() + 6) % 7) * 24 + ist.getHours();
  }));
  const flagged = d.entitlements.filter((e) => e.flags.length);
  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="rhythm">Access rhythm</TabsTrigger>
        <TabsTrigger value="ents">Entitlements {flagged.length > 0 && <span className="ml-1 text-threat">{flagged.length}</span>}</TabsTrigger>
        <TabsTrigger value="alibi">Alibi</TabsTrigger>
        <TabsTrigger value="opened">Accounts opened</TabsTrigger>
        <TabsTrigger value="rel">Relationships</TabsTrigger>
        <TabsTrigger value="related">Chains & signals</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="mt-4">
        <div className="grid gap-3 md:grid-cols-4">
          {[
            { k: "Sessions in 90 days", v: b.sessions_90d, sub: `${b.after20_sessions} after 20:00 · peers ${pct(b.peer_after20_share, 2)}` },
            { k: "Accounts approved (60d)", v: b.approvals_60d, sub: `own baseline ${b.approvals_baseline_60d}`, hot: b.approvals_60d > b.approvals_baseline_60d * 2 },
            { k: "Alibi coverage", v: d.alibi.coverage * 100, f: (v: number) => `${v.toFixed(1)}%`, sub: `${d.alibi.unexplained} unexplained · ${d.alibi.partial} partial`, hot: d.alibi.unexplained > 0 },
            { k: "Flagged entitlements", v: flagged.length, sub: `of ${d.entitlements.length} held`, hot: flagged.some((e) => e.flags.includes("EXPIRED_BUT_ACTIVE")) },
          ].map((x) => (
            <Panel key={x.k} className={cn("p-3.5", x.hot && "border-threat/40")}>
              <div className="text-[11.5px] text-muted">{x.k}</div>
              <div className={cn("display mt-1 text-[24px] font-extrabold leading-none", x.hot ? "text-threat" : "text-ink")}><CountUp value={x.v} format={x.f} /></div>
              <div className="mt-1 text-[11px] text-faint">{x.sub}</div>
            </Panel>
          ))}
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <Fact k="Branch">{d.branch} · {d.card.branch_id}</Fact>
          <Fact k="Role">{d.card.role.replaceAll("_", " ").toLowerCase()}</Fact>
          <Fact k="Hired">{d.hire_date} · {d.tenure_years} years</Fact>
          <Fact k="Identity">{d.card.unmasked ? d.card.name : "pseudonymous"}</Fact>
        </div>
      </TabsContent>
      <TabsContent value="rhythm" className="mt-4">
        <div className="grid gap-5 xl:grid-cols-2">
          <Heat rates={b.hour_rates} title="This employee — share of sessions by hour of week" flagHours={late} />
          <Heat rates={b.peer_hour_rates} title="Peers in the same role" />
        </div>
        <p className="mt-3 text-[11.5px] text-muted">M1 compares each session against the employee&apos;s own rhythm, shrunk towards peers when history is thin. Red outlines mark hours with unexplained accesses.</p>
      </TabsContent>
      <TabsContent value="ents" className="mt-4">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[12px]">
            <thead><tr className="border-b border-line text-left">{["Permission", "Granted", "Reason", "Intended expiry", "Revoked", "Flags"].map((h) => <th key={h} className="px-2.5 py-2 eyebrow">{h}</th>)}</tr></thead>
            <tbody>
              {d.entitlements.slice().sort((a, z) => z.flags.length - a.flags.length).map((e) => (
                <tr key={e.id} className={cn("border-b border-line last:border-0", e.flags.includes("EXPIRED_BUT_ACTIVE") && "bg-threat-soft/30")}>
                  <td className="px-2.5 py-2 font-mono text-[11px] text-ink">{e.permission}</td>
                  <td className="num whitespace-nowrap px-2.5 py-2 text-muted">{dayMonth(e.valid_from)} · {e.granted_by}</td>
                  <td className="px-2.5 py-2 text-ink-2">{e.reason}{e.request_ref && <span className="num ml-1 text-faint">{e.request_ref}</span>}</td>
                  <td className="num whitespace-nowrap px-2.5 py-2 text-muted">{e.intended_expiry ? stamp(e.intended_expiry) : "—"}</td>
                  <td className="num whitespace-nowrap px-2.5 py-2 text-muted">{e.revoked_at ? stamp(e.revoked_at) : "—"}</td>
                  <td className="px-2.5 py-2"><div className="flex flex-wrap gap-1">{e.flags.map((f) => <Tip key={f} content={FLAG[f]?.why ?? f}><span><Chip tone={FLAG[f]?.tone ?? "faint"}>{FLAG[f]?.label ?? f}</Chip></span></Tip>)}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </TabsContent>
      <TabsContent value="alibi" className="mt-4">
        <div className="mb-3 flex flex-wrap gap-2 text-[12px]">
          <Chip tone="ok">{d.alibi.explained} explained</Chip><Chip tone="amber">{d.alibi.partial} partial</Chip><Chip tone="threat">{d.alibi.unexplained} unexplained</Chip>
          <Link href={`/alibi?employee=${d.id}`} className="ml-auto text-info hover:underline">Full ledger for {d.id}</Link>
        </div>
        <div className="space-y-1">
          {d.alibi.recent.map((r) => (
            <div key={r.access_id} className="flex items-center gap-3 rounded-md px-2 py-1.5 text-[12px] hover:bg-panel-2">
              <span className="num w-24 shrink-0 text-muted">{stamp(r.t)}</span><span className="w-32 shrink-0 font-mono text-[11px] text-ink">{r.action}</span>
              <span className="num w-16 text-ink-2">{r.account_id}</span><span className="text-faint">{r.reasons}/5 reasons</span>
              <Chip tone={r.verdict === "EXPLAINED" ? "ok" : r.verdict === "PARTIAL" ? "amber" : "threat"} className="ml-auto">{r.verdict.toLowerCase()}</Chip>
            </div>
          ))}
        </div>
      </TabsContent>
      <TabsContent value="opened" className="mt-4">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {d.approved_accounts.map((a) => (
            <Link key={a.id} href={`/entities/${a.id}`} className="rounded-md border border-line px-3 py-2 hover:border-line-strong">
              <div className="flex items-center justify-between"><span className="num text-[12.5px] text-ink">{a.id}</span><span className="num text-[11px] text-faint">{dayMonth(a.opened_at)}</span></div>
              <div className="mt-1 flex gap-1">{a.self_opened && <Chip tone="threat">opened & approved by same person</Chip>}<Chip tone="faint">{a.mode.toLowerCase()}</Chip></div>
            </Link>
          ))}
        </div>
      </TabsContent>
      <TabsContent value="rel" className="mt-4">
        {d.relationships.length === 0 && <p className="text-[12.5px] text-muted">No employee–customer links found.</p>}
        {d.relationships.map((r) => (
          <div key={r.customer_id} className="rounded-lg border border-line p-3">
            <div className="flex items-center gap-2 text-[12.5px]">
              <Users size={14} className="text-amber" /><Link href={`/entities/${r.customer_id}`} className="num text-ink hover:text-info">{r.customer_id}</Link>
              <Chip tone="amber">{r.type === "ER_MATCH" ? "entity-resolution match" : r.type.toLowerCase()}</Chip>
              {r.detail.declared ? <Chip tone="ok">declared</Chip> : <Chip tone="threat">not declared</Chip>}
            </div>
            <div className="mt-2 grid gap-1 sm:grid-cols-3">
              {Object.entries(r.detail.fields ?? {}).map(([k, v]) => (
                <div key={k} className="text-[12px]"><span className="text-faint">{k}: </span><span className={v.includes("match") && !v.startsWith("no") ? "text-amber" : "text-muted"}>{v}</span></div>
              ))}
            </div>
          </div>
        ))}
      </TabsContent>
      <TabsContent value="related" className="mt-4"><Related alerts={d.alerts} signals={d.signals} /></TabsContent>
    </Tabs>
  );
}

// ── account ────────────────────────────────────────────────────────────────

const money = (field: string, v: string) => (field === "TXN_LIMIT" && /^\d+$/.test(v) ? inr(Number(v) / 100) : v);

function AccountView({ d }: { d: Account }) {
  const maxCp = Math.max(...d.top_counterparties.map((c) => c.amount), 1);
  const timeline = [
    ...d.state_changes.map((s) => ({ t: s.t, kind: "change", text: `${s.field.replaceAll("_", " ").toLowerCase()}: ${money(s.field, s.old)} → ${money(s.field, s.new)}`, by: `${s.by} · ${s.auth.toLowerCase().replaceAll("_", " ")}`, hot: s.auth === "OVERRIDE" })),
    ...d.payees.map((p) => ({ t: p.t, kind: "payee", text: `new payee ${p.account} · ${p.name}`, by: "", hot: false })),
  ].sort((a, b) => a.t.localeCompare(b.t));
  return (
    <Tabs defaultValue="overview">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="changes">Changes & payees {timeline.length > 0 && <span className="ml-1 text-threat">{timeline.length}</span>}</TabsTrigger>
        <TabsTrigger value="flows">Flows</TabsTrigger>
        <TabsTrigger value="txns">Transactions</TabsTrigger>
        {d.mule && <TabsTrigger value="mule">Mule-likeness</TabsTrigger>}
        <TabsTrigger value="related">Chains & signals</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="mt-4">
        <div className="grid gap-4 md:grid-cols-4">
          <Fact k="Holder">{d.holder_name}</Fact>
          <Fact k="Bank · type">{d.bank} · {d.type.toLowerCase()}</Fact>
          <Fact k="Status">{d.status.toLowerCase()}{d.status_since && ` since ${dayMonth(d.status_since)}`}</Fact>
          <Fact k="Opened">{d.opened_at ? `${dayMonth(d.opened_at)} · ${d.opening_mode?.toLowerCase().replaceAll("_", " ")}` : "—"}</Fact>
          <Fact k="Balance">{inr(d.balance)}</Fact>
          <Fact k="Per-transaction limit">{inr(d.limit)}</Fact>
          <Fact k="Opened by">{d.opened_by ? <Link href={`/entities/${d.opened_by.id}`} className="hover:text-info">{d.opened_by.pseudonym}</Link> : "—"}</Fact>
          <Fact k="KYC approved by">{d.kyc_approved_by ? <Link href={`/entities/${d.kyc_approved_by.id}`} className="hover:text-info">{d.kyc_approved_by.pseudonym}</Link> : "—"}</Fact>
          {d.customer && <Fact k="Customer"><Link href={`/entities/${d.customer.id}`} className="num hover:text-info">{d.customer.id}</Link> · {d.customer.segment.toLowerCase()}</Fact>}
          <Fact k="Devices">{d.devices.map((x) => `${x.id} (${x.sessions})`).join(", ") || "—"}</Fact>
        </div>
        {d.opened_by && d.kyc_approved_by && d.opened_by.id === d.kyc_approved_by.id && (
          <p className="mt-3 flex items-center gap-1.5 text-[12px] text-threat"><AlertTriangle size={13} /> The same employee opened this account and approved its KYC.</p>
        )}
      </TabsContent>
      <TabsContent value="changes" className="mt-4">
        {timeline.length === 0 && <p className="text-[12.5px] text-muted">No contact, limit or payee changes in the window.</p>}
        <ol className="relative space-y-2 border-l border-line pl-4">
          {timeline.map((x, i) => (
            <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }} className="relative">
              <span className={cn("absolute -left-[21px] top-1.5 size-2.5 rounded-full border-2 border-bg", x.hot ? "bg-threat" : x.kind === "payee" ? "bg-amber" : "bg-info")} />
              <div className="num text-[11px] text-faint">{stamp(x.t)}</div>
              <div className="text-[12.5px] text-ink">{x.text}</div>
              {x.by && <div className={cn("text-[11px]", x.hot ? "text-threat" : "text-muted")}>{x.by}</div>}
            </motion.li>
          ))}
        </ol>
      </TabsContent>
      <TabsContent value="flows" className="mt-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Panel className="p-3.5"><div className="text-[11.5px] text-muted">Money in</div><div className="display text-[22px] font-bold text-ok">{inr(d.flows.in)}</div><div className="text-[11px] text-faint">{d.flows.in_count} credits</div></Panel>
          <Panel className="p-3.5"><div className="text-[11.5px] text-muted">Money out</div><div className="display text-[22px] font-bold text-threat">{inr(d.flows.out)}</div><div className="text-[11px] text-faint">{d.flows.out_count} debits</div></Panel>
        </div>
        <div className="eyebrow mb-2 mt-4">Top counterparties</div>
        <div className="space-y-2">
          {d.top_counterparties.map((c, i) => (
            <div key={c.account} className="flex items-center gap-3 text-[12px]">
              <Link href={`/entities/${c.account}`} className="num w-20 shrink-0 text-ink hover:text-info">{c.account}</Link>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-panel-2"><motion.div className="h-full bg-info" initial={{ width: 0 }} animate={{ width: `${(c.amount / maxCp) * 100}%` }} transition={{ delay: i * 0.06 }} /></div>
              <span className="num w-20 text-right text-ink">{inr(c.amount)}</span><span className="num w-10 text-right text-faint">×{c.count}</span>
            </div>
          ))}
        </div>
      </TabsContent>
      <TabsContent value="txns" className="mt-4">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-[12px]">
            <thead><tr className="border-b border-line text-left">{["When", "From → To", "Amount", "Channel", "Narration"].map((h) => <th key={h} className="px-2.5 py-2 eyebrow">{h}</th>)}</tr></thead>
            <tbody>
              {d.recent_txns.map((t) => {
                const out = t.from === d.id;
                return (
                  <tr key={t.id} className="border-b border-line last:border-0">
                    <td className="num whitespace-nowrap px-2.5 py-2 text-muted">{stamp(t.t)}</td>
                    <td className="num whitespace-nowrap px-2.5 py-2 text-ink">{t.from} → {t.to}</td>
                    <td className={cn("num whitespace-nowrap px-2.5 py-2 font-semibold", out ? "text-threat" : "text-ok")}>{out ? "−" : "+"}{inr(t.amount)}</td>
                    <td className="px-2.5 py-2 text-muted">{t.channel}</td><td className="px-2.5 py-2 text-ink-2">{t.narration}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </TabsContent>
      {d.mule && (
        <TabsContent value="mule" className="mt-4">
          <div className="flex items-baseline gap-3">
            <span className="display text-[28px] font-extrabold text-ai">{d.mule.p.toFixed(2)}</span>
            <span className="text-[12.5px] text-muted">M6 mule-likeness · model output, evidence grade C — never an alert on its own</span>
          </div>
          <div className="eyebrow mb-2 mt-4">Why (TreeSHAP, log-odds)</div>
          <div className="space-y-1.5">
            {d.mule.contributions.map((c, i) => {
              const max = Math.max(...d.mule!.contributions.map((x) => Math.abs(x.contribution)), 1e-9);
              return (
                <div key={c.feature} className="grid grid-cols-[200px_1fr_60px] items-center gap-3 text-[12px]">
                  <span className="text-ink-2">{c.label} <span className="num text-faint">= {Number.isInteger(c.value) ? c.value : c.value.toFixed(2)}</span></span>
                  <div className="h-2 overflow-hidden rounded-full bg-panel-2">
                    <motion.div className={cn("h-full", c.contribution >= 0 ? "bg-threat" : "bg-ok")} initial={{ width: 0 }} animate={{ width: `${(Math.abs(c.contribution) / max) * 100}%` }} transition={{ delay: i * 0.05 }} />
                  </div>
                  <span className="num text-right text-muted">{c.contribution >= 0 ? "+" : ""}{c.contribution.toFixed(2)}</span>
                </div>
              );
            })}
          </div>
        </TabsContent>
      )}
      <TabsContent value="related" className="mt-4"><Related alerts={d.alerts} signals={d.signals} /></TabsContent>
    </Tabs>
  );
}

// ── page ───────────────────────────────────────────────────────────────────

const KIND_ICON = { employee: UserCog, account: Wallet, customer: Users, device: Smartphone };

export default function EntityDossier() {
  const { id } = useParams<{ id: string }>();
  const { data: d, error, isLoading } = useGet<Dossier>(["entity", id], `/entities/${id}`);
  const Icon = d ? KIND_ICON[d.kind] ?? Building2 : Building2;
  const title = !d ? id : d.kind === "employee" ? d.card.pseudonym : d.kind === "account" ? d.holder_name : `${d.segment.charAt(0)}${d.segment.slice(1).toLowerCase()} customer`;

  return (
    <div className="mx-auto max-w-[1400px] p-5">
      <PageHeader eyebrow={`Investigate · Entity Explorer · ${d?.kind ?? "entity"}`}
        title={<span className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-lg bg-panel-2 text-muted"><Icon size={20} /></span>
          <span>{title}<span className="num ml-3 text-[15px] font-normal text-faint">{id}</span></span></span>}
        right={d && <>
          {d.kind === "employee" && !d.card.unmasked && <UnmaskButton employee={d.id} />}
          {d.kind === "account" && <ButtonLink href={`/trail?account=${d.id}`}><Activity size={14} /> Money trail</ButtonLink>}
          <ButtonLink href={`/network?entity=${id}`}><Network size={14} /> Risk network</ButtonLink>
          {"alerts" in d && d.alerts.find((a) => ["P1", "P2", "P3"].includes(a.priority)) && (
            <ButtonLink variant="primary" href={`/cases/${d.alerts.find((a) => ["P1", "P2", "P3"].includes(a.priority))!.id}`}>Open case <ArrowRight size={14} /></ButtonLink>
          )}
        </>} />
      {error && <ErrorBox error={error} />}
      {isLoading && <Skeleton className="h-[420px]" />}
      {d && (
        <Panel className="p-4">
          {d.kind === "employee" && (
            <div className="mb-4 flex flex-wrap items-center gap-2 text-[12px] text-muted">
              <Chip tone="faint">{d.card.role.replaceAll("_", " ").toLowerCase()}</Chip><Chip tone="faint">{d.card.branch_id}</Chip>
              {d.entitlements.some((e) => e.flags.includes("EXPIRED_BUT_ACTIVE")) && <Chip tone="threat"><KeyRound size={10} /> holds an expired, unrevoked privilege</Chip>}
              {!d.card.unmasked && <span className="flex items-center gap-1"><EyeOff size={12} /> name withheld — two-person unmask required</span>}
            </div>
          )}
          {d.kind === "employee" && <EmployeeView d={d} />}
          {d.kind === "account" && <AccountView d={d} />}
          {d.kind === "customer" && (
            <div className="space-y-5">
              <div className="grid gap-4 md:grid-cols-4">
                <Fact k="Segment">{d.segment.toLowerCase()}</Fact><Fact k="Branch">{d.branch_id}</Fact>
                <Fact k="Customer since">{dayMonth(d.created_at)} {new Date(d.created_at).getFullYear()}</Fact>
                <Fact k="Relationship manager">{d.rm ? <Link href={`/entities/${d.rm}`} className="hover:text-info">{d.rm}</Link> : "—"}</Fact>
              </div>
              <div>
                <div className="eyebrow mb-2">Accounts</div>
                <div className="flex flex-wrap gap-2">
                  {d.accounts.map((a) => (
                    <Link key={a.id} href={`/entities/${a.id}`} className="rounded-md border border-line px-3 py-2 text-[12.5px] hover:border-line-strong">
                      <span className="num text-ink">{a.id}</span> <Chip tone={a.status === "ACTIVE" ? "ok" : "amber"}>{a.status.toLowerCase()}</Chip> <span className="num ml-1 text-muted">{inr(a.balance)}</span>
                    </Link>
                  ))}
                </div>
              </div>
              <Related alerts={d.alerts} />
            </div>
          )}
        </Panel>
      )}
      {!d && !isLoading && !error && <Empty title="Not found" />}
    </div>
  );
}
