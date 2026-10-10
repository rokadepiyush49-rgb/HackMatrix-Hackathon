"""Model quality gate: CI fails if a retrained model gets worse, opaque or untraceable."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.features import MULE_FEATURES
from app.ml.models import _load, model_meta, score_chain


@pytest.fixture(scope="module")
def meta():
    m = model_meta()
    if set(m) != {"chain_classifier", "mule_model"}:
        pytest.skip("model artifacts not built — run `make train`")
    return m


def test_models_are_traceable(meta):
    for name, m in meta.items():
        assert len(m["artifact_sha256"]) == 64, name
        assert {"scikit-learn", "lightgbm", "numpy"} <= set(m["libraries"]), name
        assert m["train_seed"] != 42, "trained on the demo world — evaluation would be leaked"


def test_metric_floors(meta):
    m5, m6 = meta["chain_classifier"]["metrics"], meta["mule_model"]["metrics"]
    assert m5["roc_auc_oof"] >= 0.85 and m5["brier_oof"] <= 0.08
    assert m5["positives"] >= 15, "too few positive chains for stable out-of-fold metrics"
    assert m6["pr_auc_oof"] >= 0.80 and m6["precision_at_k"] >= 0.75


def test_m5_explanation_is_exact(meta, result):
    """Contributions shown to investigators must add up to the model's decision value."""
    lr = _load("chain_classifier")["lr"]
    scored = [b for b in result["briefs"] if b.classifier]
    assert scored
    for b in scored[:20]:
        s = score_chain(b.draft.features)
        total = sum(c["contribution"] for c in s.contributions) + float(lr.intercept_[0])
        assert total == pytest.approx(s.decision, abs=0.02)


def test_m6_treeshap_is_additive_and_not_a_single_rule(meta, frames):
    from app.ml.features import mule_frame

    model = _load("mule_model")["model"]
    X = mule_frame(frames)[MULE_FEATURES].to_numpy()
    contrib = model.booster_.predict(X, pred_contrib=True)
    raw = model.booster_.predict(X, raw_score=True)
    np.testing.assert_allclose(contrib.sum(axis=1), raw, rtol=1e-6, atol=1e-6)

    flagged = model.predict_proba(X)[:, 1] >= 0.5
    assert flagged.any()
    share = np.abs(contrib[flagged, :-1]).mean(axis=0)
    share = share / share.sum()
    top = MULE_FEATURES[int(share.argmax())]
    assert share.max() < 0.8, f"M6 leans on one feature ({top}: {share.max():.0%}) — a rule, not a model"
