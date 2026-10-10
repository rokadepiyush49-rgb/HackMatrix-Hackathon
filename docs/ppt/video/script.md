# SUTRA — presentation video script (Team Admiral · FIN04)

Target length: **~4:00** (current cut: 3:59). Order: Slides 1–3 → live demo → Slides 4–7.
Timestamps match `SUTRA_Admiral_FIN04_demo.mp4`. Words per section are sized for a calm ~180 wpm.

---

## Part 1 — Slides (0:00 – 1:02)

**[0:00] Slide 1 · Title**
> Hi, we are Team Admiral, and this is SUTRA, our solution for FIN04: Financial Crime and Insider Risk Intelligence.

**[0:09] Slide 2 · Abstract**
> SUTRA is an AI-assisted investigation platform that connects what a privileged employee did inside a bank to the money that moved afterwards. It rebuilds scattered events into one time-ordered chain, and checks whether every access had a legitimate reason.

**[0:24] Slide 3 · Problem & solution**
> Here's the problem. In insider fraud, IAM, the SOC, fraud ops and AML each see one piece of the chain. Nobody sees the whole thread. Logs show who and when, but never why, so honest employees get flagged too. And alerts arrive as opaque scores.
> SUTRA answers with three engines. **Needle** rebuilds the privilege-to-payment chain. **Alibi** checks every access against tickets, portfolios, queues and rosters. And **Brief** argues each alert both ways: prosecution and defence. A multi-agent council, and **Mend**, our counterfactual control lab, complete the picture. Let us show you.

---

## Part 2 — Live demo (1:02 – 2:47)

| Time | On screen | Say |
|---|---|---|
| 1:02 | `/login` → click **Ananya Rao** → Command Center; point at **₹1.09 Cr at risk**, scroll to the live threat rail | We log in as Ananya, an L2 fraud investigator. The Command Center shows ₹1.09 crore at risk across five active chains, and the live threat rail surfaces our flagship case. |
| 1:14 | **Open top case** (`/cases/AL-0921-001`); hover each hop E0 → E6 on the timeline | An ops officer used a temporary override, granted nine and a half days earlier and never revoked, to log in after hours, change a dormant pensioner's mobile number, add three payees, and move ₹14.7 lakh, just 47 minutes after first access. Every hop is backed by IAM, SOC, fraud or AML evidence. |
| 1:36 | Click **Ask SUTRA** → "Why was this flagged?" | Ask SUTRA explains why the case was flagged, in plain language. Every sentence cites evidence codes, and any claim that isn't supported is dropped. |
| 1:45 | **Prosecution & Defence** (`/evidence/arguments`), scroll slowly | Instead of a risk score, SUTRA argues the case. Prosecution grounds cite evidence on the left. On the right, the defence tests innocent explanations, like a compromised credential, before anything is escalated. |
| 1:59 | **Alibi Ledger** (`/alibi`); point at 98.4% | The Alibi Ledger reconciled over 55,000 staff accesses. 98.4% were explained, and only four stayed unexplained. So investigators see five alerts, not seven hundred. |
| 2:13 | **Council** → Convene the takeover case (`/council/AL-0921-001`) | In the Evidence War Room, eight specialist agents debate the same records, request missing evidence, and hand a structured finding, including dissent, to a human, who always makes the final decision. |
| 2:26 | **Control Lab** (`/controls`); toggle **C1 Expire temporary entitlements** → "Stopped at E0" | Control Lab asks: what would have stopped this? Auto-expiring temporary entitlements breaks the chain at the very first hop, almost seven days early, with zero impact on legitimate operations. |
| 2:38 | **Twin Scenario Lab** (`/lab`) | And every fraud scenario has a legitimate twin. SUTRA catches all six frauds, and stays quiet on all eight twins. |

---

## Part 3 — Slides (2:47 – 3:59)

**[2:47] Slide 4 · Technical approach**
> Under the hood: Next.js and FastAPI on PostgreSQL, with bitemporal event storage. The detection pipeline runs Alibi, entity resolution, ten rules and five graph and ML signals, then Needle and Brief. Our models are glass-box: logistic regression and LightGBM with SHAP explanations. And the LLM only writes language. It never scores or closes an alert.

**[3:11] Slide 5 · Feasibility & viability**
> It's feasible today: one `docker compose` command runs the full MVP on a laptop, over 400,000 synthetic transactions. And it's viable: 1,457 urban co-operative banks form our beachhead, with RBI's 2024 fraud-risk directions creating regulatory pull. SUTRA plugs into existing systems. No rip and replace.

**[3:34] Slide 6 · Impact & benefits**
> The impact: fairer investigations for employees, far less manual correlation for analysts, and for banks, a shift from investigating fraud after the fact, to fixing the control that enabled it.

**[3:47] Slide 7 · Research & references**
> SUTRA builds on research in explanation-based auditing, temporal cycle detection, and the AMLworld benchmark. Trace every rupee back to the privileged action that made it possible. Thank you.

---

## Recording it yourselves

The MP4 uses a synthetic macOS voice (Rishi) as a placeholder. A real team voice will land better with judges:

1. Open the MP4 in QuickTime with the sound muted and read along with the timestamps above. Or split the parts: one member per slide section and one for the demo.
2. Record with **⌘⇧5 → Record Selected Portion** plus your mic, or record voice only in QuickTime (**File → New Audio Recording**) and drop it over the video in iMovie or CapCut.
3. For a live-recorded demo, log in at http://localhost:3000 as **Ananya Rao** and follow the "On screen" column. Every page is already seeded.

`SUTRA_Admiral_FIN04_demo.srt` has matching captions, if the submission portal accepts subtitles.
