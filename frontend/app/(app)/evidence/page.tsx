"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown, Download, FileJson, FileSpreadsheet, FileText, Fingerprint, Loader2, PackagePlus, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { EvidenceChip } from "@/components/brief/evidence";
import { Button, Chip, Empty, ErrorBox, PageHeader, Panel, PanelHead, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { api, useCases, useGet } from "@/lib/api";
import { cn, inr, stamp } from "@/lib/format";
import { useParam } from "@/lib/params";
import type { AlertDetail, CaseFile, EvidenceItem } from "@/lib/types";

interface CaseDetail extends CaseFile { packs: { id: string; sha256: string; created_by: string; created_at: string; locked: boolean }[]; detail: AlertDetail }
interface StrDraft { title: string; sections: { title: string; sentences: { text: string; evidence: string[] }[] }[] }
interface Pack {
  id: string; case_id: string; sha256: string; locked: boolean; created_by: string; created_at: string;
  manifest: { files: Record<string, string>; items: { code: string; source: string; grade: string; sha256: string }[]; sections: string[]; bundle_sha256: string };
  bundle: { sections: Record<string, unknown>; str_draft: StrDraft; provenance: { detectors: Record<string, string>; as_of_snapshot: string; data_note: string } };
}
interface Verify { ok: boolean; files: Record<string, { expected: string; actual: string | null }>; items: { code: string; ok: boolean }[] }

function SectionBody({ k, v, pool }: { k: string; v: unknown; pool: EvidenceItem[] }) {
  if (Array.isArray(v)) {
    if (!v.length) return <p className="text-[12px] text-muted">Nothing recorded.</p>;
    if (typeof v[0] === "string") return <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-ink-2">{(v as string[]).map((x) => <li key={x}>{x}</li>)}</ul>;
    const rows = v as Record<string, unknown>[];
    if ("code" in rows[0] && "summary" in rows[0]) {
      return (
        <div className="space-y-1">
          {(rows as unknown as EvidenceItem[]).map((e) => (
            <div key={e.code} className="flex items-start gap-2 text-[12px]">
              <EvidenceChip code={e.code} pool={pool} /><span className="text-ink-2">{e.summary}</span>
              <span className="num ml-auto shrink-0 text-[10.5px] text-faint">{e.reliability}{e.credibility} · {e.source_system}</span>
            </div>
          ))}
        </div>
      );
    }
    if ("title" in rows[0] && "t" in rows[0]) {
      return (
        <div className="space-y-1">
          {rows.map((l, i) => (
            <div key={i} className="flex gap-2 text-[12px]"><span className="num w-24 shrink-0 text-faint">{stamp(String(l.t))}</span><span className="num w-8 shrink-0 text-info">{String(l.code)}</span><span className="text-ink-2"><b className="text-ink">{String(l.title)}</b> — {String(l.detail)}</span></div>
          ))}
        </div>
      );
    }
    if ("actor_name" in rows[0]) {
      return <div className="space-y-0.5">{rows.map((a, i) => <div key={i} className="num text-[11.5px] text-muted">{stamp(String(a.at))} · {String(a.actor_name)} · <span className="text-ink-2">{String(a.action)}</span></div>)}</div>;
    }
  }
  if (k === "01_executive_summary" && v && typeof v === "object") {
    const x = v as { claim: string; summary: string; priority: string; lattice_rule: string; amount_at_risk: number; attribution: { note: string } };
    return (
      <div className="space-y-1.5 text-[12.5px]">
        <p className="font-semibold text-ink">{x.claim}</p><p className="text-ink-2">{x.summary}</p>
        <p className="text-muted"><PriorityPill p={x.priority} /> <span className="ml-1">{x.lattice_rule}</span></p>
        <p className="text-muted">At risk {inr(x.amount_at_risk)} · Attribution: {x.attribution?.note}</p>
      </div>
    );
  }
  if (k === "10_control_recommendation") {
    const x = v as { id: string; name: string; why: string } | null;
    return x ? <p className="text-[12.5px] text-ink-2"><b className="text-ink">{x.id} · {x.name}</b> — {x.why}</p> : <p className="text-[12px] text-muted">No control applies.</p>;
  }
  if (k === "07_prosecution") {
    const x = v as { warrant: string; qualifier: string; grounds: { text: string; evidence: string[] }[] };
    return (
      <div className="space-y-1.5 text-[12.5px]">
        {x.grounds?.map((g, i) => <div key={i} className="flex flex-wrap items-start gap-1.5 text-ink-2">{g.text} {g.evidence?.map((c) => <EvidenceChip key={c} code={c} pool={pool} />)}</div>)}
        <p className="text-muted"><b>Warrant:</b> {x.warrant}</p><p className="text-muted"><b>Qualifier:</b> {x.qualifier}</p>
      </div>
    );
  }
  if (k === "08_defence") {
    const x = v as { rebuttals: { hypothesis: string; status: string; note?: string }[] };
    return <div className="space-y-1">{x.rebuttals?.map((r) => <div key={r.hypothesis} className="flex items-center gap-2 text-[12.5px]"><Chip tone={r.status === "open" ? "amber" : r.status === "supported" ? "ok" : "faint"}>{r.status}</Chip><span className="text-ink-2">{r.hypothesis}</span></div>)}</div>;
  }
  return <pre className="max-h-48 overflow-auto rounded bg-panel-2 p-2 text-[11px] text-muted">{JSON.stringify(v, null, 2)}</pre>;
}

function PackView({ id, pool }: { id: string; pool: EvidenceItem[] }) {
  const { data: p } = useGet<Pack>(["pack", id], `/packs/${id}`);
  const [open, setOpen] = useState<string | null>("01_executive_summary");
  const [ver, setVer] = useState<Verify | null>(null);
  const [checking, setChecking] = useState(false);
  if (!p) return <Skeleton className="h-96" />;
  const keys = Object.keys(p.bundle.sections).sort();
  const verify = async () => { setChecking(true); setVer(null); try { setVer(await api<Verify>(`/packs/${id}/verify`)); } finally { setChecking(false); } };

  return (
    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Panel>
        <PanelHead eyebrow={`${p.id} · ${stamp(p.created_at)} · by ${p.created_by}`} title="Evidence pack · 11 sections"
          right={<div className="flex gap-1.5">
            {([["pdf", FileText], ["json", FileJson], ["csv", FileSpreadsheet]] as const).map(([f, Icon]) => (
              <a key={f} href={`/api/sutra/packs/${id}/download?format=${f}`} download
                className="inline-flex h-7 items-center gap-1 rounded-md border border-line-strong px-2 text-[12px] text-ink hover:bg-panel-2"><Icon size={13} />{f.toUpperCase()}</a>
            ))}
          </div>} />
        <div className="px-4 pb-4">
          {keys.map((k, i) => {
            const on = open === k;
            const v = p.bundle.sections[k];
            const n = Array.isArray(v) ? v.length : null;
            return (
              <motion.div key={k} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }} className="border-b border-line last:border-0">
                <button onClick={() => setOpen(on ? null : k)} className="flex w-full items-center gap-3 py-2.5 text-left">
                  <span className="num grid size-7 place-items-center rounded-md bg-panel-2 text-[11px] text-muted">{k.slice(0, 2)}</span>
                  <span className="text-[13px] font-medium text-ink">{p.manifest.sections[i]}</span>
                  {n !== null && <span className="num text-[11px] text-faint">{n}</span>}
                  <ChevronDown size={14} className={cn("ml-auto text-faint transition-transform", on && "rotate-180")} />
                </button>
                <AnimatePresence initial={false}>
                  {on && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                      <div className="pb-3 pl-10"><SectionBody k={k} v={v} pool={pool} /></div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel>
          <PanelHead eyebrow="Integrity" title="Tamper-evident by construction"
            right={<Button size="sm" variant="outline" onClick={verify} disabled={checking}>{checking ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />} Verify</Button>} />
          <div className="space-y-2 px-4 pb-4 text-[12px]">
            <div className="flex items-center gap-2"><Fingerprint size={14} className="text-ai" /><span className="text-muted">Bundle SHA-256</span></div>
            <p className="num break-all rounded bg-panel-2 px-2 py-1.5 text-[11px] text-ink-2">{p.sha256}</p>
            {Object.entries(p.manifest.files).map(([f, h]) => {
              const r = ver?.files[f];
              return (
                <div key={f} className="flex items-center gap-2">
                  <span className="w-24 text-ink">{f}</span><span className="num min-w-0 flex-1 truncate text-faint">{h}</span>
                  {r && (r.expected === r.actual ? <Check size={14} className="text-ok" /> : <X size={14} className="text-threat" />)}
                </div>
              );
            })}
            <AnimatePresence>
              {ver && (
                <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  className={cn("rounded-md px-3 py-2 text-[12.5px]", ver.ok ? "bg-ok-soft text-ok" : "bg-threat-soft text-threat")}>
                  {ver.ok ? "Verified" : "Mismatch"} — files match their hashes and {ver.items.filter((i) => i.ok).length}/{ver.items.length} evidence items still match the live Loom records.
                </motion.div>
              )}
            </AnimatePresence>
            <p className="text-[11px] text-faint">{p.bundle.provenance.as_of_snapshot} · {p.bundle.provenance.data_note}</p>
          </div>
        </Panel>

        <Panel>
          <PanelHead eyebrow="Draft for FIU-IND" title="Suspicious Transaction Report — draft" right={<Chip tone="amber">needs a human signature</Chip>} />
          <div className="max-h-[440px] space-y-3 overflow-y-auto px-4 pb-4">
            <p className="text-[12.5px] font-semibold text-ink">{p.bundle.str_draft.title}</p>
            {p.bundle.str_draft.sections.map((s) => (
              <div key={s.title}>
                <div className="eyebrow mb-1">{s.title}</div>
                {s.sentences.map((x, i) => (
                  <p key={i} className="mb-1 text-[12px] leading-relaxed text-ink-2">{x.text} {x.evidence.map((c) => <EvidenceChip key={c} code={c} pool={pool} className="ml-0.5" />)}</p>
                ))}
              </div>
            ))}
            <p className="text-[11px] text-faint">Every sentence cites evidence; anything the verifier could not tie to a record was dropped.</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Packs() {
  const [caseId, setCase] = useParam("case");
  const { data: cases } = useCases();
  const qc = useQueryClient();
  const current = caseId ?? cases?.[0]?.id;
  const { data: c, error } = useGet<CaseDetail>(["case", current], current ? `/cases/${current}` : null);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const latest = c?.packs.slice().sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  const generate = async () => {
    if (!current) return;
    setCreating(true); setErr(null);
    try { await api(`/cases/${current}/packs`, { method: "POST" }); await qc.invalidateQueries({ queryKey: ["case", current] }); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setCreating(false); }
  };

  return (
    <div className="mx-auto max-w-[1600px] p-5">
      <PageHeader eyebrow="Evidence · Evidence Packs" title="A pack a regulator, auditor or court can check"
        sub="Every pack is generated from the same evidence book the investigator saw, hashed per item and per file, and written to the audit chain. Re-verify at any time: if a record changed, the pack says so." />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Panel className="h-fit">
          <PanelHead eyebrow="Cases" title="Choose a case" />
          <div className="px-2 pb-2">
            {cases?.length === 0 && <p className="px-2 py-3 text-[12px] text-muted">No cases yet. Open one from the <Link href="/signals" className="text-info">Signal Desk</Link>.</p>}
            {cases?.map((x) => (
              <button key={x.id} onClick={() => setCase(x.id)} className={cn("w-full rounded-md px-2.5 py-2 text-left hover:bg-panel-2", x.id === current && "bg-panel-2 ring-1 ring-info/40")}>
                <div className="flex items-center gap-2"><PriorityPill p={x.priority} /><span className="num text-[11px] text-faint">{x.id}</span></div>
                <div className="mt-1 line-clamp-2 text-[12px] text-ink">{x.title}</div>
              </button>
            ))}
          </div>
        </Panel>
        <div>
          {error && <ErrorBox error={error} />}
          {current && !c && !error && <Skeleton className="h-96" />}
          {c && (
            <>
              <Panel className="mb-4 flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="eyebrow">{c.id} · {c.state.toLowerCase()}</div>
                  <div className="truncate text-[14px] font-semibold text-ink">{c.title}</div>
                  <div className="text-[12px] text-muted">{c.packs.length} pack{c.packs.length === 1 ? "" : "s"} generated · {c.detail.evidence.length} evidence items</div>
                </div>
                <Button variant="primary" onClick={generate} disabled={creating}>
                  {creating ? <><Loader2 size={14} className="animate-spin" /> Assembling…</> : <><PackagePlus size={14} /> Generate new pack</>}
                </Button>
                {err && <p className="w-full text-[12px] text-threat">{err}</p>}
              </Panel>
              {latest ? <PackView key={latest.id} id={latest.id} pool={c.detail.evidence} /> : (
                <Panel><Empty title="No pack yet" icon={<Download size={26} />}>Generate the first pack for this case — PDF, JSON and CSV with a SHA-256 manifest.</Empty></Panel>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function EvidencePacks() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[480px]" /></div>}><Packs /></Suspense>;
}
