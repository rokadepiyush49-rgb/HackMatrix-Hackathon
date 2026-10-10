# On-site demo script — 8 minutes, end to end

Everything below runs on one laptop with no internet: Postgres, the API, the web app, the models
and the voices are all local. All data is synthetic; Kestrel Urban Co-operative Bank is fictional.

## Before the judges arrive (T – 30 min)

1. **Data.** On a fresh machine run `make demo` (about 3 minutes). If the feed was played in a
   rehearsal, reset it: `make live-reset` (about 25 s), or **Reset demo** on the Live Ops page.
2. **Start** the API and web app (`make api`, `make web`). Open http://localhost:3000 and sign in as
   **Ananya Rao** (L2 investigator).
3. **Open Live Ops** in the sidebar. Check that it reads *247 rows · Queued for tonight* with
   **Play tonight's feed** enabled. Pick a speed: **240×** (about 40 s of feed) for a relaxed pace,
   **600×** (about 16 s) when time is short.
4. **Voice.** Turn **Voice** on (Live Ops header, Council toolbar), play one Council line, and set
   the volume for the room. Voices come from the operating system. For an Indian-English voice:
   - macOS: System Settings → Accessibility → Spoken Content → System voice → Manage Voices →
     English (India) → *Rishi* or *Veena*.
   - Windows: Edge offers *Microsoft Neerja* and *Prabhat*.

   Without them, SUTRA falls back to the best English voices it finds.
5. **Screen.** Use full screen and keep the browser at 90%. On a 1280 px projector the three Live Ops
   columns stack, so zoom to 80% to keep input, engines and output side by side.

## The flow

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | Command Center | — | "Insider fraud is invisible to any single team. IAM saw an override, the SOC saw a late login, Fraud saw new payees, AML saw layering. Nobody saw the thread." |
| 0:45 | **Live Ops** | Point at the queued rows and the source-system chips | "This is tonight, 22 September, and none of it has happened yet: 247 raw rows from 11 systems — VPN, core banking, the UPI switch, the service desk. They are not in the database. Hidden in them is an insider takeover, and a legitimate pension camp doing exactly the same thing." |
| 1:15 | Live Ops | **Play tonight's feed** | While rows land: "20:31, a VPN login from Nashik… a dormant pensioner's mobile number changed with an override… the limit raised to ₹5 L… a brand-new phone… three payees… ₹4.85 L out. And at Hadapsar, the camp's two mobile changes." |
| 1:55 | Live Ops — engines | Let the stages tick | "Same code as the production job, re-reading all 90 days. Alibi tests all 55,760 staff accesses for a legitimate reason; Needle assembles chains; Brief grades the evidence. These timings are real." |
| 2:20 | Live Ops — output | The P1 card appears (voice announces it) | Read the chain: "Override granted for a camp on 16 Sep, meant to expire on the 18th, never revoked. Off-hours login. Dormant account. Mobile changed, limit raised. Accomplice's new device, three payees, **₹14.15 L gone 41 minutes after the login**, into the *same mule ring* as last night: A-7731, A-7768 → RK Traders → Shree Bullion House." |
| 3:00 | Alibi panel | Point at the two cards | "Same action, opposite verdicts. The camp officer's four accesses are explained: camp roster, ticket, biometric eKYC. The insider's four have zero of five reasons. That's the difference between an alert and an argument." |
| 3:25 | Ground truth | **Reveal ground truth** on the input panel | "The simulator's labels, hidden until now. The P1 cites 17 of the attack's 24 rows and none of the 223 legitimate ones. All 14 scenario checks still pass. Last night's mule-factory case now cites tonight's payouts, with the same alert ID." |
| 3:50 | **Live Ops → Your input** | Hand the console to a judge: pick a preset (*Forged ticket* works well), change anything, **Send to the bank** | "Now you are the insider. Your choices become the rows each bank system would record — nothing on the form decides the outcome." Read the verdict and its reason; show the Alibi card (the ticket explains the mobile change, not the 21:20 timing or the limit raise). **Undo my input** afterwards (≈ 25 s). |
| 4:50 | **Council** | **Convene the Council**, Voice on | "Eight agents argue the case from the same records, each in its own voice. The Defence challenges, the Alibi agent asks for the roster, and the moderator retrieves it or says it isn't ingested. No confidence score, and dissent stays on the record." Skip to the ruling after one round if time is short. |
| 5:30 | **Control Lab** | **Which control stops it** | "Expiring temporary entitlements on time would have broken this chain at E0, days before the money moved, and the friction on legitimate work is measured, not guessed." |
| 6:30 | Case → Evidence | **Open case** → propose → (Suresh) review → evidence pack | "Four-eyes: the investigator proposes, vigilance decides. The evidence pack is hashed and written once; in production it sits in S3 Object Lock for five years under PMLA." |
| 7:30 | Close | **Reset demo** for the next judge | "In production this runs every 15 minutes on EKS in Mumbai, data stays in India, and re-runs never touch an open case." |

## Numbers to have ready

From the local run; they are deterministic for seed 42.

- Feed: 247 rows from 11 systems, 20:02 → 22:39 on 22 Sep. 24 attack rows, 10 camp rows, 213 routine.
- Insider: **EMP-0919**, ops officer at BR-033 Nashik Road, working on a VPN laptop. Override
  REQ-7777 was granted on 16 Sep, intended to expire on 18 Sep, and was never revoked.
- Victim: **A-5361**, a pensioner's savings account, inoperative since Nov 2023, holding ₹21.40 L.
  Payouts of ₹4.85 + 4.70 + 4.60 L = **₹14.15 L**, starting 41 min after the login.
- The camp: EMP-0172 at BR-021 Hadapsar, rostered 17:30–22:30, two pensioners, ticket + biometric eKYC.
- New alert: **AL-0922-003** (P1, insider-enabled takeover). Updated: **AL-0922-001** (mule factory).
- Detection on an M-series laptop: about 23 s.
  - Alibi about 9 s, signals about 3 s, Needle about 3 s, Brief about 2.5 s.
  - Persist about 2.5 s (one transaction).

## If something goes wrong

| Symptom | Fix |
|---|---|
| A run fails or the API restarted mid-run | **Reset demo**, then play again (≈ 25 s), or `make live-reset` in a terminal. |
| The page was reloaded during a run | Nothing to do — it re-attaches and replays the run's progress. |
| No sound | Check the system volume and the OS voice list; Chrome and Edge work best. The visual flow does not depend on voice. |
| No internet at the venue | Nothing changes: Ask SUTRA uses its deterministic engine, voices are local, data is local. |
| "Is it really live?" | Show the terminal: `make live-reset` then `make live-play` runs the same code from the CLI with the same timings. In the UI, nothing is in the database before Play — the input panel says so. |

## Rehearse from the terminal

```bash
make live-reset    # undo tonight and re-detect
make live-play     # stream the evening and detect — prints every stage and the new alert
```

## Your input: four presets and what SUTRA does with them

Same officer (EMP-0258) and account (A-5661, dormant, ₹8.87 L) each time; only the choices change.

| Preset | What the judge chooses | Result |
|---|---|---|
| Insider takeover | 21:20 VPN, expired override, mobile + limit, accomplice's phone, ₹4 L × 2 to the 21 Sep ring | **P1**, 17 signals, all 4 accesses unexplained |
| Legitimate camp update | 19:10 branch, ticket + biometric eKYC + camp roster, mobile change only | **No alert** — Alibi explains every access |
| Forged ticket | The takeover plus a ticket filed by the insider | **Still P1** — the ticket explains the purpose, not the timing or the limit raise |
| Quiet daytime takeover | 11:40 branch, no override, ₹90,000 to an outside account | **P2** — smaller and inside office hours lowers urgency, the chain remains |

## Test it yourself in Kestrel Bank

Open two windows side by side: **http://localhost:3000/bank** (the bank) and **SUTRA → Live Ops → Kestrel Bank**.

1. **Bank header → Set time** to 21:20 (after the 18:30 shift).
2. **Staff · Core banking**: sign in as EMP-0258, *VPN from home*. In *Branch manager · setup*, grant the **old camp
   override, never revoked**. Search **A-5661**, open the customer and the account, **change the mobile** (authorised by
   override) and **raise the transaction limit** to ₹5,00,000 using the override.
3. **Customer · NetBanking**: sign in as Kavita Gupta (A-5661) on **a new phone** — the OTP goes to the number you just
   set. **Reset the password**, add **A-7731** and **A-7768** as payees, send **₹4,00,000** to each.
4. **SUTRA → Kestrel Bank → Run detection now.** Tested result: **P1**, ₹8.00 L at risk, money out 18 minutes after
   the login, all four staff accesses unexplained, 12 of the bank's 17 records linked into the chain.
5. **Undo bank activity** (≈ 25 s) to start again. For the legitimate version, roster a camp shift, sign in at the branch
   around 19:10, raise a ticket, capture an eKYC and change the mobile by biometric: SUTRA stays quiet.

The bank refuses what a bank would: a transfer above the transaction limit or the balance, money to someone who is not
a payee, an override nobody granted, a biometric change with no eKYC.

## FIN-04 final-round segment (about 6 minutes)

What the brief asks to see: a legitimate look-alike, coordinated suspicious activity, late linking
evidence and duplicate delivery, with case history and priority changes. Each replay runs detection twice
(about 25 s per run on an M-series laptop; about 80 s on a Windows laptop with Postgres in Docker). On a
slow machine, run the late-link replay just before the judges arrive and show its case history live.

| Step | Screen | Do | Say |
|---|---|---|---|
| 1 | **Live Ops** | Arrival order → **IMPS connector lags (late linking evidence)** → **Play in this arrival order** | "Same evening, but the IMPS switch's connector is 35 minutes late. Every row is logged with when it happened and when it reached us." |
| 2 | Live Ops — first detection | Point at the empty output after the first checkpoint | "The insider's override, login and mobile change are in. No money has arrived, so there is no chain yet. Absence of evidence is not a finding." |
| 3 | Live Ops — second detection | The 18 IMPS rows land tagged **late · n min behind**; the P1 appears | "The late transfers link the access to the money, and to the same mule ring as last night." |
| 4 | **Case → Case history** on the new P1 and on AL-0922-001 | Expand the newest revisions | "Every revision is kept; the database refuses edits. Here is why it changed: these rows arrived late, the chain gained E5, priority set by this rule. The M7 score is a reason to look first, not a finding." |
| 5 | Live Ops | **Reset demo**, then arrival order **Duplicate delivery + a tampered re-send** → Play | "At-least-once delivery: every transfer arrives twice and one comes back with a changed amount." Point at **duplicate · absorbed** and **refused**. |
| 6 | Terminal or `ml/reports/replay/replay_report.json` | Show `invariant: true` | "We replayed the same evening in order, late, duplicated, shuffled and reversed. All five converge to the same 85 cases, money totals, balances and M7 scores." |
| 7 | Live Ops — Alibi panel | The pension camp | "The legitimate look-alike: same mobile changes, but ticket, eKYC and roster explain them. No alert, whatever the order." |
| 8 | **Council** | **Convene AI agents** (needs `GROQ_API_KEY`), then **Harness trace** | "Agents on Groq argue the case, and the harness decides what counts: claims citing records the agent wasn't given, figures not in the cited record, or 'X committed fraud' are dropped and listed here." Without a key, say "Re-run council" uses the deterministic council, and show the trace from a run saved earlier. |
| 9 | **Case → Account Aggregator** on AL-0918-001 | Request consent → Approve as the customer (demo) → Fetch → open the Council | "A customer-consented statement from another bank, through the RBI Account Aggregator flow. This FIP is a labelled synthetic one; live data needs a licensed FIU. The source-of-funds question the Council couldn't answer is now answered, and cited." |

Before this segment: `make migrate` on an existing database, and `make train` once if `/health/ready`
reports a model as anything other than ok or unregistered.
