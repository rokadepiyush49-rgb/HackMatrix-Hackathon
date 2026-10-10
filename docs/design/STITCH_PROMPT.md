# SUTRA: prompts for Google Stitch

How to use:
1. Paste the **Master prompt** into a new Stitch project (Web / desktop). It sets the product story, the
   beginner-friendly rules and the visual style, and generates the first two screens.
2. Add the other screens one at a time with the **Screen prompts** below. Each one starts with
   "Same app and design system", so Stitch reuses the style.
3. If a screen gets too busy, follow up with: *"Simplify: keep one primary action, move details into an
   expandable section, and add a one-line explanation under the title."*

---

## Master prompt

```
Design a desktop web app called SUTRA. It helps bank investigators catch insider fraud. Many users are beginners (new analysts, students, hackathon judges) who have never used a fraud tool, so every screen must explain itself.

WHAT THE APP DOES, IN PLAIN WORDS
Sometimes a bank employee misuses their system access to take over a customer's account and move money out. Each bank team sees only one small clue: an unusual login, a changed phone number, new payees, a big transfer. SUTRA joins those clues into one story, called a "chain", that runs from the employee's ACCESS to the MONEY that left. For every access it asks "was there a valid reason?" (the "Alibi"). Then it argues every alert both ways, with evidence against and evidence for, instead of giving a mystery score. A human always makes the final decision.

The UI must make this 6-step flow obvious everywhere:
1 Data comes in → 2 Clues found → 3 Clues joined into a chain → 4 Alibi checked → 5 Both sides argued, priority set → 6 Human decides and exports evidence

BEGINNER-FRIENDLY RULES (every screen)
- Page header = title + one sentence on what the page is for + a "How this works" link that opens a side panel with a 3-step illustrated explanation.
- Plain words first, technical term second in small grey text, e.g. "Why was this accessed? · Alibi".
- An (i) tooltip on every jargon word, plus a Glossary that can be opened from anywhere.
- Status is never shown by colour alone: always colour + icon + word.
- Empty states teach: a small line illustration, what will appear here, and the one action to take.
- One primary action per screen (black pill button). Secondary actions are outline pills.
- A "Simple / Expert" toggle in the top bar. Simple view hides raw IDs, detector codes and model numbers.
- Investigation pages show a step tracker: Clues → Chain → Alibi → Arguments → Decision.
- Body text at least 16px, WCAG AA contrast, large click targets, visible keyboard focus rings.
- Global search / command palette (Cmd+K) and a floating "Ask SUTRA" button in the bottom-right corner.

PRIORITY LEVELS (show this legend wherever priority appears)
- P1 Urgent (coral): strong evidence from several systems, no valid reason, money can still be recovered
- P2 High (tangerine): two or more high-risk areas
- P3 Review (periwinkle): one high-risk area, or several medium ones
- Watch (grey): keep an eye on it, not queued yet
- Explained (mint): a valid reason was found and the alert was closed automatically (5% are spot-checked by a person)

VISUAL STYLE: friendly, calm and pastel, not a dark "hacker" dashboard
- Background: soft periwinkle #DCE3FB with a faint grid #C9D4FB
- Cards: white #FFFFFF, very rounded (24px), soft shadow, no borders. Inner panels #F3F4F8
- Text: ink #111114, secondary #5F6376
- Primary button: black pill #111114 with white text
- Colour carries meaning only, never decoration. Each colour has a soft tint for chips:
  Coral #B8322A on #FFD9D4 = suspicious, money at risk, "against"
  Tangerine #9F4A00 on #FFE0C2 = uncertain, open question
  Mint #15703F on #CDF1DC = explained, verified, "for / defence"
  Orchid #8E2A99 on #F8D3F9 = AI or agent insight
  Periwinkle #3B54C9 on #DFE5FD = links, neutral info
- Font: Poppins everywhere. JetBrains Mono for IDs, amounts and timestamps
- Icons: Lucide outline icons. Small friendly line doodles in empty states and onboarding
- Also design a dark "Night" theme: background #0F1226, cards #171B34, same accents slightly lighter

LAYOUT
Collapsible left sidebar. Each item has a plain-language sub-label in small grey text:
  ★ Start here: How SUTRA works
  Home: Command Center (today at a glance), Live Ops (watch it work live)
  Investigate: Case Desk (alerts waiting for a decision), Signal Desk (individual clues), Chain Explorer (access-to-money stories), Money Trail (where the money went), Entity Explorer (people, accounts, devices)
  Understand: Alibi Ledger (was each access justified?), Risk Network, Mule Factory (suspicious account clusters), Timeline Replay
  Decide: Investigation Council (AI agents debate a case), Evidence Packs, For & Against, Missing Evidence, Audit Trail
  Prevent: Control Lab (which rule would have stopped it), Twin Scenario Lab, Control Library
  Admin: Users & Roles, Models & Rules, Approvals, Data Sources, Responsible AI
Top bar: search, Simple/Expert toggle, light/dark toggle, a small "100% synthetic data" badge, and the signed-in user's role chip.

All data is fictional, from "Kestrel Urban Co-operative Bank". Use Indian rupees (₹14.7 L), Indian names, and staff shown as pseudonyms such as "Ops Officer · Branch 12 · EMP-0417".

START WITH TWO SCREENS

1) Command Center (home)
- Greeting + one line: "3 alerts need your decision today."
- 4 summary cards: Urgent (P1) alerts, Money at risk (₹), Explained automatically, Open cases. Each card has a tiny trend line and an (i) tooltip.
- "Needs your attention" list: alert cards showing priority chip, one-sentence story ("Ops officer accessed a dormant pensioner account after hours; ₹14.7 L left 47 minutes later"), time, and an "Open case" button.
- A horizontal "How SUTRA works" strip showing the 6 steps with icons, each step clickable.
- Priority legend card. Recent activity feed on the right.

2) Case Detail (the most important screen)
- Header: case ID, P1 Urgent chip, one-sentence summary, step tracker (Clues → Chain → Alibi → Arguments → Decision), primary button "Make a decision".
- "The story" timeline: a vertical chain of 6 steps, each a card with icon, time, plain sentence and the source system:
  Override access granted, 9.5 days earlier (IAM) → 21:08 Opened a dormant pensioner's account, no ticket, outside shift (Core banking) → 21:12 Customer mobile number changed (Core banking) → 21:31 New login from a new device (NetBanking) → 21:40 Three new payees added → 21:55 ₹14.7 L sent out via IMPS
  The gaps between steps show elapsed time ("+4 min"). A summary pill reads "Access to money: 47 minutes".
- "Was there a valid reason?" card: Alibi verdict UNEXPLAINED (coral), with a checklist of what was searched: service ticket ✗, customer in the officer's portfolio ✗, work-queue item ✗, customer interaction ✗, on shift ✗.
- "Why this priority?" card: the plain-language rule that fired, e.g. "3 areas are High, confirmed by 2 separate systems, no valid reason, and the money can still be recovered → P1".
- 7 risk areas shown as a simple row of labelled level bars (None / Low / Elevated / High): Money movement, Employee behaviour, Access, Network, Timing, Relationships, History.
- Two columns, "Evidence against" (coral) and "Evidence for / innocent explanations tested" (mint), each item with an evidence code chip.
- "What's missing" list (tangerine).
- Right rail: Ask SUTRA chat, Send to Investigation Council, Export evidence pack.
```

---

## Screen prompts (add one at a time)

### Sign in
```
Same app and design system. Sign-in screen. Left: the SUTRA logo, the tagline "Follow the thread from access to money" and a 3-icon explanation (Access → Chain → Money). Right: a "Choose a demo persona" grid of 4 to 6 role cards. Each card shows avatar initials, name, role and a plain line on what they can do (e.g. "Investigator: reviews alerts and decides cases", "Principal Officer: approves suspicious-transaction reports", "Admin: manages users and audits"). Below the grid, a normal email and password form. Footer badge: "All data is synthetic."
```

### First-run welcome tour
```
Same app and design system. A 4-step onboarding modal over a blurred Command Center. Step dots at the top, Back / Next / Skip buttons. Each step has a large friendly line illustration, a title and two sentences:
1 "Clues are scattered": each bank team sees one piece.
2 "SUTRA joins them into a chain": from staff access to money moved.
3 "Every access needs a reason": the Alibi check looks for a ticket, a shift and a customer link.
4 "Both sides, then you decide": evidence for and against; you make the final call.
Last step button: "Show me a real case".
```

### Case Desk (alert queue)
```
Same app and design system. Case Desk: a list of alerts waiting for a decision. Header with one-line explanation and the priority legend. Filter pills: All, P1, P2, P3, Watch, Explained, plus "Assigned to me". Each row is a rounded card: priority chip (colour + icon + word), one-sentence story, amount at risk in mono, the access-to-money time ("47 min"), Alibi verdict chip, assigned investigator, age, and an "Open" button. Simple view hides IDs. Empty state: "Nothing waiting. SUTRA will add alerts here as clues connect."
```

### Alibi Ledger
```
Same app and design system. Alibi Ledger: "Was each staff access justified?" A table of staff accesses to customer accounts: time, staff pseudonym, customer account (masked), action, and verdict chip EXPLAINED (mint) / PARTIAL (tangerine) / UNEXPLAINED (coral). Clicking a row opens a side drawer with a reasons checklist: matching service ticket, customer in the staff member's portfolio, work-queue item, customer interaction, inside rostered shift. Each reason is ticked or crossed with the record that proves it. Top: a donut of verdict counts and a "How the Alibi check works" explainer card.
```

### Investigation Council
```
Same app and design system. Investigation Council: 8 AI specialist agents and a moderator debate one case. Top: the case summary and a "Start debate" button. Centre: a chat-style transcript. Each agent has an avatar, a role name (e.g. AML Analyst, Access Auditor, Defence Advocate, Customer Advocate) and orchid "AI" chips. Every message cites evidence code chips. Agents can "request a record", shown as a small system card. Right panel: the agents with their current stance (leans suspicious / leans innocent / undecided). End: a "Council finding" card with consensus, dissent and recommended next steps, and a clear note: "A human makes the final decision." Include a speaker / play button so the debate can be read aloud.
```

### Ask SUTRA (assistant dock)
```
Same app and design system. A right-side chat drawer called "Ask SUTRA" that opens over any page. Suggested starter questions as chips ("Why is this P1?", "What evidence is missing?", "Explain this in simple words", "Draft an STR"). Answers are short paragraphs where every sentence ends with small evidence code chips you can click. Show a note: "Sentences that can't be backed by evidence are removed automatically." Orchid accent for AI.
```

### Money Trail / Risk Network
```
Same app and design system. Money Trail: a left-to-right flow graph showing where the money went. Rounded node cards for accounts (customer, mule, cash-out) and arrows labelled with amount and time. Suspicious paths in coral, normal ones in grey. A left panel lists hops in order. A legend explains node shapes and colours. Controls: zoom, "fit to screen", and a time slider to replay the money moving. Clicking a node opens a side drawer with account details and links to related cases.
```

### Live Ops
```
Same app and design system. Live Ops: watch SUTRA work in real time. Three columns labelled 1 Input, 2 Processing, 3 Output.
Input: a live feed of raw bank events arriving one by one (time, source system icon, plain summary), with a Play / Pause / Reset demo control.
Processing: a vertical pipeline of stages (Load data, Alibi check, Find clues, Build chains, Score with models, Write briefs) with progress bars and real durations.
Output: new alerts appear as cards with a gentle highlight. A P1 is announced with a banner.
A "Try it yourself" tab with a simple form: choose who logs in and when, what paperwork exists, which account, and where the money goes. Then "Run detection" and "Undo my input".
```

### Evidence Pack
```
Same app and design system. Evidence Packs: a list of exportable case reports, each with case, created by, date, a "Verified, not tampered" mint chip and a "Download PDF" button. A preview pane shows the 11 sections as a checklist with page numbers: Summary, Timeline, Access records, Alibi analysis, Evidence against, Evidence for, Missing evidence, Network, Models used, Audit, Manifest. A plain explanation: "Each pack has a digital fingerprint (SHA-256). If anyone edits it, verification fails." Include a "Verify a pack" upload box.
```

### Control Lab
```
Same app and design system. Control Lab: "Which bank control would have stopped this?" A list of candidate controls (e.g. "Auto-expire overrides after 24h", "Block payees for 24h after a mobile change"). Each card shows: the step in the chain where it would have broken it (mini chain with a scissors icon), how early, money saved (₹), and the cost to normal work over 90 days (legitimate actions blocked). A simple comparison bar chart. Primary button: "Propose this control".
```

### Twin Scenario Lab
```
Same app and design system. Twin Scenario Lab: proves SUTRA doesn't cry wolf. A grid of scenario pairs. Each pair shows a "Suspicious" card and a "Legitimate twin" card side by side, with the one fact that differs highlighted between them (e.g. "Twin has a service ticket and a camp roster entry"). Result chips: "Flagged ✓" on the suspicious one and "Stayed quiet ✓" on the twin. Header scoreboard: "14/14 checks pass, 8/8 twins stay quiet."
```

### Governance: reveal identity and approvals
```
Same app and design system. Approvals page. Staff are shown as pseudonyms by default. A "Request to reveal identity" flow: a form with a reason field, a case link and an expiry, and a note that a second person must approve. An approvals inbox with request cards (who asked, why, which case, time left), with Approve / Decline buttons and a four-eyes icon. A side card explains: "Why names are hidden: privacy by default; two people are needed to reveal one." Below, an audit log preview with a "Tamper-proof chain ✓" chip.
```

### Glossary / Help center
```
Same app and design system. Help center with a search bar, a "How SUTRA works" illustrated 6-step walkthrough, and a Glossary of A–Z cards. Each card has the term, a one-line plain definition and a tiny example. Include: Alert, Case, Chain, Hop, Alibi, Priority (P1, P2, P3, Watch, Explained), Risk area, Evidence code, Evidence for / against, Missing evidence, Mule account, Dormant account, Override, Pseudonym, Unmask, Twin scenario, STR, Evidence pack.
```
