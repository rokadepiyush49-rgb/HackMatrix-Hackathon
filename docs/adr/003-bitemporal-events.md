# 003 — Bitemporal events

**Context.** Investigators and auditors must reproduce *what the system knew and what
was true* at a given moment ("what did account A-5520 look like at 21:46?").

**Decision.** Every event row stores `occurred_at` (valid time) and `ingested_at`
(system time). Things with a lifespan (entitlements, rosters, relationships) store
explicit validity intervals. As-of queries filter on both.

**Consequences.** Time-scrubber replay and staff-accountability reconstruction are
plain SQL. Late-arriving data never silently rewrites history.
