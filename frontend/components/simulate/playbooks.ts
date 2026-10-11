"use client";

// Fraud Simulator playbooks. Each playbook is a fraud (or its legitimate twin) broken into the actions a
// person would take, and every action is a real call to Kestrel Bank, the mock bank. The bank records
// what its systems would record and hands those rows to SUTRA as it happens. Nothing here talks to
// detection: whether it adds up to a signal, an alert or a case is decided later by SUTRA's own run.

import type { LucideIcon } from "lucide-react";
import { Banknote, Building2, Shuffle, VenetianMask } from "lucide-react";

// ── talking to the bank ─────────────────────────────────────────────────────

export class SimError extends Error {
  constructor(message: string, public code?: string) {
    super(message);
  }
}

/** One call to the bank's API (through the web app's /api/bank pass-through). Refusals carry the bank's own words. */
export async function bankCall<T>(path: string, opts: { body?: unknown; token?: string | null } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/bank/${path}`, {
      method: opts.body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", ...(opts.token ? { "X-Bank-Token": opts.token } : {}) },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: "no-store",
    });
  } catch {
    throw new SimError("Kestrel Bank is not reachable. Is the API running?");
  }
  const b = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = b?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join("; ")
        : b?.message ?? res.statusText;
    throw new SimError(msg, b?.code);
  }
  return b as T;
}

export interface BankRecord { seq: number; t: string; table: string; ref: string; system: string; summary: string }
export interface Account {
  accountId: string; customerId: string; name: string; segment: string; type: string; balance: number;
  status: string; transactionLimit: number; registeredMobile: string;
}
interface Directory { account: string; name: string; bank: string | null; internal: boolean }
interface CustomerMe { accounts: { id: string; payees: { account: string }[] }[] }

export const activity = () => bankCall<BankRecord[]>("activity");
export const account = (id: string) => bankCall<Account>(`accounts/${id}`);

const rupees = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const PERSON = /^[A-Z][a-z]+ [A-Z][a-z]+$/;

/** Accounts at other banks this customer has never paid, as the NetBanking payee search lists them. */
async function freshExternals(token: string, accountId: string, n: number, skip: string[] = []): Promise<Directory[]> {
  const [dir, me] = await Promise.all([
    bankCall<Directory[]>("customer/payee-directory", { token }),
    bankCall<CustomerMe>("customer/me", { token }),
  ]);
  const known = new Set([...(me.accounts.find((a) => a.id === accountId)?.payees.map((p) => p.account) ?? []), ...skip]);
  const out = dir.filter((d) => !d.internal && PERSON.test(d.name) && !known.has(d.account)).slice(0, n);
  if (out.length < n) throw new SimError("Ran out of fresh accounts at other banks for this customer. Reset the simulation and try again.");
  return out;
}

// ── playbook shape ──────────────────────────────────────────────────────────

export type Actor = "insider" | "accomplice" | "fraudster" | "mule" | "staff" | "backstory" | "victims";
export const ACTOR: Record<Actor, { label: string; tone: "threat" | "amber" | "ai" | "ok" | "info" | "faint" }> = {
  insider: { label: "Rogue insider", tone: "threat" },
  accomplice: { label: "Accomplice", tone: "amber" },
  fraudster: { label: "Fraudster", tone: "threat" },
  mule: { label: "Money mule", tone: "amber" },
  staff: { label: "Camp officer", tone: "ok" },
  backstory: { label: "Back-story", tone: "faint" },
  victims: { label: "Scam victims", tone: "info" },
};

export type Params = Record<string, string | number | string[]>;

export interface Ctx {
  p: Params;
  staff: string | null;
  customer: string | null;
  bag: Record<string, unknown>;
}

export interface StepOut { note: string; staff?: string; customer?: string; bag?: Record<string, unknown> }

export interface Step {
  key: string;
  actor: Actor;
  system: string;
  title: string;
  story: string;
  cta: string;
  run: (c: Ctx) => Promise<StepOut>;
}

export interface Field {
  key: string;
  label: string;
  kind: "time" | "number" | "text" | "select" | "multi" | "victim";
  help?: string;
  min?: number | string;
  max?: number | string;
  step?: number;
  options?: { v: string; label: string }[];
}

/** What SUTRA is expected to make of it — checked against the detection run's findings. */
export interface Expect {
  alert: "P1" | "queued" | null;
  typology?: string;
  signal?: string;
  /** Alibi's verdict on every access by this employee. */
  alibi?: { employee: string; verdict: "EXPLAINED" | "UNEXPLAINED" };
}

export interface Playbook {
  key: string;
  title: string;
  kind: "fraud" | "twin";
  icon: LucideIcon;
  tagline: string;
  brief: string;
  expectText: string;
  expect: Expect;
  /** The account the fraud is aimed at (a param key when the user picks it). */
  victim: (p: Params) => string;
  fields: Field[];
  defaults: Params;
  steps: (p: Params) => Step[];
  /** What to look at once SUTRA has judged it, beyond the case journey. */
  takeaway: string;
}

const s = (v: Params[string]) => String(v);
const n = (v: Params[string]) => Number(v);
const list = (v: Params[string]) => (Array.isArray(v) ? v : [String(v)]);

async function at(hhmm: string) {
  await bankCall("clock", { body: { at: hhmm } });
}

// ── 1. insider-enabled account takeover ─────────────────────────────────────

const OFFICER = "EMP-0258";

const insider: Playbook = {
  key: "insider",
  title: "Insider account takeover",
  kind: "fraud",
  icon: VenetianMask,
  tagline: "A bank officer uses an override nobody revoked to hijack a dormant pensioner's account.",
  brief:
    "You are EMP-0258, an operations officer at Nashik Road. Six days ago you were given a two-day override for a pension camp. " +
    "Nobody took it back. Tonight, from home, you use it to point a dormant account at your accomplice's phone and lift its limit. " +
    "Your accomplice signs in, adds two mule payees and empties the account.",
  expectText: "P1 insider-enabled takeover. Alibi finds no ticket, roster, queue item or customer contact behind the officer's accesses.",
  expect: { alert: "P1", typology: "INSIDER_ATO", alibi: { employee: OFFICER, verdict: "UNEXPLAINED" } },
  victim: (p) => s(p.account),
  fields: [
    { key: "account", label: "Target account (dormant)", kind: "victim", help: "Dormant accounts are attractive: nobody is watching them." },
    { key: "at", label: "Officer logs in at", kind: "time", min: "19:00", max: "22:45", help: "The officer's shift ended at 18:30." },
    { key: "mobile", label: "Accomplice's mobile", kind: "text", help: "10 digits, starting 6–9" },
    { key: "limit", label: "New transaction limit (₹)", kind: "number", min: 1_00_000, max: 10_00_000, step: 50_000 },
    { key: "mules", label: "Mule payees", kind: "multi", options: [{ v: "A-7731", label: "A-7731 · Arjun Sathe" }, { v: "A-7768", label: "A-7768 · Vishal Bapat" }] },
    { key: "amount", label: "Sent to each mule (₹)", kind: "number", min: 10_000, max: 10_00_000, step: 10_000 },
  ],
  defaults: { account: "A-5661", at: "21:20", mobile: "9876543210", limit: 5_00_000, mules: ["A-7731", "A-7768"], amount: 4_00_000 },
  steps: (p) => [
    {
      key: "login", actor: "insider", system: "VPN gateway", title: "Sign in to core banking over VPN, from home",
      story: `It is ${s(p.at)} on 22 Sep, hours after the shift ended. ${OFFICER} connects from a personal laptop.`,
      cta: "Connect over VPN",
      run: async () => {
        await at(s(p.at));
        const r = await bankCall<{ session_id: string; device: string; token: string }>("staff/login", { body: { employee_id: OFFICER, channel: "VPN" } });
        return { note: `VPN session ${r.session_id} from ${r.device}`, staff: r.token };
      },
    },
    {
      key: "override", actor: "backstory", system: "IAM", title: "The override that was never revoked",
      story: "16 Sep: the branch manager granted a two-day mobile-update override for a pension camp. It should have lapsed on 18 Sep. Nobody revoked it, so it still works tonight.",
      cta: "Bring the forgotten grant on record",
      run: async (c) => {
        const r = await bankCall<BankRecord>("staff/setup/override", { body: { mode: "expired" }, token: c.staff });
        return { note: r.summary };
      },
    },
    {
      key: "open", actor: "insider", system: "Core banking", title: "Look up the customer and open the dormant account",
      story: "No ticket, no customer at the counter, no queue item. Just curiosity about a balance nobody is watching.",
      cta: "Search and open the account",
      run: async (c) => {
        const acct = await account(s(p.account));
        await bankCall("staff/customer", { body: { customer_id: acct.customerId }, token: c.staff });
        const v = await bankCall<{ balance: number; mobile: string; status: string }>("staff/account", { body: { account_id: acct.accountId }, token: c.staff });
        return { note: `${acct.name} · ${v.status.toLowerCase()} · ${rupees(v.balance)} · mobile on file ${v.mobile}`, bag: { customerId: acct.customerId } };
      },
    },
    {
      key: "mobile", actor: "insider", system: "Core banking", title: "Swap the registered mobile to the accomplice's number",
      story: "Every OTP for this account will now go to the accomplice. The override means no OTP to the old number and no biometric.",
      cta: "Change the mobile with the override",
      run: async (c) => {
        await bankCall("staff/mobile", { body: { account_id: s(p.account), new_mobile: s(p.mobile), auth: "OVERRIDE" }, token: c.staff });
        return { note: `Registered mobile → +91 ••••• ${s(p.mobile).slice(-4)} (authorised by OVERRIDE)` };
      },
    },
    {
      key: "limit", actor: "insider", system: "Core banking", title: `Raise the transaction limit to ${rupees(n(p.limit))}`,
      story: "The old ₹1,00,000 limit would refuse the transfers. The officer lifts it, again on the override.",
      cta: "Raise the limit",
      run: async (c) => {
        await bankCall("staff/limit", { body: { account_id: s(p.account), limit: n(p.limit), use_override: true }, token: c.staff });
        return { note: `Transaction limit → ${rupees(n(p.limit))}` };
      },
    },
    {
      key: "takeover", actor: "accomplice", system: "Digital banking", title: "Sign in to NetBanking on a brand-new phone",
      story: "The accomplice installs the app on a phone the bank has never seen. The OTP arrives on the number the officer just set.",
      cta: "Sign in on the new phone",
      run: async (c) => {
        const r = await bankCall<{ device: string; otp_to: string; token: string }>("customer/login", { body: { customer_id: c.bag.customerId, new_device: true } });
        return { note: `New device ${r.device} registered · OTP sent to ${r.otp_to}`, customer: r.token };
      },
    },
    {
      key: "password", actor: "accomplice", system: "Digital banking", title: "Reset the password",
      story: "If the real customer ever tries to sign in, they are locked out.",
      cta: "Reset the password",
      run: async (c) => {
        await bankCall("customer/password", { body: {}, token: c.customer });
        return { note: "Password reset, authorised by OTP to the new number" };
      },
    },
    {
      key: "payees", actor: "accomplice", system: "Digital banking", title: `Add ${list(p.mules).length} mule payee${list(p.mules).length > 1 ? "s" : ""}`,
      story: "The mules are accounts recruited a day earlier. They will move the money on within the hour.",
      cta: "Add the payees",
      run: async (c) => {
        for (const m of list(p.mules)) await bankCall("customer/payees", { body: { account_id: s(p.account), counterparty: m }, token: c.customer });
        return { note: `Payees added: ${list(p.mules).join(", ")}` };
      },
    },
    ...list(p.mules).map((m, i): Step => ({
      key: `send-${m}`, actor: "accomplice", system: "IMPS switch", title: `Send ${rupees(n(p.amount))} to ${m}`,
      story: i === 0 ? "IMPS settles in seconds. Once it lands in a mule account, it is gone." : "The second half, straight after the first.",
      cta: `Send ${rupees(n(p.amount))}`,
      run: async (c) => {
        const r = await bankCall<BankRecord>("customer/transfer", { body: { account_id: s(p.account), to: m, amount: n(p.amount), channel: "IMPS" }, token: c.customer });
        return { note: `${r.ref}: ${rupees(n(p.amount))} by IMPS to ${m}` };
      },
    })),
  ],
  takeaway: "The privilege was granted 6 days before the money moved. Open Control Lab to see which control would have broken the chain, and how early.",
};

// ── 2. external account takeover (no insider) ──────────────────────────────

const OUTSIDER = { account: "A-8070", customer: "C-35868" };

const outsider: Playbook = {
  key: "outsider",
  title: "Account takeover by an outsider",
  kind: "fraud",
  icon: Banknote,
  tagline: "Phished credentials and a SIM swap: a stranger empties a salaried account, just under the limit.",
  brief:
    "You are a fraudster with Vishal Nair's NetBanking password from a phishing page and his number ported to your SIM. " +
    "Late at night, from a city he has never banked from, you sign in on your own phone, lock him out, add two payees at other banks " +
    "and send two transfers just under his ₹1,00,000 limit. No bank employee is involved.",
  expectText: "A queued external account-takeover alert: new device, password reset, new payees and payouts, with no staff privilege in the chain.",
  expect: { alert: "queued", typology: "EXTERNAL_ATO" },
  victim: () => OUTSIDER.account,
  fields: [
    { key: "at", label: "Sign-in time", kind: "time", min: "21:00", max: "23:40" },
    { key: "city", label: "Signing in from", kind: "select", options: ["Kolkata", "Jamtara", "Delhi", "Mumbai"].map((v) => ({ v, label: v })) },
    { key: "amount1", label: "First transfer (₹)", kind: "number", min: 1_000, max: 1_00_000, step: 500, help: "The account's limit is ₹1,00,000 per transfer." },
    { key: "amount2", label: "Second transfer (₹)", kind: "number", min: 1_000, max: 1_00_000, step: 500 },
  ],
  defaults: { at: "23:02", city: "Kolkata", amount1: 98_500, amount2: 97_000 },
  steps: (p) => [
    {
      key: "login", actor: "fraudster", system: "Digital banking", title: `Sign in on a new phone from ${s(p.city)}`,
      story: "The password came from a phishing page; the OTP comes to the fraudster's SIM after a swap. The bank has never seen this phone.",
      cta: "Sign in",
      run: async () => {
        await at(s(p.at));
        const r = await bankCall<{ device: string; token: string }>("customer/login", { body: { customer_id: OUTSIDER.customer, new_device: true, city: s(p.city) } });
        const targets = await freshExternals(r.token, OUTSIDER.account, 2);
        return { note: `New device ${r.device} · ${s(p.city)}`, customer: r.token, bag: { payees: targets.map((t) => t.account), names: targets.map((t) => t.name) } };
      },
    },
    {
      key: "password", actor: "fraudster", system: "Digital banking", title: "Reset the password and lock the customer out",
      story: "The real Vishal Nair can no longer sign in to see what is happening.",
      cta: "Reset the password",
      run: async (c) => {
        await bankCall("customer/password", { body: {}, token: c.customer });
        return { note: "Password reset from the new device" };
      },
    },
    {
      key: "payees", actor: "fraudster", system: "Digital banking", title: "Add two payees at other banks",
      story: "Accounts the customer has never paid. Money sent to another bank is much harder to claw back.",
      cta: "Add the payees",
      run: async (c) => {
        const payees = c.bag.payees as string[];
        for (const x of payees) await bankCall("customer/payees", { body: { account_id: OUTSIDER.account, counterparty: x }, token: c.customer });
        return { note: `Payees added: ${payees.map((x, i) => `${x} (${(c.bag.names as string[])[i]})`).join(", ")}` };
      },
    },
    ...(["amount1", "amount2"] as const).map((k, i): Step => ({
      key: `send-${i}`, actor: "fraudster", system: "IMPS switch", title: `Send ${rupees(n(p[k]))}, just under the limit`,
      story: i === 0 ? "Staying under ₹1,00,000 avoids the limit and, the fraudster hopes, attention." : "And again, to the second payee.",
      cta: `Send ${rupees(n(p[k]))}`,
      run: async (c) => {
        const to = (c.bag.payees as string[])[i];
        const r = await bankCall<BankRecord>("customer/transfer", { body: { account_id: OUTSIDER.account, to, amount: n(p[k]), channel: "IMPS" }, token: c.customer });
        return { note: `${r.ref}: ${rupees(n(p[k]))} by IMPS to ${to}` };
      },
    })),
  ],
  takeaway: "No employee is in this chain, so Alibi has nothing to explain. The evidence is the device, the reset and the payees.",
};

// ── 3. money mule pass-through ──────────────────────────────────────────────

const MULE = { account: "A-5636", customer: "C-39423" };
const MAX_OUT = 95_000; // under the account's ₹1,00,000 transaction limit

function forwards(p: Params): number[] {
  let total = Math.round((n(p.credits) * n(p.each) * n(p.pct)) / 100);
  const out: number[] = [];
  while (total > 0) {
    const part = Math.min(total, MAX_OUT);
    out.push(part);
    total -= part;
  }
  return out;
}

const mule: Playbook = {
  key: "mule",
  title: "Money-mule pass-through",
  kind: "fraud",
  icon: Shuffle,
  tagline: "Scam money lands from several banks and is forwarded within minutes: a layering hop.",
  brief:
    "Sandeep Fernandes has rented out his salary account. Victims of an investment scam pay into it from different banks; " +
    "within minutes he forwards almost everything to a new payee. On its own this is one hop of laundering, " +
    "not yet an investigation: SUTRA records the signal and keeps it on file until it joins a chain.",
  expectText: "A rapid pass-through signal (G2) on the account. One account passing money on is a signal, not yet a case.",
  expect: { alert: null, signal: "G2" },
  victim: () => MULE.account,
  fields: [
    { key: "at", label: "Mule signs in at", kind: "time", min: "09:00", max: "21:00" },
    { key: "credits", label: "Incoming payments", kind: "number", min: 2, max: 4, step: 1 },
    { key: "each", label: "Each payment (₹)", kind: "number", min: 20_000, max: 90_000, step: 5_000, help: "G2 looks at inflows of ₹20,000 or more." },
    { key: "pct", label: "Share forwarded (%)", kind: "number", min: 50, max: 100, step: 5, help: "G2 fires when ≥ 90% of an inflow leaves within 60 min." },
  ],
  defaults: { at: "16:30", credits: 3, each: 40_000, pct: 95 },
  steps: (p) => {
    const outs = forwards(p);
    return [
      {
        key: "login", actor: "mule", system: "Digital banking", title: "The mule opens the banking app and waits",
        story: "Usual phone, usual city. Nothing about the sign-in itself is odd.",
        cta: "Sign in",
        run: async () => {
          await at(s(p.at));
          const r = await bankCall<{ token: string }>("customer/login", { body: { customer_id: MULE.customer, new_device: false } });
          const senders = await freshExternals(r.token, MULE.account, n(p.credits) + 1);
          return { note: "Signed in on the usual phone", customer: r.token,
            bag: { senders: senders.slice(0, -1).map((x) => x.account), out: senders.at(-1)!.account, outName: senders.at(-1)!.name } };
        },
      },
      ...Array.from({ length: n(p.credits) }, (_, i): Step => ({
        key: `credit-${i}`, actor: "victims", system: "IMPS switch", title: `Payment ${i + 1} of ${n(p.credits)} arrives: ${rupees(n(p.each))}`,
        story: i === 0 ? "A scam victim at another bank pays what they think is an investment platform." : "Another victim, another bank.",
        cta: "Receive the payment",
        run: async (c) => {
          const from = (c.bag.senders as string[])[i];
          const r = await bankCall<{ transactionId: string }>(`accounts/${MULE.account}/credit`, { body: { fromAccount: from, amount: n(p.each), channel: "IMPS" } });
          return { note: `${r.transactionId}: ${rupees(n(p.each))} in from ${from}` };
        },
      })),
      {
        key: "payee", actor: "mule", system: "Digital banking", title: "Add the next hop as a payee",
        story: "The handler sends an account number on a messaging app. The mule adds it.",
        cta: "Add the payee",
        run: async (c) => {
          await bankCall("customer/payees", { body: { account_id: MULE.account, counterparty: c.bag.out }, token: c.customer });
          return { note: `Payee added: ${String(c.bag.out)} (${String(c.bag.outName)})` };
        },
      },
      ...outs.map((amt, i): Step => ({
        key: `forward-${i}`, actor: "mule", system: "IMPS switch", title: `Forward ${rupees(amt)}`,
        story: i === 0 ? "Minutes after the money arrived, it leaves. The mule keeps a small cut." : "The rest goes too.",
        cta: `Forward ${rupees(amt)}`,
        run: async (c) => {
          const r = await bankCall<BankRecord>("customer/transfer", { body: { account_id: MULE.account, to: c.bag.out, amount: amt, channel: "IMPS" }, token: c.customer });
          return { note: `${r.ref}: ${rupees(amt)} by IMPS to ${String(c.bag.out)}` };
        },
      })),
    ];
  },
  takeaway: "A signal is not an alert. SUTRA raises an alert only when it can follow a chain to money leaving; the signal stays on the account's file.",
};

// ── 4. the legitimate twin ──────────────────────────────────────────────────

const CAMP = { officer: "EMP-0266", account: "A-1028", customer: "C-79086" };

const camp: Playbook = {
  key: "camp",
  title: "Legitimate twin: pension camp",
  kind: "twin",
  icon: Building2,
  tagline: "The same mobile-number change on a dormant account, done properly. It must not raise an alert.",
  brief:
    "EMP-0266 is rostered on an evening pension camp. Rupali Nair, a dormant pensioner, is at the desk in person. " +
    "The officer raises a ticket, captures her Aadhaar biometric and changes her mobile. No money moves. " +
    "This is the control for the insider takeover: it differs by the explanatory facts, and SUTRA has to stay quiet.",
  expectText: "No alert. Alibi explains every staff access with the ticket, the eKYC, the customer's presence and the roster.",
  expect: { alert: null, alibi: { employee: CAMP.officer, verdict: "EXPLAINED" } },
  victim: () => CAMP.account,
  fields: [
    { key: "at", label: "Customer at the desk at", kind: "time", min: "17:45", max: "21:30", help: "The camp shift runs 17:30–22:30." },
    { key: "mobile", label: "Customer's new mobile", kind: "text" },
  ],
  defaults: { at: "19:05", mobile: "9123456780" },
  steps: (p) => [
    {
      key: "login", actor: "staff", system: "Branch SSO", title: "Sign in at the camp terminal",
      story: "On a branch terminal, not over VPN, during a rostered shift.",
      cta: "Sign in at the branch",
      run: async () => {
        await at(s(p.at));
        const r = await bankCall<{ session_id: string; token: string }>("staff/login", { body: { employee_id: CAMP.officer, channel: "BRANCH" } });
        return { note: `Branch session ${r.session_id}`, staff: r.token };
      },
    },
    {
      key: "roster", actor: "backstory", system: "HRMS", title: "On the camp roster, 17:30–22:30",
      story: "The branch rostered the officer for the evening camp in advance.",
      cta: "Bring the roster on record",
      run: async (c) => {
        const r = await bankCall<BankRecord>("staff/setup/roster", { body: { start: "17:30", end: "22:30" }, token: c.staff });
        return { note: r.summary };
      },
    },
    {
      key: "open", actor: "staff", system: "Core banking", title: "Look up the customer who is at the desk",
      story: "Rupali Nair hands over her passbook.",
      cta: "Search the customer",
      run: async (c) => {
        await bankCall("staff/customer", { body: { customer_id: CAMP.customer }, token: c.staff });
        return { note: `Customer ${CAMP.customer} opened` };
      },
    },
    {
      key: "ticket", actor: "staff", system: "Service desk", title: "Raise a service ticket",
      story: "The request is written down before anything changes.",
      cta: "Raise the ticket",
      run: async (c) => {
        const r = await bankCall<BankRecord>("staff/ticket", { body: { account_id: CAMP.account, note: "Pension camp: update registered mobile — customer present" }, token: c.staff });
        return { note: r.summary };
      },
    },
    {
      key: "ekyc", actor: "staff", system: "UIDAI eKYC", title: "Capture the customer's biometric eKYC",
      story: "Her fingerprint proves she is present and consents.",
      cta: "Capture eKYC",
      run: async (c) => {
        const r = await bankCall<BankRecord>("staff/ekyc", { body: { account_id: CAMP.account }, token: c.staff });
        return { note: r.summary };
      },
    },
    {
      key: "mobile", actor: "staff", system: "Core banking", title: "Change the registered mobile, authorised by biometric",
      story: "Same field, same kind of account as the insider takeover. No override, no limit change, no money.",
      cta: "Change the mobile",
      run: async (c) => {
        await bankCall("staff/account", { body: { account_id: CAMP.account }, token: c.staff });
        await bankCall("staff/mobile", { body: { account_id: CAMP.account, new_mobile: s(p.mobile), auth: "BIOMETRIC" }, token: c.staff });
        return { note: `Registered mobile → +91 ••••• ${s(p.mobile).slice(-4)} (authorised by BIOMETRIC)` };
      },
    },
  ],
  takeaway: "Run the insider takeover next to this. The records differ only in the reasons behind them, and that is the difference SUTRA acts on.",
};

export const PLAYBOOKS: Playbook[] = [insider, outsider, mule, camp];
export const playbook = (key: string | null | undefined) => PLAYBOOKS.find((x) => x.key === key) ?? null;

/** Problems with the chosen parameters, before anything reaches the bank. */
export function checkParams(pb: Playbook, p: Params, victim: Account | undefined): string[] {
  const errs: string[] = [];
  for (const f of pb.fields) {
    const v = p[f.key];
    if (f.kind === "time") {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(s(v))) errs.push(`${f.label}: enter a time as HH:MM.`);
      else if ((f.min && s(v) < s(f.min)) || (f.max && s(v) > s(f.max))) errs.push(`${f.label}: between ${f.min} and ${f.max}.`);
    }
    if (f.kind === "number" && (Number.isNaN(n(v)) || n(v) < Number(f.min) || n(v) > Number(f.max)))
      errs.push(`${f.label}: between ${Number(f.min).toLocaleString("en-IN")} and ${Number(f.max).toLocaleString("en-IN")}.`);
    if (f.kind === "multi" && !list(v).length) errs.push(`${f.label}: choose at least one.`);
    if (f.kind === "text" && !/^[6-9]\d{9}$/.test(s(v))) errs.push(`${f.label}: 10 digits starting with 6, 7, 8 or 9.`);
  }
  if (pb.key === "insider") {
    if (n(p.amount) > n(p.limit)) errs.push("Each transfer must fit under the new limit, or the bank will refuse it.");
    if (victim && n(p.amount) * list(p.mules).length > victim.balance)
      errs.push(`The account holds ${rupees(victim.balance)}; ${rupees(n(p.amount) * list(p.mules).length)} will not fit.`);
  }
  if (pb.key === "outsider" && victim && n(p.amount1) + n(p.amount2) > victim.balance)
    errs.push(`The account holds ${rupees(victim.balance)}.`);
  return errs;
}

/** Money the playbook moves out of the target account, for the briefing. */
export function moneyOut(pb: Playbook, p: Params): number {
  if (pb.key === "insider") return n(p.amount) * list(p.mules).length;
  if (pb.key === "outsider") return n(p.amount1) + n(p.amount2);
  if (pb.key === "mule") return forwards(p).reduce((a, b) => a + b, 0);
  return 0;
}
