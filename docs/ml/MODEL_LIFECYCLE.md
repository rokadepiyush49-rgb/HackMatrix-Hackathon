# Model lifecycle

Every model, what it is for, how it is trained, how it reaches a prediction, and when it may change.
Decisions: [ADR 007](../adr/007-models-and-leakage.md), [017](../adr/017-learned-prioritisation.md),
[021](../adr/021-behavioural-baselines-m1-m2.md), [022](../adr/022-model-lifecycle.md). All metrics come
from synthetic Kestrel-Sim worlds and say nothing about accuracy on real bank data.

> **Naming.** The brief speaks of M1–M6. In this repository the learned models are M1, M2, M5, M6 and M7.
> "M3"/"M4" do not exist: rule (R1–R10) and graph (G1–G5) detectors fill those roles, and ER (entity
> resolution) is a fuzzy matcher, not a trained model.

## Inventory

| Model | Purpose | Kind | Trained on | Served how | Output used by |
|---|---|---|---|---|---|
| **M1** access rhythm | Is this staff session at an unusual hour for this person? | Unsupervised: hour-of-week share, leave-one-out, shrunk toward the role (k = 20) | The run's own 90-day window; refitted every run | In-process, per detection run | M1 signal; employee dimension; M7 features |
| **M2** navigation | Is this session's sequence of actions unusual for the role? | Unsupervised: role-conditioned first-order Markov likelihood | The run's own window; refitted every run | In-process | M2 signal (bottom 2% of role, ADR 021); employee dimension; M7 features |
| **M5** chain classifier | How much does this chain look like the suspicious ones? | Standardised logistic regression + Platt calibration; exact per-feature contributions | Worlds 7–10, 442 chains (71 positive), grouped CV | Approved artifact `chain_classifier.joblib` | Priority lattice (moves a chain between watch-list and queue only) |
| **M6** mule-likeness | Does this account behave like a mule? | LightGBM, 200 trees, 15 leaves; TreeSHAP | Worlds 7–10, 18,982 accounts (326 positive), grouped CV | `mule_model.joblib` | M6 evidence; network dimension |
| **M7** case prioritiser | Which connected case to look at first | LightGBM over 32 graph, sequence and detector features; Platt calibration | Worlds 7–10, 1,772 cases (113 positive, 545 look-alikes) | `case_prioritiser.joblib` | Queue order inside a priority band; never sets a priority |

Approved artifacts as of 11 Oct 2026 (`ml/artifacts/registry.json`, grouped out-of-fold, synthetic):

| Model | PR-AUC | ROC-AUC | Brier | Positives / negatives |
|---|---|---|---|---|
| M5 | 0.955 | 0.97 | 0.0116 | 71 / 371 |
| M6 | 0.979 | 0.999 | — | 326 / 18,656 |
| M7 | 1.00 | 1.00 | 0.0007 | 113 / 1,659 |

M7 against the rule baselines on unseen data (`ml/reports/fin04_eval.json`):

| Test set | Method | Precision | Recall | Look-alike alerts |
|---|---|---|---|---|
| Held-out worlds 11 and 42 | M7 | 1.00 | 0.97 | 0% |
| | RB-1 (rules) | 0.42 | 0.91 | 16% |
| Later events | M7 | 0.84 | 1.00 | 9% |
| | RB-1 (rules) | 0.66 | 1.00 | 19% |

## M5 and M6 (and M7): when they train

**They do not train when data is ingested.** Ingesting the live feed, the mock bank or an AA statement,
and running detection, only *load* the approved artifacts. A test enforces this structurally: importing
the ingest/detect path never imports `app.ml.train`.

We chose **global training on labelled, independent worlds, with versioned reuse** (strategy B):
- **Not A (retrain each batch):** a live batch carries no labels. Fitting each evening's quirks would
  make the same case score differently between re-runs.
- **Not C (incremental):** LightGBM and logistic regression here are batch learners. Without fresh labels,
  drift can only *propose* an evaluation, never a deployment.

The data roles stay separate:
- worlds 7–10: training and threshold selection;
- worlds 11 and 42: held-out evaluation only;
- the 22 Sep feed: later-events evaluation;
- live ingestion: inference only.

## Train → validate → promote → roll back (`app/ml/registry.py`)

```
make train
  ├─ build worlds 7–10 (and 11, 42, 42+feed for evaluation)
  ├─ fit M5, M6, M7 → save_candidate()           atomic write to ml/artifacts/candidates/
  ├─ validate_candidate()                          schema · positives · floors · no regression ≤ 0.03 PR-AUC
  │                                                · smoke prediction · no held-out world in training
  ├─ promote()  if every check passes             archive approved → atomic rename → registry.json
  └─ reject()   otherwise                         approved model keeps serving; failure recorded
rollback(name)                                     restore the last archive after checking its SHA-256
load(name)                                         refuses missing / altered / unreadable / incompatible files
```

**What the registry records for each model:**
- version, SHA-256 and training timestamp;
- training worlds and row counts;
- feature list and feature-schema hash;
- metrics and hyperparameters;
- library versions (Python, NumPy, scikit-learn, LightGBM);
- the validation checks, the previous versions (archive) and any rejected candidates.

**Gates:**

| Model | Floors | Ceilings | Minimum positives |
|---|---|---|---|
| M5 | ROC-AUC ≥ 0.85, PR-AUC ≥ 0.70 | Brier ≤ 0.08 | 15 |
| M6 | PR-AUC ≥ 0.80, precision@k ≥ 0.75 | — | 30 |
| M7 | PR-AUC ≥ 0.80 | Brier ≤ 0.10 | 30 |

**When to retrain:** after a change to features, detectors (as with M2's threshold, ADR 021) or the
simulator; or after a library upgrade that the loader refuses. Never automatically.

**Drift:** not implemented. Meaningful drift checks need per-feature training distributions stored in the
registry; that is the next step (see IMPLEMENTATION_STATUS).

## M1 and M2: retained, M2's signal threshold recalibrated

On worlds 7–11 (20,033 staff sessions, 60 insider sessions, 30 legitimate look-alikes):
- **M1** reaches PR-AUC 0.72 (chance 0.003) and precision 0.76 at its threshold. It beats the
  after-hours and first-late-session rules. Kept.
- **M2** ranks well (PR-AUC 0.32), but its original 0.5% signal caught none of the insider sessions.
  - A 2% threshold, chosen on worlds 7–9, caught 24 of 24 on worlds 10–11 at precision 0.24 with no
    look-alike flagged.
  - M7 retrained with the new signal gives identical FIN-04 results.
  - A leave-one-session-out variant of M2 gave no improvement (ΔPR-AUC −0.001), so the algorithm is
    unchanged.
- Full numbers: `ml/reports/m1_m2_eval.json`; reproduce with `make eval-behaviour`.

## Commands

| Command | What it does |
|---|---|
| `make train` | Train, validate and promote M5/M6/M7; write model cards and the FIN-04 evaluation |
| `make eval-behaviour` | M1/M2 against baselines and the M2 threshold study |
| `python -c "from app.ml import registry; print(registry.status())"` | What serves now |
| `python -c "from app.ml import registry; registry.rollback('mule_model')"` | Roll back one model |
| `curl :8000/health/ready` | Readiness, including model status |
