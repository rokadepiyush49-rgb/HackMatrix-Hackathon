"use client";

// Account Aggregator: ask the customer for consent, fetch the consented statement, revoke it. The data
// source is always on screen — a synthetic demo FIP must never be mistaken for a live bank feed.

import { useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Ban, Download, FileKey2, Landmark } from "lucide-react";
import { useState } from "react";

import { Button, Chip, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { api, useGet } from "@/lib/api";
import { stamp } from "@/lib/format";
import type { AAConsent } from "@/lib/types";

const SOURCE = {
  SYNTHETIC_DEMO: { label: "Synthetic demo data", tone: "amber" },
  SANDBOX: { label: "AA sandbox (mock FIP)", tone: "info" },
  LIVE: { label: "Live AA data", tone: "ok" },
} as const;
const STATUS_TONE = { PENDING: "amber", ACTIVE: "ok", REJECTED: "threat", REVOKED: "faint", EXPIRED: "faint" } as const;

interface AAStatus { provider: string; configured: boolean; data_source: keyof typeof SOURCE; note: string; data_life_days: number }

export function AccountAggregatorPanel({ customerId, alertId }: { customerId?: string | null; alertId: string }) {
  const qc = useQueryClient();
  const { data: status, error: statusErr } = useGet<AAStatus>(["aa-status"], "/aa/status", { staleTime: 60_000, retry: false });
  const { data: consents, isLoading } = useGet<AAConsent[]>(["aa-consents", customerId], customerId ? `/aa/consents?customer_id=${customerId}` : null,
    { retry: false });
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function act(path: string, body?: object, label?: string) {
    setBusy(path);
    setMsg(null);
    try {
      const out = await api<Record<string, unknown>>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
      const o = out.outcomes as Record<string, number> | undefined;
      if (o) setMsg(`${label}: ${o.NEW} new, ${o.DUPLICATE} already held, ${o.CONFLICT} conflicting${(out.rejected as unknown[])?.length ? `, ${(out.rejected as unknown[]).length} rejected` : ""}`);
      else if (label) setMsg(label);
      qc.invalidateQueries({ queryKey: ["aa-consents", customerId] });
      qc.invalidateQueries({ queryKey: ["council", alertId] });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(null);
    }
  }

  if (statusErr) return null; // not available outside demo mode without a configured provider
  const src = status ? SOURCE[status.data_source] : null;
  return (
    <Panel className="flex flex-col">
      <PanelHead eyebrow="Account Aggregator" title="Customer-consented statements"
        right={src && <Chip tone={src.tone}><Landmark size={11} /> {src.label}</Chip>} />
      <div className="space-y-3 px-4 pb-4">
        <p className="text-[12px] text-muted">
          With the customer&apos;s consent, fetch their statement from another bank for a source-of-funds check. It becomes
          evidence the Council can cite. It never changes a model score.
          {status && <> {status.note} Fetched data is deleted after {status.data_life_days} days or when consent is revoked.</>}
        </p>
        {!customerId && <p className="text-[12.5px] text-muted">This chain has no customer account to ask.</p>}
        {customerId && (
          <Button size="sm" variant="outline" disabled={!!busy || !status?.configured}
            onClick={() => act("/aa/consents", { customer_id: customerId, alert_id: alertId }, `Consent requested from ${customerId}`)}>
            <FileKey2 size={13} /> Request consent from {customerId}
          </Button>
        )}
        {isLoading && <Skeleton className="h-16" />}
        {consents?.map((c) => (
          <div key={c.id} className="rounded-lg border border-line p-3 text-[12px]">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="num text-ink">{c.id}</span>
              <Chip tone={STATUS_TONE[c.status]}>{c.status.toLowerCase()}</Chip>
              <Chip tone={SOURCE[c.data_source].tone}>{SOURCE[c.data_source].label}</Chip>
              <span className="ml-auto text-faint">{c.date_from} → {c.date_to}</span>
            </div>
            <p className="mt-1 text-muted">{c.purpose} · {c.rows} statement rows held{c.fetched_at ? ` · fetched ${stamp(c.fetched_at)}` : ""}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.status === "PENDING" && c.provider === "synthetic" && (
                <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act(`/aa/consents/${c.id}/approve`, {}, "Approved (demo stand-in for the customer's AA app)")}>
                  <BadgeCheck size={13} /> Approve as the customer (demo)
                </Button>
              )}
              {c.status === "PENDING" && c.redirect_url && (
                <a href={c.redirect_url} target="_blank" rel="noreferrer" className="text-[12px] text-info hover:underline">Customer approval page</a>
              )}
              {c.status === "ACTIVE" && (
                <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act(`/aa/consents/${c.id}/fetch`, {}, "Fetched")}>
                  <Download size={13} /> Fetch statement
                </Button>
              )}
              {(c.status === "ACTIVE" || c.status === "PENDING") && (
                <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act(`/aa/consents/${c.id}/revoke`, {}, "Revoked; fetched rows deleted")}>
                  <Ban size={13} /> Revoke
                </Button>
              )}
            </div>
          </div>
        ))}
        {msg && <p className="text-[12px] text-ink-2">{msg}</p>}
      </div>
    </Panel>
  );
}
