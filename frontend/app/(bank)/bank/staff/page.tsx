"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Fingerprint, KeyRound, LogOut, Search, ShieldAlert, Ticket } from "lucide-react";
import { useState } from "react";

import { bank, BankError, bankTime, rupees, useBankSession, type BankRecord } from "@/components/bank/bank-client";
import { Btn, Card, Field, INPUT, Notice, RecordsList } from "@/components/bank/shell";
import { cn } from "@/lib/format";

interface StaffRow { id: string; pseudonym: string; role: string; branch_id: string; branch: string; city: string }
interface Perm { code: string; name: string; temporary: boolean; since: string; intended_expiry: string | null; past_expiry: boolean; request_ref: string | null }
interface StaffMe {
  employee: StaffRow;
  permissions: Perm[];
  roster: { duty: string; start: string; end: string }[];
  on_duty: boolean;
  session_id: string;
  channel: "BRANCH" | "VPN";
}
interface Hit { id: string; full_name: string; segment: string; branch_id: string; account_id: string; status: string }
interface Opened { customer: { id: string; name: string; segment: string; branch_id: string; since: string }; accounts: { id: string; kind: string; status: string; balance: number }[]; record: BankRecord }
interface AccountView {
  id: string; customer_id: string; holder: string; segment: string; kind: string; status: string; status_since: string | null;
  branch_id: string; balance: number; daily_limit: number; mobile: string; last_activity: string | null;
  transactions: { id: string; t: string; from: string; to: string; amount: number; channel: string; narration: string | null }[];
  payees: { account: string; name: string; since: string }[];
  record?: BankRecord;
}

const KEY = "kestrel.staff";

export default function StaffConsole() {
  const [token, setToken] = useBankSession(KEY);
  return token ? <Console token={token} onLogout={() => setToken(null)} /> : <Login onIn={setToken} />;
}

function Login({ onIn }: { onIn: (t: string) => void }) {
  const dir = useQuery<StaffRow[]>({ queryKey: ["bank-staff-dir"], queryFn: () => bank<StaffRow[]>("staff/directory") });
  const qc = useQueryClient();
  const [emp, setEmp] = useState("");
  const [channel, setChannel] = useState<"BRANCH" | "VPN">("VPN");
  const [err, setErr] = useState<string | null>(null);
  const chosen = emp || dir.data?.find((s) => s.id === "EMP-0258")?.id || dir.data?.[0]?.id || "";
  return (
    <div className="mx-auto flex max-w-[460px] flex-col gap-4 pt-6">
      <Card title="Core banking · staff sign-in" sub="Test system: pick an employee, no password needed.">
        <form className="flex flex-col gap-3" onSubmit={async (e) => {
          e.preventDefault();
          setErr(null);
          try {
            const r = await bank<{ token: string }>("staff/login", { body: { employee_id: chosen, channel } });
            onIn(r.token);
            qc.invalidateQueries({ queryKey: ["bank-clock"] });
          } catch (x) {
            setErr(x instanceof BankError ? x.message : "The bank is not reachable.");
          }
        }}>
          <Field label="Employee">
            <select className={INPUT} value={chosen} onChange={(e) => setEmp(e.target.value)} id="staff-employee">
              {dir.data?.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.pseudonym} · {s.branch}, {s.city}</option>)}
            </select>
          </Field>
          <Field label="Signing in from" hint="VPN means from home on the bank laptop; the branch terminal means at the counter.">
            <div className="flex gap-2">
              {(["VPN", "BRANCH"] as const).map((c) => (
                <button type="button" key={c} onClick={() => setChannel(c)} aria-pressed={channel === c}
                  className={cn("h-9 flex-1 rounded-md border text-[13px]", channel === c ? "border-[#0f6b50] bg-[#e3f4ec] font-semibold text-[#0b5a43]" : "border-[#c7d0cc] bg-white")}>
                  {c === "VPN" ? "VPN from home" : "Branch terminal"}
                </button>
              ))}
            </div>
          </Field>
          {err && <Notice tone="error">{err}</Notice>}
          <Btn type="submit" disabled={!chosen}><KeyRound size={14} /> Sign in</Btn>
        </form>
      </Card>
      <p className="text-center text-[12px] text-[#6b7a75]">Signing in is itself recorded: the VPN gateway or branch SSO logs a session.</p>
    </div>
  );
}

function Console({ token, onLogout }: { token: string; onLogout: () => void }) {
  const qc = useQueryClient();
  const me = useQuery<StaffMe, BankError>({
    queryKey: ["staff-me", token], queryFn: () => bank<StaffMe>("staff/me", { token }), retry: false,
  });
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [acct, setAcct] = useState<AccountView | null>(null);
  const [log, setLog] = useState<BankRecord[]>([]);
  const [msg, setMsg] = useState<{ tone: "ok" | "error" | "warn"; text: string } | null>(null);

  if (me.error?.status === 401) {
    return <div className="mx-auto max-w-[460px] pt-6"><Notice tone="warn">Your bank session has expired. <button className="underline" onClick={onLogout}>Sign in again</button></Notice></div>;
  }

  const act = async <T,>(fn: () => Promise<T>, ok: (r: T) => string | null) => {
    setMsg(null);
    try {
      const r = await fn();
      const recs = (Array.isArray(r) ? r : [(r as { record?: BankRecord }).record ?? r]).filter((x): x is BankRecord => !!x && typeof x === "object" && "seq" in x);
      setLog((l) => [...l, ...recs]);
      const text = ok(r);
      if (text) setMsg({ tone: "ok", text });
      qc.invalidateQueries({ queryKey: ["bank-clock"] });
      qc.invalidateQueries({ queryKey: ["bank-activity"] });
      qc.invalidateQueries({ queryKey: ["staff-me"] });
      return r;
    } catch (x) {
      setMsg({ tone: "error", text: x instanceof BankError ? x.message : "The bank is not reachable." });
      return null;
    }
  };
  const open = async (id: string) => {
    const r = await act(() => bank<AccountView>("staff/account", { token, body: { account_id: id } }), () => null);
    if (r) setAcct(r);
  };
  // after a change: refresh what is on screen without recording another view
  const reopen = async (id: string) => {
    try {
      setAcct(await bank<AccountView>(`staff/account-view?account_id=${encodeURIComponent(id)}`, { token }));
    } catch {
      /* keep what is shown */
    }
  };

  const m = me.data;
  const override = m?.permissions.find((p) => p.code === "MOBILE_UPDATE_OVERRIDE");
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="flex flex-col gap-4">
        <Card title={m ? `${m.employee.id} · ${m.employee.pseudonym}` : "Signed in"} sub={m ? `${m.employee.branch}, ${m.employee.city}` : undefined}
          right={<button onClick={onLogout} className="flex items-center gap-1 text-[12px] text-[#5b6b66] hover:text-[#14211d]"><LogOut size={13} /> Sign out</button>}>
          {m && (
            <div className="flex flex-col gap-2 text-[12.5px]">
              <div className="flex justify-between"><span className="text-[#5b6b66]">Session</span><span className="font-mono">{m.session_id}</span></div>
              <div className="flex justify-between"><span className="text-[#5b6b66]">Signed in from</span><span>{m.channel === "VPN" ? "VPN · bank laptop" : "Branch terminal"}</span></div>
              <div className="flex justify-between"><span className="text-[#5b6b66]">Rostered now</span>
                <span className={m.on_duty ? "text-[#0b5a43]" : "font-semibold text-[#9a3412]"}>{m.on_duty ? "Yes" : "No shift covers this time"}</span></div>
            </div>
          )}
        </Card>
        <Card title="My permissions">
          <ul className="flex flex-col gap-1.5 text-[12.5px]">
            {m?.permissions.map((p) => (
              <li key={p.code} className={cn("rounded px-2 py-1", p.past_expiry ? "bg-[#fdf1d8]" : "bg-[#f3f6f5]")}>
                <span className="font-mono text-[11.5px]">{p.code}</span>
                {p.temporary && (
                  <span className="block text-[11.5px] text-[#7a4b00]">
                    Temporary ({p.request_ref}) · meant to expire {new Date(p.intended_expiry ?? "").toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}
                    {p.past_expiry && " · past expiry, still active: nobody revoked it"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="My roster today">
          {m && m.roster.length ? (
            <ul className="text-[12.5px]">{m.roster.map((r, i) => <li key={i}>{r.duty.toLowerCase()} · {bankTime(r.start)}–{bankTime(r.end)}</li>)}</ul>
          ) : <p className="text-[12.5px] text-[#6b7a75]">No shift today.</p>}
        </Card>
        <Card title="Branch manager · setup" sub="Things a manager or HR would have done earlier.">
          <div className="flex flex-col gap-2">
            <Btn tone="plain" onClick={() => act(() => bank<BankRecord>("staff/setup/override", { token, body: { mode: "expired" } }),
              () => "Old camp override granted (16 Sep, meant to expire 18 Sep, never revoked).")}>
              <ShieldAlert size={14} /> Old camp override, never revoked
            </Btn>
            <Btn tone="plain" onClick={() => act(() => bank<BankRecord>("staff/setup/override", { token, body: { mode: "today" } }),
              () => "Temporary override granted from today, for two days.")}>Temporary override from today</Btn>
            <Btn tone="plain" onClick={() => act(() => bank<BankRecord>("staff/setup/roster", { token, body: { start: "17:30", end: "22:30" } }),
              () => "Evening camp shift 17:30–22:30 added to the roster.")}>Roster an evening camp shift</Btn>
          </div>
        </Card>
      </aside>

      <div className="flex flex-col gap-5">
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
        <Card title="Customer search">
          <form className="flex gap-2" onSubmit={async (e) => {
            e.preventDefault();
            setMsg(null);
            try {
              setHits(await bank<Hit[]>(`staff/search?q=${encodeURIComponent(q)}`, { token }));
            } catch (x) {
              setMsg({ tone: "error", text: x instanceof BankError ? x.message : "Search failed." });
            }
          }}>
            <input className={cn(INPUT, "flex-1")} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Customer ID, account number or name — try A-5661" id="staff-search" />
            <Btn type="submit"><Search size={14} /> Search</Btn>
          </form>
          {hits && (
            <ul className="mt-3 divide-y divide-[#eef1f0] text-[13px]">
              {hits.length === 0 && <li className="py-2 text-[#6b7a75]">No match.</li>}
              {hits.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span><b>{h.full_name}</b> · <span className="font-mono">{h.id}</span> · {h.account_id} · {h.segment.toLowerCase()}
                    {h.status === "INOPERATIVE" && <span className="ml-1.5 rounded bg-[#fdf1d8] px-1.5 text-[11px] text-[#7a4b00]">dormant</span>}</span>
                  <Btn tone="plain" className="h-8" onClick={async () => {
                    const r = await act(() => bank<Opened>("staff/customer", { token, body: { customer_id: h.id } }), () => null);
                    if (r) { setOpened(r); setAcct(null); setHits(null); }
                  }}>Open customer</Btn>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {opened && (
          <Card title={`${opened.customer.name} · ${opened.customer.id}`} sub={`${opened.customer.segment.toLowerCase()} · branch ${opened.customer.branch_id} · customer since ${new Date(opened.customer.since).getFullYear()}`}>
            <div className="flex flex-wrap gap-2">
              {opened.accounts.map((a) => (
                <Btn key={a.id} tone={acct?.id === a.id ? "primary" : "plain"} onClick={() => open(a.id)}>
                  {a.id} · {a.kind.toLowerCase()} {a.status === "INOPERATIVE" ? "· dormant" : ""}
                </Btn>
              ))}
            </div>
          </Card>
        )}

        {acct && (
          <AccountPanel acct={acct} token={token} override={!!override} overridePastExpiry={!!override?.past_expiry} act={act} reopen={reopen} />
        )}

        <Card title="What the bank recorded for you" sub="These rows are what SUTRA ingests. It never sees your intentions.">
          <RecordsList records={log} empty="Nothing yet in this session. Opening a customer is itself recorded." />
        </Card>
      </div>
    </div>
  );
}

function AccountPanel({ acct, token, override, overridePastExpiry, act, reopen }: {
  acct: AccountView; token: string; override: boolean; overridePastExpiry: boolean;
  act: <T>(fn: () => Promise<T>, ok: (r: T) => string | null) => Promise<T | null>;
  reopen: (id: string) => Promise<void>;
}) {
  const [mobile, setMobile] = useState("");
  const [auth, setAuth] = useState<"OTP_OLD_NUMBER" | "BIOMETRIC" | "OVERRIDE">(override ? "OVERRIDE" : "OTP_OLD_NUMBER");
  const [limit, setLimit] = useState(500000);
  const [useOverride, setUseOverride] = useState(override);
  const [note, setNote] = useState("Update registered mobile number — customer request");
  const dormant = acct.status === "INOPERATIVE";
  return (
    <Card title={`Account ${acct.id} · ${acct.holder}`} sub={`${acct.kind.toLowerCase()} · branch ${acct.branch_id}`}
      right={dormant ? <span className="rounded bg-[#fdf1d8] px-2 py-0.5 text-[12px] font-semibold text-[#7a4b00]">Dormant since {acct.status_since ? new Date(acct.status_since).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "—"}</span> : undefined}>
      <div className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
        <Stat label="Balance" value={rupees(acct.balance)} />
        <Stat label="Transaction limit" value={rupees(acct.daily_limit)} />
        <Stat label="Registered mobile" value={acct.mobile} />
        <Stat label="Last activity" value={acct.last_activity ? new Date(acct.last_activity).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—"} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <div className="flex flex-col gap-3 rounded-md border border-[#e3e8e6] p-3">
          <h3 className="text-[13px] font-semibold">Update registered mobile</h3>
          <Field label="New mobile number">
            <input className={INPUT} inputMode="numeric" placeholder="98765 43210" value={mobile} onChange={(e) => setMobile(e.target.value)} id="staff-mobile" />
          </Field>
          <Field label="Authorised by">
            <select className={INPUT} value={auth} onChange={(e) => setAuth(e.target.value as typeof auth)} id="staff-auth">
              <option value="OTP_OLD_NUMBER">OTP to the old number (customer confirms)</option>
              <option value="BIOMETRIC">Customer&apos;s biometric (needs an eKYC first)</option>
              <option value="OVERRIDE">Override, no OTP {override ? "" : "(you hold no override)"}</option>
            </select>
          </Field>
          {auth === "OVERRIDE" && overridePastExpiry && <Notice tone="warn"><AlertTriangle size={13} className="mr-1 inline" />Your override is past its intended expiry, but nobody revoked it, so the system still accepts it.</Notice>}
          <Btn disabled={!mobile} onClick={async () => {
            const r = await act(() => bank<BankRecord[]>("staff/mobile", { token, body: { account_id: acct.id, new_mobile: mobile, auth } }), () => "Registered mobile changed.");
            if (r) { setMobile(""); await reopen(acct.id); }
          }}>Change mobile</Btn>
        </div>

        <div className="flex flex-col gap-3 rounded-md border border-[#e3e8e6] p-3">
          <h3 className="text-[13px] font-semibold">Change transaction limit</h3>
          <Field label="New limit (₹)">
            <input className={INPUT} inputMode="numeric" value={limit} onChange={(e) => setLimit(Number(e.target.value.replace(/\D/g, "")) || 0)} id="staff-limit" />
          </Field>
          <label className="flex items-center gap-2 text-[12.5px]">
            <input type="checkbox" checked={useOverride} onChange={(e) => setUseOverride(e.target.checked)} id="staff-limit-override" /> Use my override (no checker)
          </label>
          <Btn onClick={async () => {
            const r = await act(() => bank<BankRecord[]>("staff/limit", { token, body: { account_id: acct.id, limit, use_override: useOverride } }), () => "Transaction limit changed.");
            if (r) await reopen(acct.id);
          }}>Change limit</Btn>
        </div>

        <div className="flex flex-col gap-3 rounded-md border border-[#e3e8e6] p-3">
          <h3 className="text-[13px] font-semibold">Service desk</h3>
          <Field label="Ticket for this customer">
            <input className={INPUT} value={note} onChange={(e) => setNote(e.target.value)} id="staff-ticket" />
          </Field>
          <Btn tone="plain" onClick={() => act(() => bank<BankRecord>("staff/ticket", { token, body: { account_id: acct.id, note } }), () => "Service ticket raised.")}>
            <Ticket size={14} /> Raise ticket
          </Btn>
        </div>

        <div className="flex flex-col gap-3 rounded-md border border-[#e3e8e6] p-3">
          <h3 className="text-[13px] font-semibold">Customer at the counter</h3>
          <p className="text-[12.5px] text-[#5b6b66]">Capture an Aadhaar biometric eKYC. Only possible when the customer is actually present.</p>
          <Btn tone="plain" onClick={() => act(() => bank<BankRecord>("staff/ekyc", { token, body: { account_id: acct.id } }), () => "Biometric eKYC captured.")}>
            <Fingerprint size={14} /> Capture eKYC
          </Btn>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <div>
          <h3 className="mb-1.5 text-[13px] font-semibold">Recent transactions</h3>
          <ul className="text-[12.5px]">
            {acct.transactions.length === 0 && <li className="text-[#6b7a75]">None.</li>}
            {acct.transactions.map((t) => (
              <li key={t.id} className="flex justify-between gap-2 border-b border-[#eef1f0] py-1">
                <span className="text-[#5b6b66]">{new Date(t.t).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} · {t.narration ?? t.channel}</span>
                <span className={cn("font-mono", t.from === acct.id ? "text-[#9f1d14]" : "text-[#0b5a43]")}>{t.from === acct.id ? "−" : "+"}{rupees(t.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-1.5 text-[13px] font-semibold">Payees</h3>
          <ul className="text-[12.5px]">
            {acct.payees.length === 0 && <li className="text-[#6b7a75]">None.</li>}
            {acct.payees.map((p) => <li key={p.account} className="border-b border-[#eef1f0] py-1">{p.name} · <span className="font-mono">{p.account}</span></li>)}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-[#f3f6f5] px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-[#6b7a75]">{label}</div>
      <div className="mt-0.5 font-semibold">{value}</div>
    </div>
  );
}
