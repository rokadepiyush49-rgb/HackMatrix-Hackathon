# Implementation status — final round

Start commit `ed12861`. Work done 10–11 Oct 2026. Status labels: **DONE** (implemented and verified by
the tests or runs listed), **PARTIALLY DONE**, **PENDING**, **BLOCKED** (needs something outside this
repository). Audit of the starting point: [PROJECT_AUDIT.md](PROJECT_AUDIT.md). Submission checklist:
[FIN04_EVIDENCE_PACKAGE.md](../evidence/FIN04_EVIDENCE_PACKAGE.md).

## A. What existed before

A working detection platform:
- Kestrel-Sim and Loom (PostgreSQL, bitemporal);
- Alibi; R1–R10 rules and G1–G5 graph detectors; Needle chains; argued Briefs with a priority lattice;
- M1/M2 baselines; M5/M6/M7 with grouped CV and a FIN-04 evaluation against rule baselines;
- Ask SUTRA (Claude, cite-or-drop);
- a scripted (not AI) Investigation Council;
- an in-order live feed with reset; the mock bank;
- RBAC, four-eyes review, a hash-chained audit log, evidence packs;
- Docker/Helm/Terraform/CI.

In this environment the test suite failed (13 failed, 4 errors) because the local database was a
migration behind and no models had been trained.

## B. What was implemented

| Change | Files | Verification | Status |
|---|---|---|---|
| Order-independent ingest: NEW / DUPLICATE / CONFLICT receipts, event vs arrival time, late flag, last-writer-wins by event time, exact reset | `loom/feed.py`, migration `9b2f4e6a1c03` | `test_incremental.py`; `make replay` | DONE |
| Frames loaded in primary-key order (detection no longer sees storage order) | `loom/frames.py` | 14/14 scenario checks; replay invariance | DONE |
| Append-only case revisions with reasons (DB trigger blocks edits); history API and UI panel | `brief/revisions.py`, `pipeline.record_run`, `api/alerts.py`, `components/brief/case-history.tsx` | `test_incremental.py`; seen in the UI | DONE |
| Replay harness: 5 arrival plans, convergence check, receipt logs; Live Ops arrival-order picker | `loom/replay.py`, `cli replay`, `api/live.py` `/live/replay`, `live/page.tsx` | `ml/reports/replay/`; UI late-link run opened AL-0922-003 | DONE |
| Groq client: retries, classified errors, no key leakage | `council/llm.py`, config | `test_council_agents.py` (fake Groq) | DONE (mock-verified) |
| Agent harness: strict schemas, ID enums, cite-or-drop, status rules, attribution rule, allowlists, budgets, loop cache, repair, trace | `council/harness.py` | `test_council_agents.py` | DONE (mock-verified) |
| Council agents (5 LLM, 3 hybrid, 1 deterministic) with per-agent fallback; saved runs with staleness; engine bar and trace UI | `council/agentic.py`, `api/workbench.py`, migration `c4d7e2f9a815`, `components/council/engine.tsx` | tests + UI (deterministic path) | PARTIALLY DONE — no live Groq run (no key) |
| Context budgets: model-aware per-call budget, whole-item batching, oversize reporting, coverage and "partial review" | `council/harness.py`, `agentic.py` | batching/oversize/budget tests | DONE (mock-verified) |
| Demo-world literals removed from the deterministic council | `council/engine.py` | `test_deterministic_council_has_no_demo_world_literals` | DONE |
| Model registry: candidate → validate → promote; archive, rollback; guarded load; readiness | `ml/registry.py`, `ml/train.py`, `ml/models.py`, `main.py` | `test_lifecycle.py`; `make train` promoted 3/3 | DONE |
| M1/M2 evaluation vs baselines; M2 threshold 0.5% → 2% (held-out), M7 retrained, FIN-04 unchanged | `lab/behaviour_eval.py`, `pipeline.py`, config | `ml/reports/m1_m2_eval.json`; scenario + M7 tests at 2% | DONE |
| Account Aggregator: consent, synthetic FIP, Setu adapter, ReBIT normalisation, idempotent store, revoke/purge, Council evidence, UI panel | `integrations/aa/*`, `api/aa.py`, migration `d5e8f1a2b3c4`, `components/aa/aa-panel.tsx` | `test_account_aggregator.py`; UI run (44 rows) | PARTIALLY DONE — synthetic only; Setu BLOCKED |
| Sign-out: visible button, audited `auth.logout`, full navigation clears cached data; "Switch persona" signs out first | `api/auth.py`, `app/api/session/route.ts`, `shell/topbar.tsx` | `test_sign_out_is_recorded_in_the_audit_chain`; UI | DONE |
| Dockerfile training provenance corrected | `docker/api.Dockerfile` | review | DONE |
| Docs: audit, ADRs 018–023, Council architecture, model lifecycle, AA, evidence package, demo script, README | `docs/**` | — | DONE |

## C. What remains

| Item | Status | Why / what it needs |
|---|---|---|
| Live Groq run of the Council | BLOCKED | No `GROQ_API_KEY` in this environment. Set one and press **Convene AI agents**; check the harness trace. Expect minutes on the free tier (8K tokens/min). |
| Setu AA sandbox run | BLOCKED | Bridge credentials; confirm header names and the ReBIT purpose code |
| Live AA customer data | BLOCKED | Regulated, Sahamati-certified FIU |
| Council checkpoint/resume after an API restart | PENDING | Interrupted runs are marked FAILED and must be convened again |
| Refresh-token revocation on sign-out | DONE | Sign-out revokes the session's `sid`; access and refresh tokens are refused (`test_sign_out_ends_every_token_of_the_session`) |
| Drift monitoring for M5/M6/M7 | PENDING | Store per-feature training distributions in the registry; compare per run; propose (never auto-deploy) |
| Capability check on Live Ops routes | DONE | Changes need `cases:investigate` (`test_read_only_roles_cannot_change_live_data`) |
| Frontend tests for the new panels | PENDING | No frontend test runner in the repo; verified by hand in the browser |

## D. Next, in order

1. **Live Groq dry run** (½ day; needs a key). Convene on AL-0921-001 and AL-0918-001; read the trace;
   tune prompts only if the harness drops too much. Pre-run the council before the judging session.
2. **Setu sandbox** (1 day; needs Bridge credentials). Point `SUTRA_AA_PROVIDER=setu`, run the consent
   flow, fix any schema drift in `normalize.py`.
3. ~~**Refresh-token revocation**~~ — done: sign-out ends the session.
4. **Drift report** per detection run (1 day): PSI per M6/M7 feature against stored training quantiles;
   propose evaluation only.
5. **Council resume from checkpoints** (1–2 days): persist validated claims per round in `council_run`.

## E. Test results

All commands were run with `PYTHONPATH=backend:data/kestrel_sim` against the isolated `sutra_audit`
database (migrated, seeded with world 42, models trained).

| When | Command | Result |
|---|---|---|
| Baseline, start | `uv run pytest` (your `sutra` DB, as found) | 13 failed, 4 errors (environment: missing migration, no models) |
| After changes, new suites | `pytest test_incremental.py test_council_agents.py test_lifecycle.py test_account_aggregator.py` | 65 passed (23 + 20 + 8 + 14), plus the sign-out audit test |
| After changes, full suite | `uv run pytest` | **177 passed, 2 skipped, 0 failed** of 179 (133 s) |
| Scenario/M7 at M2 = 2% | `pytest test_scenarios.py test_m7.py test_lattice.py test_alibi.py` | 41 passed |
| Replay evaluator | `python -m app.cli replay` (1,235 s) | **Invariant**: late-link, duplicates, shuffled and reverse each identical to in-order on 85 cases and every total |
| Lint / types | `ruff check backend data` · `npm run lint` · `npm run typecheck` · `npm run build` | all clean · build succeeded |

## F. Demo readiness

- **Works offline on a laptop:** everything except live Groq.
  - Detection, Live Ops (including arrival-order replays), case history, the deterministic council and
    its trace, the AA synthetic flow, Ask SUTRA (deterministic), sign-out.
- **Needs:** PostgreSQL; Python 3.12 + uv; Node 20+.
  - On an existing database run `make migrate` first (three new migrations).
  - Run `make train` once (≈5–10 min) to get registry-approved models.
- **Optional secrets:** `GROQ_API_KEY` (Council agents), `ANTHROPIC_API_KEY` (Ask SUTRA prose).
  Server-side only.
- **Claims that need care:**
  - "AI agents": say "LLM agents on Groq when a key is configured; tested with a scripted model here".
  - "Real bank data": say "the real AA consent flow on a labelled synthetic FIP".
  - Every metric: "on synthetic data".
- **Your own `sutra` database was not modified.** It needs `make migrate` (and `make live-reset` if the
  feed was half-played) before the new features work there.

## G. Known risks

- The council's quality with a real model is unmeasured.
  - The harness bounds the damage (drops, downgrades, fallbacks), not the usefulness.
  - Rate limits can make a live council slow.
- Small positive classes (33 held-out suspicious cases; 60 insider sessions): wide uncertainty.
- Detection is a full recompute (≈80 s per run here). Fine for 15-minute batches; not streaming.
- JWTs are revocable per sign-in session: a stolen token still works until that session signs out or the token expires.
- The AA Setu adapter is written from documentation, not exercised.

## H. Decisions

- **Council:**
  - LLM agents only where language reasoning helps (positions, challenges, responses, synthesis, ruling
    text).
  - Deterministic for retrieval, bookkeeping, grading, the outcome, consensus and dissent.
  - All enforcement in code (ADR 019).
- **Context:** budget from the real window, whole-item batching, never truncate, report coverage, say
  "partial review" (ADR 020).
- **M5/M6/M7:** they were never retrained on ingestion. Keep global training on labelled independent
  worlds; add a validated promotion lifecycle; no automatic retraining (ADR 022).
- **M1/M2:** keep both algorithms; recalibrate M2's signal threshold on held-out evidence after a
  system-level check (ADR 021).
- **Account Aggregator:** a consented evidence source for source-of-funds checks, demoed on a labelled
  synthetic FIP; sandbox-ready; live data blocked by regulation (ADR 023).
- **FIN-04 Addition 1:** an order-independent ingest plus full recompute, with append-only revisions,
  rather than incremental detectors (ADR 018).
