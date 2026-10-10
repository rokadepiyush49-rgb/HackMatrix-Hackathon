"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Plus, Send, Smartphone } from "lucide-react";
import { useState } from "react";

import { bank, BankError, rupees, useBankSession, type BankRecord } from "@/components/bank/bank-client";
import { Btn, Card, Field, INPUT, Notice, RecordsList } from "@/components/bank/shell";
import { cn } from "@/lib/format";

interface DirRow { id: string; full_name: string; segment: string; account_id: string; status: string; balance: number; mobile: string }
interface Account {
  id: string; holder: string; status: string; balance: number; daily_limit: number; spent_today: number; mobile: string;
  transactions: { id: string; t: string; from: string; to: string; amount: number; channel: string; narration: string | null }[];
  payees: { account: string; name: string }[];
}
interface Me { customer: { id: string; name: string; segment: string }; accounts: Account[]; session_id: string; device: string | null }
interface Payee { account: string; name: string; bank: string; internal: boolean }

const KEY = "kestrel.customer";

export default function NetBanking() {
  const [token, setToken] = useBankSession(KEY);
  return token ? <Dashboard token={token} onLogout={() => setToken(null)} /> : <Login onIn={setToken} />;
}

function Login({ onIn }: { onIn: (t: string) => void }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const dir = useQuery<DirRow[]>({ queryKey: ["bank-customers", q], queryFn: () => bank<DirRow[]>(`customers?q=${encodeURIComponent(q)}`) });
  const [pick, setPick] = useState<DirRow | null>(null);
  const [newPhone, setNewPhone] = useState(true);
  const [stage, setStage] = useState<"who" | "otp">("who");
  const [otp, setOtp] = useState("482913");
  const [err, setErr] = useState<string | null>(null);

  return (
    <div className="mx-auto flex max-w-[560px] flex-col gap-4 pt-6">
      <Card title="Kestrel NetBanking · sign in" sub="Test system: choose a customer. The OTP step is simulated, but where it goes is real.">
        {stage === "who" ? (
          <div className="flex flex-col gap-3">
            <Field label="Find a customer" hint="Dormant accounts and the 21 Sep ring's accounts are listed first.">
              <input className={INPUT} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, customer ID or account" id="nb-search" />
            </Field>
            <ul className="max-h-[260px] divide-y divide-[#eef1f0] overflow-y-auto rounded-md border border-[#e3e8e6] text-[13px]">
              {dir.data?.map((c) => (
                <li key={c.account_id}>
                  <button className={cn("flex w-full items-center justify-between gap-2 px-3 py-2 text-left", pick?.account_id === c.account_id ? "bg-[#e3f4ec]" : "hover:bg-[#f3f6f5]")}
                    onClick={() => setPick(c)}>
                    <span><b>{c.full_name}</b> · <span className="font-mono">{c.account_id}</span>
                      {c.status === "INOPERATIVE" && <span className="ml-1.5 rounded bg-[#fdf1d8] px-1.5 text-[11px] text-[#7a4b00]">dormant</span>}</span>
                    <span className="font-mono text-[12px] text-[#5b6b66]">{rupees(c.balance)}</span>
                  </button>
                </li>
              ))}
            </ul>
            <Field label="Signing in on">
              <div className="flex gap-2">
                {[true, false].map((n) => (
                  <button key={String(n)} type="button" onClick={() => setNewPhone(n)} aria-pressed={newPhone === n}
                    className={cn("h-9 flex-1 rounded-md border text-[13px]", newPhone === n ? "border-[#0f6b50] bg-[#e3f4ec] font-semibold text-[#0b5a43]" : "border-[#c7d0cc] bg-white")}>
                    {n ? "A new phone" : "The customer's usual phone"}
                  </button>
                ))}
              </div>
            </Field>
            <Btn disabled={!pick} onClick={() => setStage("otp")}><Smartphone size={14} /> Send OTP</Btn>
          </div>
        ) : (
          <form className="flex flex-col gap-3" onSubmit={async (e) => {
            e.preventDefault();
            if (!pick) return;
            setErr(null);
            try {
              const r = await bank<{ token: string }>("customer/login", { body: { customer_id: pick.id, new_device: newPhone } });
              onIn(r.token);
              qc.invalidateQueries({ queryKey: ["bank-clock"] });
              qc.invalidateQueries({ queryKey: ["bank-activity"] });
            } catch (x) {
              setErr(x instanceof BankError ? x.message : "The bank is not reachable.");
            }
          }}>
            <Notice tone="info">OTP sent to the registered mobile <b>{pick?.mobile}</b>. Whoever holds that phone can sign in.</Notice>
            <Field label="One-time password"><input className={cn(INPUT, "font-mono tracking-[0.3em]")} value={otp} onChange={(e) => setOtp(e.target.value)} id="nb-otp" /></Field>
            {err && <Notice tone="error">{err}</Notice>}
            <div className="flex gap-2">
              <Btn tone="plain" type="button" onClick={() => setStage("who")}>Back</Btn>
              <Btn type="submit" className="flex-1" disabled={otp.length !== 6}><KeyRound size={14} /> Verify and sign in</Btn>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}

function Dashboard({ token, onLogout }: { token: string; onLogout: () => void }) {
  const qc = useQueryClient();
  const me = useQuery<Me, BankError>({ queryKey: ["nb-me", token], queryFn: () => bank<Me>("customer/me", { token }), retry: false });
  const [log, setLog] = useState<BankRecord[]>([]);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [pq, setPq] = useState("");
  const dir = useQuery<Payee[]>({ queryKey: ["nb-payees", token, pq], queryFn: () => bank<Payee[]>(`customer/payee-directory?q=${encodeURIComponent(pq)}`, { token }) });
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState(400000);
  const [channel, setChannel] = useState<"IMPS" | "NEFT" | "UPI">("IMPS");

  if (me.error?.status === 401) {
    return <div className="mx-auto max-w-[460px] pt-6"><Notice tone="error">Your NetBanking session has expired. <button className="underline" onClick={onLogout}>Sign in again</button></Notice></div>;
  }
  const m = me.data;
  const acct = m?.accounts[0];
  const act = async (fn: () => Promise<BankRecord>, ok: string) => {
    setMsg(null);
    try {
      const r = await fn();
      setLog((l) => [...l, r]);
      setMsg({ tone: "ok", text: ok });
      qc.invalidateQueries({ queryKey: ["nb-me"] });
      qc.invalidateQueries({ queryKey: ["bank-clock"] });
      qc.invalidateQueries({ queryKey: ["bank-activity"] });
      return true;
    } catch (x) {
      setMsg({ tone: "error", text: x instanceof BankError ? x.message : "The bank is not reachable." });
      return false;
    }
  };

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-[22px] font-semibold">Welcome, {m?.customer.name ?? "…"}</h1>
            <p className="text-[12.5px] text-[#5b6b66]">Session <span className="font-mono">{m?.session_id}</span> · device <span className="font-mono">{m?.device ?? "—"}</span></p>
          </div>
          <Btn tone="plain" onClick={onLogout}><LogOut size={14} /> Sign out</Btn>
        </div>
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
        {acct && (
          <Card title={`Savings account ${acct.id}`} sub={acct.status === "INOPERATIVE" ? "Marked dormant: no customer activity for over two years" : undefined}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Balance" value={rupees(acct.balance)} big />
              <Stat label="Transaction limit" value={rupees(acct.daily_limit)} />
              <Stat label="Sent today" value={rupees(acct.spent_today)} />
              <Stat label="Registered mobile" value={acct.mobile} />
            </div>
          </Card>
        )}

        <Card title="Send money" sub="Only to saved payees. The bank checks the balance and the transaction limit.">
          {acct && acct.payees.length === 0 && <Notice tone="info">No payees yet. Add one first.</Notice>}
          <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="To">
              <select className={INPUT} value={to} onChange={(e) => setTo(e.target.value)} id="nb-to">
                <option value="">Choose a payee</option>
                {acct?.payees.map((p) => <option key={p.account} value={p.account}>{p.name} · {p.account}</option>)}
              </select>
            </Field>
            <Field label="Amount (₹)">
              <input className={INPUT} inputMode="numeric" value={amount} onChange={(e) => setAmount(Number(e.target.value.replace(/\D/g, "")) || 0)} id="nb-amount" />
            </Field>
            <Field label="Via">
              <select className={INPUT} value={channel} onChange={(e) => setChannel(e.target.value as typeof channel)} id="nb-channel">
                <option>IMPS</option><option>NEFT</option><option>UPI</option>
              </select>
            </Field>
          </div>
          <Btn className="mt-3" disabled={!to || !acct} onClick={() => acct && act(
            () => bank<BankRecord>("customer/transfer", { token, body: { account_id: acct.id, to, amount, channel } }), `${rupees(amount)} sent.`)}>
            <Send size={14} /> Send {rupees(amount)}
          </Btn>
        </Card>

        <Card title="Add a payee">
          <input className={cn(INPUT, "w-full")} value={pq} onChange={(e) => setPq(e.target.value)} placeholder="Search by name or account number" id="nb-payee-search" />
          <ul className="mt-2 divide-y divide-[#eef1f0] text-[13px]">
            {dir.data?.map((p) => (
              <li key={p.account} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                <span><b>{p.name}</b> · <span className="font-mono">{p.account}</span> · {p.bank}</span>
                <Btn tone="plain" className="h-8" disabled={!acct || acct.payees.some((x) => x.account === p.account)}
                  onClick={() => acct && act(() => bank<BankRecord>("customer/payees", { token, body: { account_id: acct.id, counterparty: p.account } }), `${p.name} added as a payee.`)}>
                  <Plus size={13} /> Add
                </Btn>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Security">
          <Btn tone="plain" onClick={() => act(() => bank<BankRecord>("customer/password", { token, body: {} }), "Password reset. The OTP went to the registered mobile.")}>
            <KeyRound size={14} /> Reset password
          </Btn>
        </Card>
      </div>

      <div className="flex flex-col gap-5">
        <Card title="Recent transactions">
          <ul className="text-[12.5px]">
            {acct?.transactions.length === 0 && <li className="text-[#6b7a75]">None.</li>}
            {acct?.transactions.map((t) => (
              <li key={t.id} className="flex justify-between gap-2 border-b border-[#eef1f0] py-1.5">
                <span className="text-[#5b6b66]">{new Date(t.t).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })} · {t.from === acct.id ? `to ${t.to}` : `from ${t.from}`}</span>
                <span className={cn("font-mono", t.from === acct.id ? "text-[#9f1d14]" : "text-[#0b5a43]")}>{t.from === acct.id ? "−" : "+"}{rupees(t.amount)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="What the bank recorded for you" sub="These rows are what SUTRA ingests.">
          <RecordsList records={log} empty="Your sign-in was recorded; actions you take now appear here." />
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div className="rounded-md bg-[#f3f6f5] px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-[#6b7a75]">{label}</div>
      <div className={cn("mt-0.5 font-semibold", big && "text-[18px]")}>{value}</div>
    </div>
  );
}
