"""Inference for M5 (chain classifier) and M6 (mule-likeness), with exact explanations.

M5 is a standardised logistic regression: its decision value is a sum of per-feature terms
(coef × standardised value), so the contributions shown to investigators are exact.
Calibration (Platt) maps the decision value to a probability fitted out-of-fold.
M6 is LightGBM; per-prediction contributions come from its native TreeSHAP.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.ml.features import CHAIN_FEATURES, CHAIN_LABELS, MULE_FEATURES, MULE_LABELS, chain_row


@dataclass
class ChainScore:
    p: float
    decision: float
    contributions: list[dict]


@lru_cache
def _load(name: str):
    path = get_settings().artifacts_path / f"{name}.joblib"
    return joblib.load(path) if path.exists() else None


def reload() -> None:
    _load.cache_clear()


def score_chain(features: dict) -> ChainScore | None:
    art = _load("chain_classifier")
    if art is None:
        return None
    row = chain_row(features)
    x = np.array([[row[k] for k in CHAIN_FEATURES]])
    z = art["scaler"].transform(x)[0]
    coef = art["lr"].coef_[0]
    terms = coef * z
    decision = float(terms.sum() + art["lr"].intercept_[0])
    p = float(art["platt"].predict_proba(np.array([[decision]]))[0, 1])
    contribs = sorted(
        ({"feature": k, "label": CHAIN_LABELS[k], "value": round(row[k], 3),
          "contribution": round(float(t), 3)} for k, t in zip(CHAIN_FEATURES, terms, strict=True)),
        key=lambda d: -abs(d["contribution"]))
    return ChainScore(round(p, 3), round(decision, 3), contribs)


def score_mules(frame: pd.DataFrame) -> pd.DataFrame:
    art = _load("mule_model")
    if art is None or frame.empty:
        return pd.DataFrame(columns=["p", "contributions"])
    X = frame[MULE_FEATURES].to_numpy()
    booster = art["model"].booster_
    p = art["model"].predict_proba(X)[:, 1]
    contrib = booster.predict(X, pred_contrib=True)  # last column is the bias term
    rows = []
    for i, aid in enumerate(frame.index):
        c = sorted(({"feature": k, "label": MULE_LABELS[k], "value": round(float(X[i, j]), 3),
                     "contribution": round(float(contrib[i, j]), 3)} for j, k in enumerate(MULE_FEATURES)),
                   key=lambda d: -abs(d["contribution"]))
        rows.append((aid, round(float(p[i]), 3), c))
    return pd.DataFrame(rows, columns=["account_id", "p", "contributions"]).set_index("account_id")


def model_meta() -> dict:
    out = {}
    for name in ("chain_classifier", "mule_model"):
        art = _load(name)
        if art is not None:
            out[name] = {k: v for k, v in art.items() if k in ("version", "metrics", "trained_at",
                                                              "train_seed", "n_train", "features")}
    return out
