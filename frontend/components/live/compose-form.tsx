"use client";

// "Your input": a person acts as a member of staff. Every choice here becomes source rows — the
// sessions, audit entries, state changes, tickets, payees and transfers the bank's systems would
// record — previewed live and then sent through the same ingest and detection as tonight's feed.

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FileText, Fingerprint, Laptop, Send, Smartphone, Store, UserRound, Wallet } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button, Chip, Panel, PanelHead } from "@/components/ui/primitives";
import { api, ApiError, useGet } from "@/lib/api";
import { cn, inr } from "@/lib/format";
import type { ComposeOptions, ComposePreview, ComposeSpec } from "@/lib/types";

type Choices = Omit<ComposeSpec, "employee_id" | "account_id">;

export const PRESETS: { key: string; label: string; hint: string; spec: Choices }[] = [
  {
    key: "insider", label: "Insider takeover", hint: "After hours from home, an expired override, money to the 21 Sep ring",
    spec: { at: "21:20", channel: "VPN", auth: "OVERRIDE", expired_grant: true, ticket: false, ekyc: false, rostered: false,
      change_mobile: true, raise_limit_to: 500000, takeover: true, payees: ["A-7731", "A-7768"], amount: 400000,
      delay_min: 38, ring_reacts: true },
  },
  {
    key: "camp", label: "Legitimate camp update", hint: "The same mobile change — with a camp roster, a ticket and the customer present",
    spec: { at: "19:10", channel: "BRANCH", auth: "BIOMETRIC", expired_grant: false, ticket: true, ekyc: true, rostered: true,
      change_mobile: true, raise_limit_to: null, takeover: false, payees: [], amount: 50000, delay_min: 38, ring_reacts: false },
  },
  {
    key: "forged", label: "Forged ticket", hint: "The insider files a service ticket first. Does paperwork fool SUTRA?",
    spec: { at: "21:20", channel: "VPN", auth: "OVERRIDE", expired_grant: true, ticket: true, ekyc: false, rostered: false,
      change_mobile: true, raise_limit_to: 500000, takeover: true, payees: ["A-7731", "A-7768"], amount: 400000,
      delay_min: 38, ring_reacts: true },
  },
  {
    key: "quiet", label: "Quiet daytime takeover", hint: "Office hours, no override, ₹90,000 to an outside account",
    spec: { at: "11:40", channel: "BRANCH", auth: "MAKER_ONLY", expired_grant: false, ticket: false, ekyc: false, rostered: false,
      change_mobile: true, raise_limit_to: null, takeover: true, payees: ["OUTSIDE"], amount: 90000, delay_min: 50,
      ring_reacts: false },
  },
];

function initial(o: ComposeOptions): ComposeSpec {
  const account = o.accounts[0];
  const free = o.staff.filter((s) => !s.in_story);
  const staff = free.find((s) => s.branch_id === account?.branch_id) ?? free[0] ?? o.staff[0];
  return { employee_id: staff?.id ?? "", account_id: account?.id ?? "", ...PRESETS[0].spec };
}

function useDebounced(value: string, ms: number): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function ComposeForm({ busy, onSend }: { busy: boolean; onSend: (spec: ComposeSpec) => Promise<void> }) {
  const options = useGet<ComposeOptions>(["compose-options"], "/live/compose/options", { staleTime: 30_000 });
  const [form, setForm] = useState<ComposeSpec | null>(null);
  const [preset, setPreset] = useState<string | null>("insider");
  const [showRows, setShowRows] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const o = options.data;
  const spec = form ?? (o ? initial(o) : null);
  const set = (patch: Partial<ComposeSpec>) => {
    if (!spec) return;
    setForm({ ...spec, ...patch });
    setPreset(null);
    setSendError(null);
  };
  const applyPreset = (key: string) => {
    const p = PRESETS.find((x) => x.key === key);
    if (!spec || !p) return;
    setForm({ ...spec, ...p.spec });
    setPreset(key);
    setSendError(null);
  };

  const key = useDebounced(spec ? JSON.stringify(spec) : "", 300);
  const preview = useQuery<ComposePreview, ApiError>({
    queryKey: ["compose-preview", key],
    queryFn: () => api<ComposePreview>("/live/compose?dry_run=true", { method: "POST", body: key }),
    enabled: !!key,
    placeholderData: (prev) => prev,
    retry: false,
  });

  if (!o || !spec) {
    return <Panel className="min-h-[640px] p-5 text-[13px] text-muted">{options.error ? options.error.message : "Loading the bank…"}</Panel>;
  }
  const account = o.accounts.find((a) => a.id === spec.account_id);
  const staff = o.staff.find((s) => s.id === spec.employee_id);
  const known = (account?.payees ?? 0) > 0;
  const total = spec.amount * spec.payees.length;
  const invalid = preview.error?.message;

  return (
    <Panel className="flex flex-col">
      <PanelHead eyebrow="Your input · you act as a member of staff" title="What happens at the bank tonight?" />

      <div className="grid grid-cols-2 gap-1.5 px-4 pb-3">
        {PRESETS.map((p) => (
          <button key={p.key} onClick={() => applyPreset(p.key)} aria-pressed={preset === p.key}
            className={cn("rounded-lg border px-2.5 py-2 text-left transition-colors",
              preset === p.key ? "border-ink bg-ink text-bg" : "border-line bg-panel hover:bg-panel-2")}>
            <div className="text-[12.5px] font-semibold">{p.label}</div>
            <div className={cn("mt-0.5 text-[11px] leading-snug", preset === p.key ? "text-bg/75" : "text-muted")}>{p.hint}</div>
          </button>
        ))}
      </div>

      <div className="space-y-3 border-t border-line px-4 py-3">
        <Section n={1} icon={<UserRound size={13} />} title="Who logs in, and when">
          <Field label="Member of staff">
            <select value={spec.employee_id} onChange={(e) => set({ employee_id: e.target.value })} className={SELECT}>
              {o.staff.map((s) => (
                <option key={s.id} value={s.id}>{s.id} · {s.pseudonym}{s.in_story ? " · already in a case" : ""}</option>
              ))}
            </select>
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={spec.channel} onChange={(v) => set({ channel: v as ComposeSpec["channel"] })}
              items={[["VPN", <><Laptop size={12} /> VPN from home</>], ["BRANCH", <><Store size={12} /> Branch terminal</>]]} />
            <input type="time" value={spec.at} onChange={(e) => e.target.value && set({ at: e.target.value })} aria-label="Login time"
              className="num h-8 rounded-md border border-line bg-panel px-2 text-[12.5px] text-ink" />
            <span className="text-[11px] text-faint">22 Sep · {spec.channel === "VPN" ? staff?.laptop : staff?.terminal ?? "terminal"}</span>
          </div>
        </Section>

        <Section n={2} icon={<FileText size={13} />} title="Paperwork on file">
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            <Toggle on={spec.ticket} onChange={(v) => set({ ticket: v })} label="Service ticket for this customer" />
            <Toggle on={spec.ekyc || spec.auth === "BIOMETRIC"} onChange={(v) => set({ ekyc: v, auth: !v && spec.auth === "BIOMETRIC" ? "MAKER_ONLY" : spec.auth })}
              label="Customer present (biometric eKYC)" />
            <Toggle on={spec.rostered} onChange={(v) => set({ rostered: v })} label="Rostered — evening camp shift" />
            <Toggle on={spec.expired_grant} onChange={(v) => set({ expired_grant: v })} label="Old override grant (expired 18 Sep)" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11.5px] text-muted">Change authorised by</span>
            <Segmented value={spec.auth} onChange={(v) => set({ auth: v as ComposeSpec["auth"], ekyc: v === "BIOMETRIC" ? true : spec.ekyc })}
              items={[["OVERRIDE", "Override, no OTP"], ["MAKER_ONLY", "Maker only"], ["BIOMETRIC", <><Fingerprint size={12} /> Biometric</>]]} />
          </div>
        </Section>

        <Section n={3} icon={<Smartphone size={13} />} title="What changes on the account">
          <Field label="Customer account">
            <select value={spec.account_id} onChange={(e) => set({ account_id: e.target.value })} className={SELECT}>
              {o.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.id} · {a.holder} · {a.status === "INOPERATIVE" ? "dormant" : a.segment.toLowerCase()} · {inr(a.balance)} · {a.branch_id}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            <Toggle on={spec.change_mobile} onChange={(v) => set({ change_mobile: v })} label="Change the registered mobile" />
            <Toggle on={spec.takeover} onChange={(v) => set({ takeover: v })} label="Accomplice: new phone + password reset" />
            <div className="flex items-center gap-2 sm:col-span-2">
              <Toggle on={spec.raise_limit_to != null} onChange={(v) => set({ raise_limit_to: v ? 500000 : null })} label="Raise the daily limit to" />
              {spec.raise_limit_to != null && (
                <RupeeInput value={spec.raise_limit_to} onChange={(v) => set({ raise_limit_to: v })} min={10000} max={5000000} />
              )}
              {account && <span className="text-[11px] text-faint">now {inr(account.daily_limit)}</span>}
            </div>
          </div>
        </Section>

        <Section n={4} icon={<Wallet size={13} />} title="Where the money goes">
          <div className="flex flex-wrap gap-1.5">
            {o.payees.map((p) => {
              const on = spec.payees.includes(p.id);
              const disabled = p.kind === "known" && !known;
              return (
                <button key={p.id} disabled={disabled} aria-pressed={on}
                  onClick={() => set({ payees: on ? spec.payees.filter((x) => x !== p.id) : [...spec.payees, p.id] })}
                  className={cn("rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors disabled:opacity-40",
                    on ? (p.kind === "ring" ? "border-threat/50 bg-threat-soft text-threat" : "border-ink bg-ink text-bg")
                      : "border-line text-muted hover:text-ink")}>
                  {p.kind === "ring" ? `${p.label} · 21 Sep ring` : p.label}
                </button>
              );
            })}
          </div>
          {spec.payees.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-2">
              <RupeeInput value={spec.amount} onChange={(v) => set({ amount: v })} min={1000} max={2500000} />
              <span>to each payee,</span>
              <NumberField value={spec.delay_min} onChange={(v) => set({ delay_min: v })} min={12} max={600} label="Minutes after login"
                className="h-8 w-16 rounded-md border border-line bg-panel px-2" />
              <span>min after the login</span>
              <span className="ml-auto num font-semibold text-ink">{inr(total)} out</span>
            </div>
          ) : (
            <p className="text-[11.5px] text-faint">No money moves — staff access alone.</p>
          )}
          {spec.payees.some((p) => p.startsWith("A-")) && (
            <Toggle on={spec.ring_reacts} onChange={(v) => set({ ring_reacts: v })} label="The ring reacts as on 21 Sep: forwards ~96% within 40 min" />
          )}
        </Section>
      </div>

      <div className="mt-auto border-t border-line px-4 py-3">
        {invalid ? (
          <p className="mb-2 rounded-md bg-amber-soft px-2.5 py-1.5 text-[12px] text-amber">{invalid}</p>
        ) : preview.data ? (
          <button onClick={() => setShowRows((v) => !v)} className="mb-2 flex w-full items-center gap-2 text-left text-[12px] text-muted hover:text-ink">
            <span>
              Becomes <b className="num text-ink">{preview.data.rows.length} rows</b> in <b className="num text-ink">{preview.data.systems.length}</b> bank
              systems{preview.data.money_out ? <> · <b className="num text-ink">{inr(preview.data.money_out)}</b> leaves {spec.account_id}</> : null}
            </span>
            <ChevronDown size={13} className={cn("ml-auto transition-transform", showRows && "rotate-180")} />
          </button>
        ) : null}
        {showRows && preview.data && !invalid && (
          <ol className="mb-2 max-h-[220px] space-y-1 overflow-y-auto rounded-md bg-panel-2 p-2">
            {preview.data.rows.map((r) => (
              <li key={r.seq} className="grid grid-cols-[48px_minmax(0,1fr)] gap-2 text-[11.5px]">
                <span className="num text-faint">{r.t.slice(11, 16)}</span>
                <span className="text-ink-2"><Chip className="!px-1.5 !py-0 !text-[10px]">{r.system}</Chip> {r.summary}</span>
              </li>
            ))}
          </ol>
        )}
        {sendError && <p className="mb-2 text-[12px] text-threat">{sendError}</p>}
        <Button variant="primary" className="w-full" disabled={busy || !!invalid || preview.isFetching && !preview.data}
          onClick={async () => {
            setSendError(null);
            try {
              await onSend(spec);
            } catch (e) {
              setSendError(e instanceof ApiError ? e.message : "Could not reach the API.");
            }
          }}>
          <Send size={14} /> Send to the bank — and let SUTRA judge it
        </Button>
        <p className="mt-1.5 text-center text-[11px] text-faint">Same ingest and detection as tonight&apos;s feed. Nothing is decided by this form.</p>
      </div>
    </Panel>
  );
}

const SELECT = "h-8 w-full rounded-md border border-line bg-panel px-2 text-[12.5px] text-ink";

function Section({ n, icon, title, children }: { n: number; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-1.5 text-[12px] font-semibold text-ink">
        <span className="num grid size-5 place-items-center rounded-full bg-panel-2 text-[10.5px] text-muted">{n}</span>
        <span className="text-faint">{icon}</span>{title}
      </div>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[11px] text-faint">{label}</span>
      {children}
    </label>
  );
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} onClick={() => onChange(!on)}
      className="flex items-center gap-2 rounded-md px-1 py-1 text-left text-[12px] text-ink-2 hover:bg-panel-2">
      <span className={cn("relative h-4 w-7 shrink-0 rounded-full transition-colors", on ? "bg-ok" : "bg-line-strong")}>
        <span className={cn("absolute top-0.5 size-3 rounded-full bg-panel shadow-xs transition-[left]", on ? "left-3.5" : "left-0.5")} />
      </span>
      {label}
    </button>
  );
}

function Segmented({ value, onChange, items }: { value: string; onChange: (v: string) => void; items: [string, ReactNode][] }) {
  return (
    <div className="inline-flex rounded-full border border-line bg-panel p-0.5" role="radiogroup">
      {items.map(([v, label]) => (
        <button key={v} role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-colors",
            value === v ? "bg-primary text-on-primary" : "text-muted hover:text-ink")}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Free typing; the value is clamped and committed on blur or Enter, so "4…" never snaps to the minimum. */
function NumberField({ value, onChange, min, max, label, className }: {
  value: number; onChange: (v: number) => void; min: number; max: number; label: string; className?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const commit = () => {
    if (text === null) return;
    onChange(Math.max(min, Math.min(max, Math.round(Number(text.replace(/[^\d.]/g, "")) || min))));
    setText(null);
  };
  return (
    <input inputMode="numeric" value={text ?? String(value)} aria-label={label} onChange={(e) => setText(e.target.value)}
      onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()}
      className={cn("num text-[12.5px] text-ink outline-none", className)} />
  );
}

function RupeeInput({ value, onChange, min, max }: { value: number; onChange: (v: number) => void; min: number; max: number }) {
  return (
    <span className="inline-flex h-8 items-center rounded-md border border-line bg-panel pl-2 text-[12.5px]">
      <span className="text-faint">₹</span>
      <NumberField value={value} onChange={onChange} min={min} max={max} label="Amount in rupees" className="h-full w-24 bg-transparent px-1" />
    </span>
  );
}
