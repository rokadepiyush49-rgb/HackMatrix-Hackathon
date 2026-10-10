# 007 — Glass-box chain classifier; independent training world

**Context.** Chains are few and every prediction must be explained exactly.
Training and evaluating on the same synthetic world would leak scenario structure.

**Decision.**
- **M5 chain classifier:** standardised logistic regression with Platt calibration (fitted out-of-fold).
  Contributions are exact (`coef × standardised value`), so the brief shows real
  attributions, not approximations.
- **M6 mule-likeness:** LightGBM; per-prediction contributions come from LightGBM's
  native TreeSHAP (`pred_contrib=True`) — no extra SHAP dependency.
- **Training data:** a separate Kestrel-Sim world (seed 7, randomised scenario parameters).
  Evaluation and the demo use seed 42. Metrics are always labelled *synthetic*.

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
- **Provenance:** every model records its training seed, library versions and artifact SHA-256;
  evidence packs embed them.

**Consequences.** Honest metrics, exact explanations, and no claim about accuracy on real
bank data. M5 still separates the synthetic chains perfectly — a property of synthetic data,
which is why it may only move a chain between watch-list and queue, never raise one.
