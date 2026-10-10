# 016 — A live feed for the end-to-end demo

**Context.** Judges and bank reviewers want to watch the product work from raw input to
finished output, not a tour of screens over pre-computed results. The Command Center replay
([ADR 006](006-background-work.md)) only re-streams signals that were already detected. A live
demo also has to be repeatable on a laptop, with no network, many times a day.

**Decision.**

- **The simulator holds an evening back.** In the demo world, Kestrel-Sim generates the evening
  of 22 Sep after everything else, from its own random stream, so the rest of the world is
  unchanged. It contains a second insider takeover (another employee, another branch, the same
  mule ring as 21 Sep), a legitimate pension camp that performs the same mobile-number changes, and
  routine traffic: 247 rows from 11 source systems. Rows the bank already knew (the override grant,
  the victim's 2009 account, the camp roster) load as history. The rest go to `feed_event`,
  tokenised at the same ingest boundary as all other data. No raw phone number reaches the
  database, not even in held-back rows.
- **Ingest behaves like change-data capture.** Each held-back row is inserted as-is, one
  transaction per row, with the master-data change it implies: a transfer moves both balances, and
  a mobile-number or limit change updates the account. Tables and columns are whitelisted.
- **Detection is the production pipeline, unchanged.** After ingest, Live Ops runs the same
  `compute → persist → record_run` as the 15-minute CronJob over the full 90-day window. The UI shows
  each stage's real duration, published over Server-Sent Events with event ids, so a reconnecting
  browser resumes where it left off.
- **Re-runs keep identity and human work.** A chain is identified by `(kind, root_ref)` and keeps
  its `CH-` and `AL-` IDs for as long as detection finds it. New chains continue the sequences, so
  an empty database gets the original numbering. `persist` runs in **one transaction**: readers see
  the previous run until commit. Cases, notes and evidence packs are carried over, as are alert
  states a person set (anything other than OPEN/WATCH/SUPPRESSED). A chain that detection no longer
  finds is kept as it was if a case hangs off it. Before this, every scheduled run deleted all cases.
- **Reset is exact.** It undoes ingested rows newest-first (balances and master data restored),
  removes only the alerts the feed created, and re-detects. Feed-created alerts are recorded in the
  hash-chained audit log as `live.run`; `live.reset` marks the reset.
- **Ground truth stays out of the run.** Each row's label (attack, camp or routine) is returned only
  after the whole feed is in. The UI then shows how many rows of each kind a queued alert cites.
- **Demo mode only.** Every `/live` route returns 404 unless `SUTRA_DEMO_MODE=true`, which staging
  and prod refuse at startup. One run at a time (409 otherwise).

**What the feed exposed.** Two detection defects surfaced and were fixed rather than tuned away:

- G1 counted a "cycle" in which more money came back than went out (221%). Retention must now fall
  between 70% and 110% (G1 v1.1).
- Needle followed money for 72 h after a payout, so the 21 Sep chain absorbed the 22 Sep transfers.
  Layering hops now count within 12 h of the funds arriving. Base-world chains and every training
  feature are unchanged by this.

**Consequences.** A judge watches 247 raw rows arrive and the P1 assemble itself in about 25
seconds of detection on a laptop, with nothing pre-computed. The 21 Sep case keeps its ID and
links, and the mule-factory alert gains one cited link. Reset takes about as long as a detection
run. Run progress lives in API memory: an API restart loses the progress log but not the data, and
the page says the feed is already in.

**Addendum — your input.** A second scope, `yours`, lets a person compose input at the console. `app.loom.compose`
turns their choices (staff member, time and channel, paperwork, account, changes, payees and amount) into the rows
each system would record, built on the bank's current state: IDs continue every sequence, the account's current
mobile token and limit become the reversible effect, and the mule ring reacts as it did on 21 Sep. The rows are
staged as feed rows and go through the same ingest and detection. The run reports the signals the rows raised and a
one-sentence verdict. The same input always produces the same rows. Undoing "yours" leaves tonight's feed untouched.

**Addendum — Kestrel Bank.** A third scope, `bank`, comes from a working mock bank (`/bank`): a staff core-banking
console and customer NetBanking with sessions of their own (an `X-Bank-Token`, never SUTRA's session). Each action is
recorded the moment it happens, as a CDC feed would deliver it, so SUTRA's input is whatever a person actually did.
The bank runs on its own clock inside 22 Sep, and every action moves it on by the time that action takes, so actions
never share a timestamp and a run of clicks reads like a real evening. It resumes from its latest record after a
restart. The bank enforces only what a bank would (permissions, including a temporary override nobody revoked;
balances; per-transaction limits; payees). Detection runs on demand from Live Ops, standing in for the 15-minute job.
