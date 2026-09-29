"use client";

import { motion } from "motion/react";
import { ArrowRight, Loader2, Lock, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Sparkle, ThreadIllustration } from "@/components/ui/doodles";
import { PillLink, rise, stagger } from "@/components/ui/primitives";

interface Persona {
  id: string;
  display_name: string;
  title: string;
  role: string;
}

const ROLE_HINT: Record<string, string> = {
  L2_INVESTIGATOR: "Investigates chains end to end",
  VIGILANCE: "Staff accountability · four-eyes reviewer",
  PRINCIPAL_OFFICER: "Files STRs to FIU-IND",
  INSIDER_RISK: "Owns access monitoring",
  TEAM_LEAD: "Assigns and reviews cases",
  L1_ANALYST: "Triage",
  AUDITOR: "Read-only · reproduces decisions",
  ADMIN: "Platform administration",
};

const STEPS = [
  { t: "12 Sep", label: "Override granted", lane: 0 },
  { t: "21:47", label: "Off-hours login", lane: 1 },
  { t: "21:52", label: "Mobile changed", lane: 1 },
  { t: "22:14", label: "3 payees", lane: 2 },
  { t: "22:34", label: "₹14.7 L out", lane: 2 },
  { t: "23:58", label: "Loop closes", lane: 3 },
];
const LANES = ["IAM", "SOC", "FRAUD OPS", "AML"];
const LANE_FILL = ["#fbe7a8", "#c9d4fb", "#f8d3f9", "#cdf1dc"];

function Thesis() {
  return (
    <div className="relative">
      <svg viewBox="0 0 560 250" className="w-full" role="img" aria-label="A privilege-to-payment chain crossing four team lanes">
        {LANES.map((l, i) => (
          <g key={l}>
            <rect x="0" y={20 + i * 55} width="560" height="44" rx="22" fill={LANE_FILL[i]} />
            <text x="18" y={46 + i * 55} className="text-[10px] font-semibold tracking-[0.08em]" fill="#111114" opacity="0.6">{l}</text>
          </g>
        ))}
        {STEPS.map((s, i) => {
          const px = (k: number) => 100 + k * 87;
          const x = px(i);
          const y = 42 + s.lane * 55;
          const prev = STEPS[i - 1];
          const last = i === STEPS.length - 1;
          // Labels get a halo in their lane colour so the thread never runs through the text.
          const halo = { stroke: LANE_FILL[s.lane], strokeWidth: 5, paintOrder: "stroke" as const, strokeLinejoin: "round" as const };
          return (
            <g key={i}>
              {prev && (
                <motion.line
                  x1={px(i - 1)} y1={42 + prev.lane * 55} x2={x} y2={y}
                  stroke="#111114" strokeWidth="1.8" strokeLinecap="round"
                  initial={{ pathLength: 0 }} animate={{ pathLength: 1 }}
                  transition={{ delay: 0.4 + i * 0.35, duration: 0.35 }}
                />
              )}
              <motion.circle cx={x} cy={y} r="7" fill={i === STEPS.length - 2 ? "#ff9b3f" : "#fff"} stroke="#111114" strokeWidth="2"
                initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 0.3 + i * 0.35, type: "spring" }} />
              <motion.text x={last ? x + 9 : x} y={y - 13} textAnchor={last ? "end" : "middle"} className="text-[9.5px] font-semibold" fill="#111114" style={halo}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.45 + i * 0.35 }}>
                {s.label}
              </motion.text>
              <motion.text x={last ? x + 9 : x} y={y + 21} textAnchor={last ? "end" : "middle"} className="num text-[9.5px]" fill="#111114" style={halo}
                initial={{ opacity: 0 }} animate={{ opacity: 0.6 }} transition={{ delay: 0.45 + i * 0.35 }}>
                {s.t}
              </motion.text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function LoginInner() {
  const router = useRouter();
  const next = useSearchParams().get("next") ?? "/";
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");

  useEffect(() => {
    fetch("/api/sutra/auth/demo-users").then((r) => (r.ok ? r.json() : [])).then(setPersonas).catch(() => setPersonas([]));
  }, []);

  async function signIn(body: Record<string, unknown>, key: string) {
    setBusy(key);
    setError(null);
    const res = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.ok) {
      router.push(next);
      router.refresh();
    } else {
      const j = await res.json().catch(() => ({}));
      setError(typeof j.detail === "string" ? j.detail : "Sign-in failed");
      setBusy(null);
    }
  }

  const featured = ["ananya", "suresh", "farah", "karthik", "meera", "audit"];
  const list = personas.filter((p) => featured.includes(p.id)).sort((a, b) => featured.indexOf(a.id) - featured.indexOf(b.id));
  const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2);

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-4 pb-16 sm:px-6">
      <nav className="flex items-center justify-between py-5">
        <span className="flex items-center gap-2 text-[24px] font-semibold text-ink">
          <Sparkle className="size-6 text-ink" fill="var(--color-tangerine)" /> sutra
        </span>
        <span className="rounded-full bg-panel px-3.5 py-1.5 text-[12px] text-muted shadow-sm">Synthetic demo · Kestrel UCB</span>
      </nav>

      <motion.section variants={stagger} initial="hidden" animate="show" className="grid gap-4 lg:grid-cols-12">
        {/* hero: doodle on paper, orchid band below — the Disha landing card */}
        <motion.div variants={rise} className="relative flex flex-col overflow-hidden rounded-[var(--radius-blob)] bg-paper text-pastel-ink lg:col-span-7">
          <div className="px-6 pt-6">
            <ThreadIllustration className="mx-auto h-52 w-full max-w-md sm:h-60" />
          </div>
          <div className="flex flex-1 flex-col rounded-t-[var(--radius-blob)] bg-orchid px-6 pt-8 pb-8 sm:px-10">
            <h1 className="display text-[34px] leading-[1.15] font-light sm:text-[44px]">
              Follow the thread from <span className="font-semibold">privilege</span> to <span className="font-semibold">payment</span>.
            </h1>
            <p className="mt-4 max-w-[52ch] text-[15px] leading-[1.6] opacity-85">
              SUTRA rebuilds the chain from an employee&apos;s access to the money moving, tests every access for a
              legitimate reason, and argues each alert both ways — with evidence, never a score.
            </p>
            <p className="mt-4 flex items-center gap-2 text-[13px] font-medium">
              <Sparkles size={15} /> Access → money in 47 min · each team saw one segment
            </p>
            <div className="min-h-7 flex-1" />
            <div className="relative rounded-full bg-paper px-4 py-3" aria-label="One thread across four teams">
              <span className="absolute inset-x-[14%] top-[62%] border-t-2 border-dotted border-pastel-ink/30" aria-hidden />
              <div className="relative grid grid-cols-4 text-center text-[11.5px]">
                {["IAM", "SOC", "Fraud ops", "AML"].map((l, i) => (
                  <div key={l} className="flex flex-col items-center gap-1.5">
                    <span className={i === 3 ? "font-semibold" : "opacity-60"}>{l}</span>
                    <span className={`grid size-7 place-items-center rounded-full text-[12px] ${i === 3 ? "bg-tangerine" : "bg-pastel-ink text-paper"}`}>✓</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <Sparkle className="absolute top-8 right-8 size-7 animate-[var(--animate-twinkle)] text-pastel-ink" fill="var(--color-sunflower)" />
        </motion.div>

        {/* sign-in */}
        <motion.div variants={rise} className="panel flex flex-col !rounded-[var(--radius-blob)] p-6 sm:p-8 lg:col-span-5">
          <div className="eyebrow mb-1.5">Sign in</div>
          <h2 className="display text-[26px] leading-[1.2] font-semibold text-ink">Choose a demo persona</h2>
          <p className="mt-1.5 text-[13.5px] leading-[1.55] text-muted">Each persona has different capabilities — try the four-eyes review with two of them.</p>

          <div className="mt-5 flex flex-col gap-2">
            {list.map((p, i) => (
              <motion.div key={p.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.05 }}>
                <PillLink
                  tone={i === 0 ? "ink" : "periwinkle"}
                  onClick={() => signIn({ username: p.id, demo: true }, p.id)}
                  disabled={!!busy}
                  icon={initials(p.display_name)}
                  title={p.display_name}
                  subtitle={`${p.title} · ${ROLE_HINT[p.role] ?? p.role}`}
                  trailing={busy === p.id ? <Loader2 className="size-4 animate-spin" /> : undefined}
                />
              </motion.div>
            ))}
            {personas.length === 0 && (
              <div className="rounded-3xl bg-amber-soft p-4 text-[12.5px] text-amber">
                Can&apos;t reach the SUTRA API. Start it with <code>make api</code>, then reload.
              </div>
            )}
          </div>

          <form onSubmit={(e) => { e.preventDefault(); signIn({ username: user, password: pw }, "form"); }} className="mt-7 space-y-2.5">
            <div className="eyebrow flex items-center gap-1.5"><Lock size={11} /> Or sign in with credentials</div>
            <input id="username" value={user} onChange={(e) => setUser(e.target.value)} placeholder="Username" autoComplete="username"
              className="h-12 w-full rounded-full border border-line bg-panel-2 px-5 text-[14px] text-ink outline-none placeholder:text-faint focus:border-ink/40 focus:bg-panel" />
            <input id="password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" autoComplete="current-password"
              className="h-12 w-full rounded-full border border-line bg-panel-2 px-5 text-[14px] text-ink outline-none placeholder:text-faint focus:border-ink/40 focus:bg-panel" />
            <button type="submit" disabled={!user || !pw || !!busy}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-full bg-primary text-[14px] font-medium text-on-primary transition-[background-color,transform] hover:bg-primary-pressed active:scale-[.98] disabled:opacity-40">
              {busy === "form" ? "Signing in…" : <>Sign in <ArrowRight size={15} /></>}
            </button>
          </form>
          {error && <p className="mt-3 text-[12.5px] text-threat">{error}</p>}
        </motion.div>
      </motion.section>

      {/* the thesis, as a lane chart */}
      <motion.section initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-80px" }} className="mt-4">
        <div className="panel grid items-center gap-6 !rounded-[var(--radius-blob)] p-6 sm:p-10 md:grid-cols-[1fr_1.6fr]">
          <div>
            <p className="eyebrow">Why SUTRA</p>
            <h2 className="display mt-2 text-[26px] leading-snug text-ink sm:text-[32px]">
              One fraud, <span className="font-semibold">four teams</span>, and nobody saw the <span className="font-semibold">whole thread</span>.
            </h2>
            <p className="mt-3 text-[14px] text-muted">
              IAM saw an override, the SOC an off-hours login, fraud ops a new payee and AML a closing loop. SUTRA joins them into one chain.
            </p>
          </div>
          <Thesis />
        </div>
      </motion.section>

      <p className="mt-8 text-center text-[12px] text-muted">Kestrel Urban Co-operative Bank is fictional. All data is synthetic.</p>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
