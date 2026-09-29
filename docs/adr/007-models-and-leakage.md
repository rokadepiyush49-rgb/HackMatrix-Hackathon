# 007 — Glass-box chain classifier; independent training world

**Context.** Chains are few and every prediction must be explained exactly.
Training and evaluating on the same synthetic world would leak scenario structure.

**Decision.**
- **M5 chain classifier:** standardised logistic regression with isotonic calibration.
  Contributions are exact (`coef × standardised value`), so the brief shows real
  attributions, not approximations.
- **M6 mule-likeness:** LightGBM; per-prediction contributions come from LightGBM's
  native TreeSHAP (`pred_contrib=True`) — no extra SHAP dependency.
- **Training data:** a separate Kestrel-Sim world (seed 7, randomised scenario parameters).
  Evaluation and the demo use seed 42. Metrics are always labelled *synthetic*.

**Consequences.** Honest metrics, exact explanations, and no claim about accuracy on real
bank data.
