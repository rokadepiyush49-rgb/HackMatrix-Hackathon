"""Train M5 and M6 on an independent synthetic world (default seed 7) — see docs/adr/007.

    python -m app.cli train

Writes ml/artifacts/*.joblib and ml/model_cards/*.json. Metrics are *synthetic* and are
labelled as such everywhere they appear.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import joblib
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.preprocessing import StandardScaler

from app.alibi.engine import explain
from app.core.config import REPO_ROOT, get_settings
from app.loom.frames import frames_from_world
from app.ml.features import CHAIN_FEATURES, MULE_FEATURES, chain_row, mule_frame
from app.needle import chains as N


def _chain_dataset(world, f):
    ex = explain(f)
    ix = N.Index(f, ex)
    ins = N.insider_chains(ix)
    ext = N.external_chains(ix, {d.account_id for d in ins})
    drafts = ins + ext
    positive_accts = set()
    for lab in world.labels:
        if lab["variant"] == "suspicious" and lab["scenario"] in ("S4", "S6"):
            positive_accts |= set(lab["entities"])
    X = np.array([[chain_row(d.features)[k] for k in CHAIN_FEATURES] for d in drafts])
    y = np.array([int(d.account_id in positive_accts) for d in drafts])
    return X, y, drafts


def _mule_dataset(world, f):
    frame = mule_frame(f)
    mules = set()
    for lab in world.labels:
        if lab["scenario"] == "S7" and lab["variant"] == "suspicious":
            mules |= {e for e in lab["entities"] if e.startswith("A-")}
    y = frame.index.isin(mules).astype(int)
    return frame[MULE_FEATURES].to_numpy(), y, frame


def train_all(seed: int = 7, size: str = "demo") -> dict:
    from kestrel_sim import generate

    t0 = time.perf_counter()
    print(f"▸ Generating independent training world (seed={seed}) …")
    world = generate(seed=seed, size=size, mode="train")
    f = frames_from_world(world)
    print(f"  {len(f.txn):,} transactions, {len(world.labels)} labels ({time.perf_counter() - t0:.1f}s)")

    # ── M5 chain classifier ──────────────────────────────────────────────
    X, y, drafts = _chain_dataset(world, f)
    print(f"▸ M5: {len(y)} candidate chains ({y.sum()} suspicious, {len(y) - y.sum()} legitimate)")
    scaler = StandardScaler().fit(X)
    Z = scaler.transform(X)
    lr = LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000)
    cv = StratifiedKFold(n_splits=min(4, int(y.sum())), shuffle=True, random_state=0)
    oof_decision = cross_val_predict(lr, Z, y, cv=cv, method="decision_function")
    platt = LogisticRegression(C=10.0).fit(oof_decision.reshape(-1, 1), y)
    oof_p = platt.predict_proba(oof_decision.reshape(-1, 1))[:, 1]
    lr.fit(Z, y)
    m5_metrics = {
        "roc_auc_oof": round(float(roc_auc_score(y, oof_decision)), 3),
        "pr_auc_oof": round(float(average_precision_score(y, oof_decision)), 3),
        "brier_oof": round(float(brier_score_loss(y, oof_p)), 4),
        "positives": int(y.sum()), "negatives": int(len(y) - y.sum()),
        "note": "Out-of-fold metrics on an independent synthetic world (seed 7). Not real-bank accuracy.",
    }
    art_dir = get_settings().artifacts_path
    art_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"scaler": scaler, "lr": lr, "platt": platt, "features": CHAIN_FEATURES,
                 "metrics": m5_metrics, "version": "1.0", "train_seed": seed, "n_train": int(len(y)),
                 "trained_at": datetime.now(UTC).isoformat()}, art_dir / "chain_classifier.joblib")
    print(f"  ✓ M5 {m5_metrics}")

    # ── M6 mule-likeness ─────────────────────────────────────────────────
    Xm, ym, frame = _mule_dataset(world, f)
    print(f"▸ M6: {len(ym):,} accounts ({ym.sum()} mule)")
    model = LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=5,
                           class_weight="balanced", random_state=0, verbose=-1)
    cvm = StratifiedKFold(n_splits=4, shuffle=True, random_state=0)
    oof_m = cross_val_predict(model, Xm, ym, cv=cvm, method="predict_proba")[:, 1]
    model.fit(Xm, ym)
    top = np.argsort(-oof_m)[: int(ym.sum())]
    m6_metrics = {
        "roc_auc_oof": round(float(roc_auc_score(ym, oof_m)), 3),
        "pr_auc_oof": round(float(average_precision_score(ym, oof_m)), 3),
        "precision_at_k": round(float(ym[top].mean()), 3), "k": int(ym.sum()),
        "positives": int(ym.sum()), "negatives": int(len(ym) - ym.sum()),
        "note": "Out-of-fold metrics on an independent synthetic world (seed 7). Not real-bank accuracy.",
    }
    joblib.dump({"model": model, "features": MULE_FEATURES, "metrics": m6_metrics, "version": "1.0",
                 "train_seed": seed, "n_train": int(len(ym)),
                 "trained_at": datetime.now(UTC).isoformat()}, art_dir / "mule_model.joblib")
    print(f"  ✓ M6 {m6_metrics}")

    cards = REPO_ROOT / "ml" / "model_cards"
    cards.mkdir(parents=True, exist_ok=True)
    (cards / "m5_chain_classifier.json").write_text(json.dumps(
        {"model": "M5 chain classifier", "algorithm": "Standardised logistic regression + Platt calibration",
         "features": CHAIN_FEATURES, "coefficients": dict(zip(CHAIN_FEATURES, map(float, lr.coef_[0]), strict=True)),
         "metrics": m5_metrics, "train_seed": seed}, indent=2))
    (cards / "m6_mule_model.json").write_text(json.dumps(
        {"model": "M6 mule-likeness", "algorithm": "LightGBM (200 trees, 15 leaves) with TreeSHAP",
         "features": MULE_FEATURES, "metrics": m6_metrics, "train_seed": seed}, indent=2))
    print(f"✓ Training finished in {time.perf_counter() - t0:.1f}s")
    from app.ml.models import reload

    reload()
    return {"m5": m5_metrics, "m6": m6_metrics}
