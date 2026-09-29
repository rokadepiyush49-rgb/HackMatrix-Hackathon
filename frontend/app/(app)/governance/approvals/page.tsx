"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, Clock, EyeOff, ShieldAlert, X } from "lucide-react";
import Link from "next/link";

import { Button, Chip, Empty, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useCases, useGet, useMe, usePost } from "@/lib/api";
import { stamp } from "@/lib/format";

interface Unmask { id: string; employee_id: string; case_id: string | null; requested_by: string; reason: string; status: string; approved_by: string | null; created_at: string; expires_at: string | null }

function Decide({ u }: { u: Unmask }) {
  const post = usePost<{ approve: boolean }, { status: string }>(`/governance/unmask/${u.id}/decide`, [["unmask"], ["audit", null]]);
  return (
    <div className="flex items-center gap-2">
      {post.error && <span className="max-w-[260px] text-[11.5px] text-threat">{post.error.message}</span>}
      <Button size="sm" variant="ghost" disabled={post.isPending} onClick={() => post.mutate({ approve: false })}><X size={13} /> Reject</Button>
      <Button size="sm" variant="primary" disabled={post.isPending} onClick={() => post.mutate({ approve: true })}><Check size={13} /> Approve 4 h</Button>
    </div>
  );
}

export default function Approvals() {
  const { data: me } = useMe();
  const { data: unmask, error } = useGet<Unmask[]>(["unmask"], "/governance/unmask");
  const { data: cases } = useCases();
  const canApprove = me?.capabilities.includes("unmask:approve");
  const review = cases?.filter((c) => c.state === "REVIEW") ?? [];
  const pending = unmask?.filter((u) => u.status === "PENDING") ?? [];
  const done = unmask?.filter((u) => u.status !== "PENDING") ?? [];

  return (
    <div className="mx-auto max-w-[1400px] p-5">
      <PageHeader eyebrow="Governance · Approvals" title="Two people, every time it matters"
        sub="Closing a case and revealing an employee's name both need a second person. The API refuses the same person on both sides — try it." />
      {error && <ErrorBox error={error} />}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHead eyebrow={`Unmask requests · ${pending.length} pending`} title="Reveal a pseudonymous employee" />
          <div className="space-y-2 px-4 pb-4">
            {!unmask && <Skeleton className="h-32" />}
            {unmask && unmask.length === 0 && <Empty title="No requests" icon={<EyeOff size={24} />}>Request one from an employee dossier.</Empty>}
            <AnimatePresence initial={false}>
              {[...pending, ...done].map((u) => (
                <motion.div key={u.id} layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="rounded-lg border border-line p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="num text-[11px] text-faint">{u.id}</span>
                    <Link href={`/entities/${u.employee_id}`} className="num text-[12.5px] font-semibold text-ink hover:text-info">{u.employee_id}</Link>
                    <Chip tone={u.status === "APPROVED" ? "ok" : u.status === "REJECTED" ? "threat" : "amber"}>{u.status.toLowerCase()}</Chip>
                    <span className="ml-auto text-[11px] text-faint">by {u.requested_by} · {stamp(u.created_at)}</span>
                  </div>
                  <p className="mt-1.5 text-[12.5px] text-ink-2">“{u.reason}”</p>
                  {u.status === "PENDING" ? (
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                      {me?.id === u.requested_by
                        ? <span className="flex items-center gap-1 text-[11.5px] text-amber"><ShieldAlert size={12} /> You raised this — a different approver must decide.</span>
                        : <span className="text-[11.5px] text-muted">Approving reveals the name for 4 hours and is audited.</span>}
                      {canApprove ? <Decide u={u} /> : <span className="text-[11.5px] text-faint">Your role cannot approve unmasks.</span>}
                    </div>
                  ) : (
                    <p className="mt-1 text-[11.5px] text-muted">{u.status.toLowerCase()} by {u.approved_by}{u.expires_at && <> · <Clock size={11} className="inline" /> until {stamp(u.expires_at)}</>}</p>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </Panel>
        <Panel>
          <PanelHead eyebrow={`Case decisions · ${review.length} awaiting review`} title="Four-eyes on every closure" />
          <div className="space-y-2 px-4 pb-4">
            {review.length === 0 && <p className="text-[12.5px] text-muted">No proposed decisions are waiting. When an investigator proposes one, it appears here for a second reviewer.</p>}
            {review.map((c) => (
              <Link key={c.id} href={`/cases/${c.alert_id}`} className="block rounded-lg border border-line p-3 hover:border-line-strong">
                <div className="flex items-center gap-2"><span className="num text-[11px] text-faint">{c.id}</span><Chip tone="ai">{c.decision ?? "proposed"}</Chip><span className="ml-auto text-[11px] text-faint">by {c.assignee_name}</span></div>
                <p className="mt-1 text-[12.5px] text-ink">{c.title}</p>
                {c.decision_reason && <p className="mt-1 text-[12px] text-muted">“{c.decision_reason}”</p>}
              </Link>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
