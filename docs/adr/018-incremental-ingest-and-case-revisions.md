# 018 — Incremental ingest that converges whatever the arrival order, and append-only case revisions

**Context.** FIN-04 Addition 1 asks for events ingested incrementally with stable IDs, event and arrival
timestamps; duplicates and late events handled; connected investigations updated when new evidence links
them, with the earlier state kept and the change explained; and replays of the same history in other
arrival orders that do not inflate totals, evidence counts or case risk. The live feed of ADR 016 delivered
rows in event-time order only. A duplicate delivery aborted on a primary-key error. A late mobile-number
change could overwrite a newer one. Reset restored values in arrival order. `load_frames` read tables
without `ORDER BY`, so detection saw rows in physical order — which follows arrival and update history.
Nothing recorded how a case had looked before a re-run.

**Options.** (a) Make detection itself incremental — rejected: every detector, Needle and M7 would need
incremental versions and proofs that they equal the batch result. (b) Keep detection as a full recompute
over the 90-day window (ADR 006) and make *ingest* order-independent, so the window is the same set of
rows whatever the order — chosen. (c) Event sourcing with a replayable log as the source of truth —
right for production, too large for the final round.

**Decision.**
- `feed.deliver` classifies every arrival: **NEW** (inserted once), **DUPLICATE** (same ID and content
  hash — nothing changes), **CONFLICT** (same ID, different content — refused, nothing changes). Every
  arrival is a row in `feed_receipt` with event time, arrival time, outcome and a late flag measured
  against the stream watermark.
- Balance moves are additive, so they commute. A master-data change is applied only if no change to the
  same field with a later event time (then ID) is already in place: last writer wins *by event time*.
  Reset undoes in reverse event-time order, so each field returns to its value before the earliest change.
- Frames load in primary-key order.
- After each detection run, `brief.revisions.record` writes an append-only `case_revision` per alert whose
  case state changed: priority and lattice rule, dimension levels, links, cited evidence (with content
  hashes), money at risk, connected case and M7 score, plus a list of changes with reasons. Each reason
  names the delivered rows behind it and how late they arrived. A database trigger refuses UPDATE and
  DELETE. Identity is the alert's natural key (chain kind + root event); display IDs depend on arrival
  order and are excluded from the snapshot hash.
- `make replay` runs five arrival plans through production ingest and detection: in order, late-link
  (the IMPS connector lags 35 minutes), duplicates (≈30% re-sent, every transfer twice, one tampered
  re-send), shuffled and reverse. It checks that each converges to in-order's state. Plans schedule by
  source system, never by ground truth.

**Consequences.** Validation (ml/reports/replay/replay_report.json, 10 Oct 2026): all four plans converged
to the identical state: 85 cases compared by snapshot hash, plus totals for rows, rupees, balances,
master data, signals, evidence and M7 scores. Duplicates: 168 deliveries absorbed, 1 tampered re-send
refused. Late-link: before the IMPS rows arrive, no alert for the second insider; when the 18 late rows
land, `AL-0922-003` opens at P1 and the 21 Sep mule-factory alert gains the late transfers as evidence,
each marked "arrived late". Cost: detection is a full recompute (~80 s per checkpoint on a laptop with
Postgres in Docker). Intermediate revisions legitimately differ between arrival orders; only the
converged state is invariant. Tests: `backend/tests/test_incremental.py`.
