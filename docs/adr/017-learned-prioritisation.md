# 017 — Connected cases, a learned prioritiser (M7) and a documented rule baseline

**Context.** FIN-04 asks for a risk or priority model learned from network features and event
sequences, tied to case priority, and compared with a documented rule detector on held-out connected
cases and later events, with precision and recall and with look-alikes included. Before this record,
SUTRA's learned models scored single chains (M5) and single accounts (M6). Graph patterns lived only in
rules (G1–G5), cases were never grouped, cross-validation used `StratifiedKFold` (so one ring could
straddle folds), M5 rested on 17 positive chains from one world, and no rule baseline or precision and
recall existed.

**Decision.**

- **The unit is a connected case** ([`app/ml/cases.py`](../../backend/app/ml/cases.py)): a component
  of Needle chains and seeding signals, joined by shared accounts, customers, devices or counterparties.
  Staff never join cases, because one officer touches hundreds of customers. A shared employee becomes a
  link between cases instead. Case keys come from the content of the earliest node, so the same events
  give the same keys whatever order they arrived in.
- **M7 is LightGBM over 32 engineered features** in three families: graph, sequence and detector
  evidence ([features](../ml/features.md)). Each feature carries the record IDs that produced it.
  Calibration is Platt scaling on grouped out-of-fold scores. Isotonic regression was considered, but
  with about 110 positives it produces large flat steps that read like verdicts. TreeSHAP gives exact
  contributions. A GNN was not used: there are too few positives, it is harder to explain, and no lift
  would be expected on this data.
- **Train on four worlds, group every split.** Seeds 7–10 provide 113 positive cases and 545
  look-alikes. `StratifiedGroupKFold` groups every case, chain and account that ground truth ties
  together ([labeling](../ml/labeling.md)). M5 and M6 are retrained the same way.
- **Two documented baselines.** RB-1 is a frozen six-clause rule set. RB-2 is SUTRA's own lattice with
  every model input off ([rule baseline](../ml/rule_baseline.md)).
- **Three test sets**, with bootstrap intervals over groups: grouped out-of-fold, held-out worlds 11
  and 42, and later events (models refitted on cases that ended before 2 Sep, scored on cases with
  events after it, including the 22 Sep live feed).
- **M7 orders, it does not decide.** The lattice still sets the band from argued evidence. M7 orders
  alerts within it and is shown as a suspicion score between 0.01 and 0.99. It never sets P1, never
  demotes and never closes a case. A missing artifact means rules-only ordering.
- **`compute(models=False)`** runs the pipeline with no learned input. That is RB-2, and it keeps
  training and evaluation independent of whatever artifacts happen to be on disk.

**Consequences.**

- On held-out worlds M7 reaches 1.00 precision and 0.97 recall, against RB-1's 0.42 and 0.91. It alerts
  on no look-alike, where RB-1 alerts on 16%. On later events it falls to 0.84 precision with a 9%
  look-alike false-positive rate. Every one of those false positives is a monthly loan loop the past-only
  model never saw: loops recur, so none had ended by the cutoff. Rules still catch every circular flow
  and keep the better PR-AUC on later events. The report shows all of this, and asserts no winner.
- The scores are synthetic and high because synthetic schemes separate cleanly. This is why M7 only
  orders a band and never changes it.
- `make train` takes about 80 s instead of 20 s, and writes the FIN-04 deliverables to `ml/reports/`.
- M7 scores whole cases, not events. When an event arrives late (FIN-04 Addition 1), the affected case
  is recomputed and re-scored on the next detection run. Revision history for those changes is separate
  work.
