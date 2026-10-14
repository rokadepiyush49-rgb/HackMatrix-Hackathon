# SUTRA — project audit (final round, start commit `ed12861`)

Audited 10–11 Oct 2026 by reading the code, running the system on a fresh database, and testing it.
Statuses describe what was verified at that point, not what documentation claimed. Changes made after the
audit are in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Architecture as found

A FastAPI modular monolith (`backend/app`) over PostgreSQL, a Next.js 16 investigator app (`frontend/`)
behind a server-side BFF that keeps JWTs in httpOnly cookies, and a seeded agent-based simulator
(`data/kestrel_sim`, "Kestrel-Sim"). Production scaffolding: Docker images, Helm, Argo CD, Terraform for
AWS, CI with signing and SBOMs.

**Verified execution path:**
1. `cli seed` generates world 42 and loads it, holding the evening of 22 Sep back in `feed_event`.
2. `cli train` builds worlds 7–11 and 42 and fits M5/M6/M7.
3. `cli detect` → `pipeline.compute`:
   - Alibi on every staff access;
   - entity resolution;
   - M1/M2 baselines refitted on the window;
   - signals R1–R10, G1–G5, M1, M2;
   - Needle chain assembly;
   - M6 scoring, Briefs with M5 and the priority lattice;
   - connected cases and M7.
4. `persist` writes everything in one transaction, keeping identities and human work.
5. `record_run` grades the scenarios against ground truth.
6. The API serves alerts, cases, Council, Ask SUTRA, Mend, packs and Live Ops.

## Inventory

| Area | Status at audit | Evidence |
|---|---|---|
| Detection pipeline (Alibi, rules, graph, Needle, Brief) | **Complete and verified** | 14/14 scenario checks on a fresh DB; 8/8 twins quiet |
| M5 / M6 / M7 training and FIN-04 evaluation | **Complete and verified** | Retrained from scratch: metrics identical to the committed report |
| Investigation Council | **Implemented, not AI** | `council/engine.py` is a scripted debate per typology; no model call; demo-world facts hard-coded (`LAP-221`, `02:14`) |
| Ask SUTRA (copilot) | Implemented, verified with a fake client | Anthropic Claude behind a cite-or-drop verifier; deterministic without a key |
| Live feed (FIN-04 Addition 1) | **Partially implemented** | Rows ingested once, in event-time order; no duplicate, conflict or late handling; no case history; order-dependent state |
| Kestrel-Sim | Complete | Seeded, deterministic; scenario twins; held-back evening |
| Evidence store, packs, audit chain | Implemented and tested | Hash-chained audit, SHA-256 pack manifests |
| AuthN/Z | Implemented and tested | 8 roles → capabilities; four-eyes enforced by the API |
| Sign-out | **Partially implemented** | Hidden in a menu; kept cached data in memory; not audited |
| Account Aggregator | **Not implemented** | — |
| Model lifecycle (validation, promotion, rollback) | **Not implemented** | Training overwrote served artifacts in place |
| Drift monitoring | Not implemented | — |
| Test suite | **Broken in this environment** | 13 failed + 4 errors (below) |
| Deployment (Docker/Helm/Terraform) | Implemented, not exercised here | No cloud credentials in scope |

**Baseline tests** (`uv run pytest`, before any change): **13 failed, 4 errors**, all environmental.
- The local `sutra` database was one Alembic migration behind (no `feed_event` table).
- `ml/artifacts` was empty (models never trained on this machine).

On an isolated `sutra_audit` database, migrated, seeded, trained and detected, the original suite passed.

## Findings

Severity: **High** = wrong results or a broken FIN-04 requirement; **Medium** = a material gap or a risk
to trust; **Low** = clarity or hygiene.

| # | Sev. | Finding | Location | Impact | Status |
|---|---|---|---|---|---|
| 1 | High | Duplicate delivery hit a primary-key error and aborted ingest | `loom/feed.py` `ingest` | FIN-04 "duplicate delivery must not inflate…" unmet; a CDC retry would break the run | **Fixed** (ADR 018) |
| 2 | High | A late master-data change could overwrite a newer one; reset restored in arrival order | `loom/feed.py` | Final account state depended on arrival order | **Fixed** |
| 3 | High | `load_frames` used `SELECT *` without `ORDER BY` | `loom/frames.py` | Detection input order followed physical storage (insert/update history) | **Fixed** |
| 4 | High | No case history: re-runs replaced the reasoning layer with no record of the earlier state | `pipeline.persist` | FIN-04 "preserve earlier case state and explain why it changed" unmet | **Fixed**: `case_revision`, append-only by trigger |
| 5 | Medium | The Investigation Council was scripted, not agents, with demo-world facts in production code | `council/engine.py:269, :298` | Overstates "agents"; wrong text on other cases | **Fixed**: Groq agents + harness (ADR 019); literals derived from evidence |
| 6 | Medium | Training overwrote served models in place (non-atomic), with no validation, provenance or rollback; a corrupt file would crash detection and the API | `ml/train.py:233`, `ml/models.py:36` | Silent model regressions; outage on a bad file | **Fixed**: registry (ADR 022) |
| 7 | Medium | M2's signal threshold (0.5%) caught 0 of 24 insider sessions on unseen worlds | `pipeline.py:102` | Behavioural signal contributed no recall | **Fixed**: 2% (ADR 021), validated end to end |
| 8 | Medium | Revision diff left some changes unexplained (computed evidence re-scored, case resized) | `brief/revisions.py` (new) | Found in our own replay output | **Fixed** before the final run; test added |
| 9 | Medium | Sign-out used client-side navigation (cached data of the previous persona stayed in memory); "Switch persona" did not end the session; neither was audited | `components/shell/topbar.tsx` | Shared demo laptops | **Fixed**: full navigation, `auth.logout` audit, visible button |
| 10 | Medium | JWTs are stateless: sign-out deletes cookies but a stolen refresh token stays valid until expiry (12 h) | `core/security.py` | Session revocation | **Fixed**: sign-out revokes the session (`revoked_session`, migration `e6b3a9c1d702`) |
| 11 | Low | `api.Dockerfile` ran `train --seed 7`, but training ignores `--seed` | `docker/api.Dockerfile:39` | Misleading provenance | **Fixed** |
| 12 | Low | The brief's premise "M5/M6 retrain on every Kestrel-Sim ingestion" is false: they load saved artifacts | `pipeline.py`, `cli.py:44` | Clarifies scope | Documented (ADR 022) |
| 13 | Low | Live Ops routes require any signed-in user, not a capability | `api/live.py` | Demo mode only (refused in staging/prod) | **Fixed**: changes need `cases:investigate` |
| 14 | Low | Rate limiting uses `memory://` per process | `core/limiter.py` | Ineffective with several replicas | Open (documented in config) |
| 15 | Low | The project's own `ml/reports` regenerate with timestamps on every train | `lab/heldout.py` | Noisy diffs | Open |

**Checked and found sound:**
- SQL built with f-strings only interpolates whitelisted table and column names (`feed.TABLES`,
  `EFFECT_COLUMNS`, `SCOPES`).
- `.env` is git-ignored and untracked.
- Production refuses default secrets and demo mode.
- PII is tokenised at ingest.
- The browser never holds a JWT.

## Models

| Model | Kind | Assessment |
|---|---|---|
| M1 access rhythm | Unsupervised, refitted per run | Sound. PR-AUC 0.72 vs 0.003 chance on worlds 7–11; beats after-hours rules; 0 look-alikes. Keep |
| M2 navigation | Unsupervised, refitted per run | Ranking sound (PR-AUC 0.32), threshold wrong (finding 7). Leave-one-out variant: no gain. Keep the algorithm; recalibrated |
| M5 chain classifier | Logistic regression + Platt; exact contributions | Sound, grouped CV, PR-AUC 0.955. Only moves a chain between watch-list and queue |
| M6 mule-likeness | LightGBM + TreeSHAP | Sound, PR-AUC 0.979; no single feature > 80% |
| M7 case prioritiser | LightGBM + Platt | Strong on held-out worlds (P 1.00 / R 0.97) but weaker on later events (P 0.84 vs RB-1 0.66). The report says where rules still win. Orders the queue only |
| ER | Fuzzy matcher, not trained | n/a |

"M3" and "M4" in the brief do not exist in this code base.

## Remediation plan (as executed)

1. Make ingest order-invariant and auditable; add append-only case revisions; prove convergence by replay
   (Highs 1–4).
2. Council agents on Groq inside a harness that enforces grounding, budgets and fallbacks (Medium 5).
3. Model registry with validation, atomic promotion, rollback and a guarded load (Medium 6).
4. Measure M1/M2; recalibrate M2 only on held-out evidence and a system-level check (Medium 7).
5. Account Aggregator as consented evidence, with a labelled synthetic FIP (new capability).
6. Sign-out (Medium 9); Dockerfile provenance (Low 11).
7. Still open: shared rate-limit store (14),
   drift monitoring, checkpoint/resume for council runs.
