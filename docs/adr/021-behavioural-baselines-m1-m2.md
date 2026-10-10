# 021 — Keep M1 and M2; move M2's signal threshold from 0.5% to 2%

**Context.** M1 (access rhythm: a leave-one-out hour-of-week share, shrunk toward the role) and M2
(navigation: a role-conditioned Markov likelihood) are unsupervised baselines, refitted on each run's
window. Their signal thresholds (M1 share < 0.004 after 20:00; M2 bottom 0.5% of the role) were set on
the demo world. Neither had been measured against ground truth or a simpler rule.

**Protocol** (`app/lab/behaviour_eval.py`; run with `make eval-behaviour`):
- Unit: staff session.
- Positive: a session holding an S4/S5 suspicious variant's labelled staff actions.
- Look-alikes: the legitimate twins' sessions.
- Worlds 7–11 (seed 42 excluded, because the thresholds were set there): 20,033 sessions, 60 positives,
  30 look-alikes.
- Baselines: after-hours, first-ever after-hours session, and count of sensitive actions.
- One alternative for M2: leave-one-session-out fitting.

**Findings** (ml/reports/m1_m2_eval.json, pooled):

| Method | PR-AUC (chance 0.003) | At its threshold: flagged · precision · recall | Look-alikes flagged |
|---|---|---|---|
| M1 | 0.72 | 46 · 0.76 · 0.58 | 0 |
| M2 (0.5%) | 0.32 | 38 · 0.00 · 0.00 | 0 |
| After hours | 0.09 | 221 · 0.16 · 0.58 | 0 |
| First late session | 0.41 | 50 · 0.70 · 0.58 | 0 |
| Sensitive actions ≥ 2 | 0.01 | 4,774 · 0.01 · 0.68 | **30 of 30** |
| M2 leave-one-out | 0.32 (Δ −0.001) | identical to M2 | 0 |

**Decision.**
- **Keep M1:** it beats both after-hours rules on precision and PR-AUC with no look-alike flagged.
- **Keep M2's algorithm:** the leave-one-out alternative changes nothing, because role-level counts swamp
  a session's own transitions.
- **Change M2's signal threshold.** M2 ranks well (PR-AUC 0.32, about 100× chance), but at 0.5% it caught
  none of the insider sessions. The threshold was chosen on worlds 7–9 by F1 and reported once on worlds
  10–11:

  | Threshold | Insider sessions caught (worlds 10–11) | Precision | Look-alikes flagged |
  |---|---|---|---|
  | 0.5% | 0 of 24 | — | 0 |
  | **2%** | **24 of 24** | 0.24 | 0 |

- **System check before adopting.** M2 signals are M7 features, so M7 was retrained with the 2% signal
  in an isolated directory. FIN-04 precision, recall and look-alike rates were identical on all three
  test sets. The 41 scenario, M7, lattice and Alibi tests pass. The brief's employee dimension already
  used 2% for ELEVATED; only the signal used 0.5%.
- Adopted as `SUTRA_M2_SIGNAL_PERCENTILE=0.02`; detector version M2 1.1. Models retrained through the
  registry (ADR 022).

**Consequences.** M2 raises roughly four times as many navigation signals per run, at about 24% precision.
They are behavioural attributes that never open a case on their own. 60 positive sessions is a small
sample: these are synthetic results under Kestrel-Sim's assumptions, not real-bank accuracy.
