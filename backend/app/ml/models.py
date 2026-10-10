"""Inference for M5 (chain classifier), M6 (mule-likeness) and M7 (connected-case prioritiser).

M5 is a standardised logistic regression: its decision value is a sum of per-feature terms
(coef × standardised value), so the contributions shown to investigators are exact.
Calibration (Platt) maps the decision value to a probability fitted out-of-fold.
M6 and M7 are LightGBM; per-prediction contributions come from its native TreeSHAP and add up
exactly to the raw score. M7 is calibrated by Platt scaling fitted on grouped out-of-fold scores, and
each of its contributions carries the records that produced the feature (docs/ml/features.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.ml.case_features import CASE_LABELS, FAMILY, CaseRow, matrix
from app.ml.features import CHAIN_FEATURES, CHAIN_LABELS, MULE_FEATURES, MULE_LABELS, chain_row

MODELS = ("chain_classifier", "mule_model", "case_prioritiser")


@dataclass
class ChainScore:
    p: float
    decision: float
    contributions: list[dict]


@lru_cache
def _load(name: str):
    """The approved artifact, checked by the registry (checksum, libraries, feature schema). None when it is
    missing or refused — detection then runs on rules alone (app.ml.registry)."""
    from app.ml.registry import load

    return load(name).artifact


def reload() -> None:
    _load.cache_clear()
    _sha256.cache_clear()


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


@dataclass
class CaseScore:
    p: float  # calibrated suspicion score — a reason to look first, never a finding
    raw: float  # log-odds; orders cases that share a calibrated value
    alert: bool  # at or above the operating threshold chosen out-of-fold
    contributions: list[dict]


def explain_cases(art: dict, rows: list[CaseRow]) -> list[CaseScore]:
    """Score rows with an M7 artifact (or one of its training variants)."""
    names = art["features"]
    X = matrix(rows, names)
    booster = art["model"].booster_
    raw = booster.predict(X, raw_score=True)
    contrib = booster.predict(X, pred_contrib=True)  # last column is the bias term
    # A model score is a reason to look first, never certainty: it is shown between 0.01 and 0.99.
    p = np.clip(art["calibrator"].predict_proba(raw.reshape(-1, 1))[:, 1], 0.01, 0.99)
    out = []
    for i, r in enumerate(rows):
        c = sorted(({"feature": k, "label": CASE_LABELS[k], "family": FAMILY[k],
                     "value": None if np.isnan(X[i, j]) else round(float(X[i, j]), 3),
                     "contribution": round(float(contrib[i, j]), 3), "refs": r.provenance.get(k, [])}
                    for j, k in enumerate(names)), key=lambda d: (-abs(d["contribution"]), d["feature"]))
        out.append(CaseScore(round(float(p[i]), 3), round(float(raw[i]), 4), bool(p[i] >= art["threshold"]), c))
    return out


def score_cases(rows: list[CaseRow]) -> dict[str, CaseScore]:
    """M7 scores by case key. Empty when the artifact is missing: priority then runs on rules alone."""
    art = _load("case_prioritiser")
    if art is None or not rows:
        return {}
    return {r.key: s for r, s in zip(rows, explain_cases(art, rows), strict=True)}


@lru_cache
def _sha256(name: str) -> str | None:
    path = get_settings().artifacts_path / f"{name}.joblib"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def model_meta() -> dict:
    """What produced every score: version, training seed, metrics, libraries and the artifact's hash.

    Evidence packs embed this, so a pack can be traced to the exact model bytes that scored it.
    """
    from app.ml.registry import read_registry

    reg = read_registry()
    out = {}
    for name in MODELS:
        art = _load(name)
        if art is not None:
            out[name] = {k: v for k, v in art.items() if k in ("version", "metrics", "trained_at", "train_seeds",
                                                              "n_train", "features", "libraries", "threshold", "cv")}
            out[name]["artifact_sha256"] = _sha256(name)
            e = reg.get(name) or {}
            out[name]["registry"] = {"status": e.get("status", "unregistered"), "promoted_at": e.get("promoted_at"),
                                     "feature_schema": e.get("feature_schema")}
    return out
