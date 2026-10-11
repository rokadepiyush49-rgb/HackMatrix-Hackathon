# 022 — Train globally, serve an approved model, promote only validated candidates

**Context.** The brief assumed M5 and M6 retrain whenever Kestrel-Sim data is ingested. The code shows
they do not. Detection loads saved artifacts (`ml/models._load`), and only `make train`, or `cli demo`
when an artifact is missing, fits them, on worlds 7–10. The real gaps were elsewhere:
- training overwrote the served file in place, with non-atomic writes and no validation;
- there was no record of which data built which file, and no rollback;
- a corrupted file would crash detection and the API.

**Options for M5/M6/M7.**
- **(A) Retrain on every ingestion — rejected.** A live batch has no labels. Retraining would fit
  each evening's quirks, and alert scores would drift between re-runs of the same case.
- **(B) Train globally on labelled independent worlds and reuse a versioned model — chosen.** This is
  what the code already did; it now does it safely.
- **(C) Incremental or drift-triggered retraining — not adopted.** LightGBM and logistic regression here
  are batch learners, and new data carries no labels. Drift can propose an evaluation, never a deployment.

**Decision** (`app/ml/registry.py`):
- **Candidates:** training writes candidates atomically (temp file → fsync → rename).
- **Validation before promotion:** the candidate must pass
  - a feature-schema match with the inference code;
  - minimum positive examples;
  - metric floors and ceilings;
  - no regression beyond 0.03 PR-AUC against the approved model;
  - a smoke prediction;
  - a check that no held-out world (11, 42) was used for training.
- **Promotion:** archive the approved file first, then swap the candidate in by atomic rename. The
  registry records version, SHA-256, training worlds and row counts, feature-schema hash, metrics,
  libraries, hyperparameters and the validation record.
- **Rejection:** a failed candidate is kept for inspection and recorded; the approved model keeps serving.
- **Rollback:** restores the last archive, after checking its hash.
- **Guarded load:** refuses missing, altered (hash mismatch), unreadable or incompatible files
  (scikit-learn or LightGBM minor-version change, feature-schema change). Detection then runs on rules
  alone, as it always could. `/health/ready` reports the refusal.

**Consequences.** Validation: `backend/tests/test_lifecycle.py` (8 tests), including a structural check
that importing the ingest and detection path never imports the trainer. On 11 Oct 2026, `make train`
promoted all three models with every check passing. Files built before the registry load as
"unregistered" and still serve. Drift monitoring is **not implemented**. The comparison baseline would be
the registry's training statistics, but no per-feature training distribution is stored yet.
