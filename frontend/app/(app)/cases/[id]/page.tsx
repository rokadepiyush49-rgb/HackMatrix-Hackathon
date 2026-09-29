"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Clock, FileStack, Gavel, Landmark, ShieldCheck, Sparkles, UserCheck, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AlibiResolution, EvidenceTable, MissingEvidence, ProsecutionDefence, WhySuspicious } from "@/components/brief/brief";
import { ChainRail, LaneLegend, type RailNode } from "@/components/chain/chain-rail";
import { TimelineReplay } from "@/components/chain/timeline-replay";
import { EntityGraph } from "@/components/graph/entity-graph";
import { useUI } from "@/components/shell/ui-context";
import { Button, Chip, ErrorBox, Panel, PanelHead, PriorityPill, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, useAlert, useGet, useMe, useOpenCase, useReplay } from "@/lib/api";
import { cn, duration, hhmm, inr, stamp } from "@/lib/format";
import type { AuditEntry, CaseFile, ChainLink } from "@/lib/types";

interface CaseDetail extends CaseFile {
  notes: { id: string; author: string; body: string; evidence_refs: string[]; created_at: string }[];
  packs: { id: string; sha256: string; created_by: string; created_at: string; locked: boolean }[];
  activity: AuditEntry[];
}

function SlaClock({ due }: { due: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!due) return null;
  const left = (new Date(due).getTime() - now) / 1000;
  return (
    <Chip tone={left < 0 ? "threat" : left < 1800 ? "amber" : "faint"}>
      <Clock size={11} /> SLA {left < 0 ? `breached ${duration(-left)} ago` : `${duration(left)} left`}
    </Chip>
  );
}

function DecisionDialog({ c, onDone }: { c: CaseDetail; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [decision, setDecision] = useState("ESCALATE");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const { data: me } = useMe();
  const canReview = me?.capabilities.includes("cases:review") && me.id !== c.assignee;
  const canPropose = me?.capabilities.includes("cases:propose") && me.id === c.assignee;

  async function propose() {
    setErr(null);
    try {
      await api(`/cases/${c.id}/propose`, { method: "POST", body: JSON.stringify({ decision, reason }) });
      setOpen(false);
      onDone();
    } catch (e) { setErr((e as Error).message); }
  }
  async function review(approve: boolean) {
    setErr(null);
    try {
      await api(`/cases/${c.id}/review`, { method: "POST", body: JSON.stringify({ approve, note: "" }) });
      onDone();
    } catch (e) { setErr((e as Error).message); }
  }

  if (c.state === "REVIEW") {
    return (
      <div className="flex items-center gap-2">
        <Chip tone="amber"><UserCheck size={11} /> Awaiting four-eyes review · {c.decision}</Chip>
        {canReview ? (
          <>
            <Button size="sm" variant="danger" onClick={() => review(true)}>Approve {c.decision?.toLowerCase()}</Button>
            <Button size="sm" onClick={() => review(false)}>Return</Button>
          </>
        ) : <span className="text-[11.5px] text-muted">A different reviewer must approve</span>}
        {err && <span className="text-[11.5px] text-threat">{err}</span>}
      </div>
    );
  }
  if (c.state.startsWith("CLOSED")) return <Chip tone="ok">{c.state.replace("CLOSED_", "Closed · ").toLowerCase()} · reviewed by {c.reviewer_name}</Chip>;
  if (!canPropose) return <span className="text-[11.5px] text-muted">Investigating · {c.assignee_name ?? "unassigned"} proposes the decision</span>;

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild><Button size="sm" variant="primary"><Gavel size={13} /> Propose decision</Button></Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[81] w-[480px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line-strong bg-raised p-5 shadow-2xl">
          <Dialog.Title className="display text-[18px] font-bold text-ink">Propose a decision</Dialog.Title>
          <Dialog.Description className="mt-1 text-[12.5px] text-muted">Four-eyes rule: a different reviewer must approve before the case closes. Nothing is actioned against a person automatically.</Dialog.Description>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[["ESCALATE", "Escalate", "STR · staff action"], ["UNPROVEN", "Unproven", "Watch-list 90 days"], ["BENIGN", "Benign", "Explained"]].map(([v, l, s]) => (
              <button key={v} onClick={() => setDecision(v)}
                className={cn("rounded-lg border p-2.5 text-left", decision === v ? (v === "ESCALATE" ? "border-threat bg-threat-soft" : v === "BENIGN" ? "border-ok bg-ok-soft" : "border-amber bg-amber-soft") : "border-line")}>
                <div className="text-[13px] font-semibold text-ink">{l}</div>
                <div className="text-[11px] text-muted">{s}</div>
              </button>
            ))}
          </div>
          <textarea id="decision-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="Reason, citing evidence codes (e.g. EV-103, EV-111)…"
            className="mt-3 w-full rounded-md border border-line bg-panel p-2.5 text-[13px] text-ink outline-none focus:border-info" />
          {err && <p className="mt-2 text-[12px] text-threat">{err}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close asChild><Button size="sm" variant="ghost">Cancel</Button></Dialog.Close>
            <Button size="sm" variant="primary" disabled={reason.trim().length < 3} onClick={propose}>Send for review</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function CaseCanvas() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { openAsk, setFocusAlert } = useUI();
  const { data: a, error } = useAlert(id);
  const { data: replay } = useReplay(id);
  const openCase = useOpenCase();
  const [caseId, setCaseId] = useState<string | null>(null);
  const { data: c, refetch } = useGet<CaseDetail>(["case", caseId], caseId ? `/cases/${caseId}` : null);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [tab, setTab] = useState("why");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!id) return;
    setFocusAlert(id);
    openCase.mutate(id, { onSuccess: (cf) => setCaseId(cf.id) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const accessLink: ChainLink | undefined = useMemo(() => a?.links.find((l) => l.alibi && (l.code === "E2" || l.code === "E3")), [a]);
  const lead = a?.headline.enabling_privilege_lead_s;

  if (error) return <div className="p-6"><ErrorBox error={error} /></div>;
  if (!a) return <div className="space-y-4 p-5"><Skeleton className="h-16" /><Skeleton className="h-40" /><Skeleton className="h-[420px]" /></div>;

  const onRail = (n: RailNode) => {
    setActive(n.code);
    const t = n.links.at(-1)?.t;
    if (t) setAsOf(t);
  };

  async function addNote() {
    if (!caseId || !note.trim()) return;
    const refs = Array.from(note.matchAll(/EV-\d+/g)).map((m) => m[0]);
    await api(`/cases/${caseId}/notes`, { method: "POST", body: JSON.stringify({ body: note, evidence_refs: refs }) });
    setNote("");
    refetch();
  }

  return (
    <div className="mx-auto max-w-[1560px] space-y-4 p-5">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="num text-[12px] text-muted">{c?.id ?? "CASE-…"} · {a.id} · {a.chain_id}</span>
            <PriorityPill p={a.priority} />
            <Chip tone="threat">{inr(a.amount_at_risk)} at risk</Chip>
            <Chip tone="faint">{a.typology_label}</Chip>
            {c && <SlaClock due={c.sla_due_at} />}
          </div>
          <h1 className="display mt-1.5 max-w-[95ch] text-[21px] font-bold leading-snug text-ink">{a.claim}</h1>
          {a.employee && (
            <div className="mt-1 text-[12px] text-muted">
              Subject: <Link href={`/entities/${a.employee.id}`} className="num text-ink hover:underline">{a.employee.id}</Link> · {a.employee.pseudonym}
              {!a.employee.unmasked && <span className="ml-1 text-faint">(pseudonymous — unmasking needs two approvers)</span>}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="ai" onClick={() => openAsk(a.id)}><Sparkles size={13} /> Ask SUTRA</Button>
          <Button size="sm" onClick={() => router.push(`/council/${a.id}`)}><Landmark size={13} /> Council</Button>
          <Button size="sm" onClick={() => router.push(`/controls?alert=${a.id}`)}><ShieldCheck size={13} /> Control Lab</Button>
          <Button size="sm" onClick={() => router.push(`/evidence?case=${c?.id ?? ""}&alert=${a.id}`)}><FileStack size={13} /> Evidence pack</Button>
          {c && <DecisionDialog c={c} onDone={() => { refetch(); qc.invalidateQueries({ queryKey: ["alerts"] }); }} />}
        </div>
      </div>

      {/* chain rail */}
      <Panel className="px-4 pb-3 pt-4">
        <ChainRail links={a.links} latencyS={a.latency_s} leadS={lead} activeCode={active} onSelect={onRail} asOf={asOf} />
        <div className="mt-1 flex items-center justify-between">
          <LaneLegend />
          <span className="text-[11.5px] text-muted">Click a link to jump the replay to it</span>
        </div>
      </Panel>

      {/* graph + brief */}
      <div className="grid gap-4 xl:grid-cols-[1.25fr_1fr]">
        <Panel className="flex flex-col overflow-hidden">
          <PanelHead eyebrow={asOf ? `Graph as of ${stamp(asOf)}` : "Graph · full chain"} title="Who and what the chain touches"
            right={asOf && <Button size="sm" variant="ghost" onClick={() => setAsOf(null)}>Show all</Button>} />
          <div className="h-[520px] border-t border-line">
            {replay ? (
              <EntityGraph nodes={replay.nodes} edges={replay.edges} asOf={asOf} particles
                onNodeClick={(n) => ["account", "employee", "device", "customer", "external"].includes(n.kind) && router.push(`/entities/${n.id}`)} />
            ) : <Skeleton className="m-4 h-[480px]" />}
          </div>
        </Panel>

        <Panel className="flex max-h-[600px] flex-col overflow-hidden">
          <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
            <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-3.5">
              <TabsList>
                <TabsTrigger value="why">Why suspicious?</TabsTrigger>
                <TabsTrigger value="argue">Prosecution · Defence</TabsTrigger>
                <TabsTrigger value="alibi">Alibi</TabsTrigger>
                <TabsTrigger value="evidence">Evidence {a.evidence.length}</TabsTrigger>
                <TabsTrigger value="missing">Missing</TabsTrigger>
              </TabsList>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto border-t border-line px-4 py-3">
              <AnimatePresence mode="wait">
                <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                  <TabsContent value="why" forceMount={tab === "why" ? true : undefined}>{tab === "why" && <WhySuspicious a={a} />}</TabsContent>
                  <TabsContent value="argue">{tab === "argue" && <ProsecutionDefence a={a} />}</TabsContent>
                  <TabsContent value="alibi">
                    {tab === "alibi" && (accessLink?.alibi ? (
                      <div className="space-y-3">
                        <AlibiResolution card={accessLink.alibi} title={`Alibi for ${accessLink.code} · ${accessLink.title} (${hhmm(accessLink.t)})`} />
                        {a.links.filter((l) => l.alibi && l.id !== accessLink.id).map((l) => (
                          <AlibiResolution key={l.id} card={l.alibi!} title={`${l.code} · ${l.title} (${hhmm(l.t)})`} />
                        ))}
                      </div>
                    ) : <p className="text-[12.5px] text-muted">No staff access in this chain — Alibi does not apply.</p>)}
                  </TabsContent>
                  <TabsContent value="evidence">{tab === "evidence" && <EvidenceTable items={a.evidence} />}</TabsContent>
                  <TabsContent value="missing">{tab === "missing" && <MissingEvidence a={a} />}</TabsContent>
                </motion.div>
              </AnimatePresence>
            </div>
          </Tabs>
        </Panel>
      </div>

      {/* timeline replay */}
      <Panel className="px-4 pb-4 pt-3.5">
        <div className="eyebrow mb-2">Timeline replay</div>
        {replay ? <TimelineReplay replay={replay} asOf={asOf} onAsOf={setAsOf} /> : <Skeleton className="h-40" />}
      </Panel>

      {/* notes & activity */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHead eyebrow="Investigator notes" title="Notes cite evidence codes" />
          <div className="space-y-2 px-4 pb-4">
            {c?.notes.map((n) => (
              <div key={n.id} className="rounded-md border border-line px-3 py-2 text-[12.5px] text-ink-2">
                <div className="mb-0.5 flex items-center gap-2 text-[11px] text-faint"><span className="text-ink">{n.author}</span> {stamp(n.created_at)}</div>
                {n.body}
              </div>
            ))}
            <div className="flex gap-2">
              <input id="case-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Override used after expiry (EV-103); customer contact pending"
                className="h-9 flex-1 rounded-md border border-line bg-panel px-3 text-[12.5px] text-ink outline-none focus:border-info" />
              <Button size="sm" onClick={addNote} disabled={!note.trim()}>Add note</Button>
            </div>
          </div>
        </Panel>
        <Panel>
          <PanelHead eyebrow="Who saw this case?" title="Hash-chained activity" />
          <div className="max-h-[240px] space-y-1 overflow-y-auto px-4 pb-4">
            {c?.activity.map((x) => (
              <div key={x.id} className="grid grid-cols-[110px_1fr_auto] items-center gap-2 border-b border-line py-1.5 text-[12px] last:border-0">
                <span className="num text-faint">{stamp(x.at)}</span>
                <span className="text-ink-2"><b className="text-ink">{x.actor_name}</b> · {x.action.replace(".", " ")}</span>
                <span className="num text-[10px] text-faint">#{x.hash}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
