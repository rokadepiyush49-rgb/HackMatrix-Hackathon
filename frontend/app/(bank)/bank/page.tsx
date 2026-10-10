"use client";

import { ArrowRight, Building2, Smartphone } from "lucide-react";
import Link from "next/link";

import { ScenarioPanel } from "@/components/bank/scenario-panel";
import { Card, RecordsList, useBankActivity } from "@/components/bank/shell";

const INSIDER = [
  ["Staff · Core banking", "Sign in as an ops officer, VPN from home. Set the bank time to about 21:20 first (after the 18:30 shift)."],
  ["Staff · Branch manager setup", "Grant the officer the old camp override (granted 16 Sep, expired 18 Sep, never revoked)."],
  ["Staff · Core banking", "Search a dormant account (e.g. A-5661, Kavita Gupta), open it, change the registered mobile with the override, raise the transaction limit to ₹5,00,000."],
  ["Customer · NetBanking", "Sign in as that customer on a new phone (the OTP now goes to the number you set), reset the password, add A-7731 and A-7768 as payees."],
  ["Customer · NetBanking", "Send ₹4,00,000 to each. The old ₹1,00,000 limit would have refused it."],
  ["SUTRA · Live Ops → Kestrel Bank", "Press Run detection now. Expect a P1 with four unexplained staff accesses."],
] as const;

const LEGIT = [
  ["Staff · Branch manager setup", "Roster the officer for an evening camp shift (17:30–22:30)."],
  ["Staff · Core banking", "Sign in at the branch terminal around 19:10, open the customer, raise a service ticket, capture a biometric eKYC."],
  ["Staff · Core banking", "Change the registered mobile, authorised by the customer's biometric. Move no money."],
  ["SUTRA · Live Ops → Kestrel Bank", "Run detection. Expect no alert: Alibi finds the ticket, the eKYC and the roster."],
] as const;

export default function BankHome() {
  const activity = useBankActivity();
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-[24px] font-semibold tracking-tight">The bank&apos;s own systems</h1>
          <p className="mt-1 max-w-[70ch] text-[14px] text-[#3c4a46]">
            A working test bank. Do what a member of staff or a customer would do. Every action is recorded by the system that
            handles it (VPN, core banking, the service desk, NetBanking, the payment switch) and reaches SUTRA straight away, as a
            real bank&apos;s feeds would. SUTRA never sees what you meant to do, only what the bank recorded.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Link href="/bank/staff" className="group rounded-lg border border-[#d5dcd9] bg-white p-4 hover:border-[#0f6b50]">
            <Building2 className="text-[#0f6b50]" size={22} />
            <h2 className="mt-2 text-[16px] font-semibold">Staff · Core banking</h2>
            <p className="mt-1 text-[13px] text-[#3c4a46]">Sign in as an employee from the branch or over VPN. Search customers, open accounts, change mobile numbers and limits, raise tickets, capture eKYC.</p>
            <span className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-[#0f6b50]">Open the console <ArrowRight size={14} /></span>
          </Link>
          <Link href="/bank/netbanking" className="group rounded-lg border border-[#d5dcd9] bg-white p-4 hover:border-[#0f6b50]">
            <Smartphone className="text-[#0f6b50]" size={22} />
            <h2 className="mt-2 text-[16px] font-semibold">Customer · NetBanking</h2>
            <p className="mt-1 text-[13px] text-[#3c4a46]">Sign in as a customer on their usual phone or a new one. Reset the password, add payees, send money by IMPS, NEFT or UPI.</p>
            <span className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-[#0f6b50]">Open NetBanking <ArrowRight size={14} /></span>
          </Link>
        </div>
        <ScenarioPanel />
        <Card title="Stage the insider takeover" sub="About three minutes of clicking. Use two browser windows side by side: the bank and SUTRA.">
          <Steps steps={INSIDER} />
        </Card>
        <Card title="Then the legitimate version" sub="The same mobile change with the paperwork a real camp has. Use another dormant account, or undo the bank activity in SUTRA first.">
          <Steps steps={LEGIT} />
        </Card>
      </div>
      <Card title="What the bank has recorded" sub="Newest last. These rows are SUTRA's input.">
        <RecordsList records={activity.data ?? []} empty="Nothing yet. Sign in to the staff console or NetBanking to begin." />
      </Card>
    </div>
  );
}

function Steps({ steps }: { steps: readonly (readonly [string, string])[] }) {
  return (
    <ol className="flex flex-col gap-2.5">
      {steps.map(([where, what], i) => (
        <li key={i} className="grid grid-cols-[26px_minmax(0,1fr)] gap-2.5 text-[13px]">
          <span className="grid size-6 place-items-center rounded-full bg-[#0f6b50] font-mono text-[11.5px] text-white">{i + 1}</span>
          <span><b className="font-semibold">{where}.</b> <span className="text-[#3c4a46]">{what}</span></span>
        </li>
      ))}
    </ol>
  );
}
