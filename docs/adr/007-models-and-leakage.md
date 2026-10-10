# 007 — Glass-box chain classifier; independent training world

**Context.** Chains are few and every prediction must be explained exactly.
Training and evaluating on the same synthetic world would leak scenario structure.

**Decision.**
- **M5 chain classifier:** standardised logistic regression with Platt calibration (fitted out-of-fold).
  Contributions are exact (`coef × standardised value`), so the brief shows real
  attributions, not approximations.
- **M6 mule-likeness:** LightGBM; per-prediction contributions come from LightGBM's
  native TreeSHAP (`pred_contrib=True`) — no extra SHAP dependency.
- **Training data:** separate Kestrel-Sim worlds (seeds 7–10 since [ADR 017](017-learned-prioritisation.md);
  originally seed 7 alone), with randomised scenario parameters. Seed 11 and the demo world (seed 42)
  are held out. Metrics are always labelled *synthetic*.
- **Grouped cross-validation** (since ADR 017): every split is a `StratifiedGroupKFold` over groups of
  cases, chains and accounts that ground truth ties together, so one ring never straddles folds.

- **Legitimate look-alikes in the training world.** A model trained only on clean negatives
  learns shortcuts. In the first version every mule was self-approved and presence-less and
  no legitimate account was, so M6 scored a meaningless ROC-AUC of 1.0 with 100% of its TreeSHAP
  weight on `self_approved` — a rule dressed as a model. The training world now also contains
  Video-KYC openings (no branch visit), single-officer branch exceptions (self-approved),
  families sharing a phone or device, mules approved by a colluding second officer, and rings
  where only some accounts share a device. M6 now rests on behaviour (pass-through, presence).
- **Quality gate in CI** (`backend/tests/test_models.py`): metric floors, a minimum number of
  positives, exact additivity of M5 contributions and M6 TreeSHAP, and a shortcut guard — no
  single feature may carry more than 80% of M6's explanation.
- **Provenance:** every model records its training seeds, library versions and artifact SHA-256;
  evidence packs embed them.

**Consequences.** Honest metrics, exact explanations, and no claim about accuracy on real
bank data. On one world M5 separated the synthetic chains perfectly. Grouped across four worlds
it reaches an out-of-fold ROC-AUC of 0.97 (71 positive chains). Its scores are still synthetic,
which is why it may only move a chain between watch-list and queue, never raise one.
