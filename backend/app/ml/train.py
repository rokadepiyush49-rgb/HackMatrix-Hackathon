"""Train M5, M6 and M7 on independent synthetic worlds, then evaluate them on held-out ones.

    python -m app.cli train          (make train)

Training worlds are seeds 7–10 (docs/adr/007, docs/adr/017). Every cross-validation split is grouped:
cases, chains and accounts that ground truth ties together — a takeover and the mule ring it pays into,
two rings that share accounts — always fall in the same fold, so no ring is learned on one side of a
split and scored on the other.

Writes ml/artifacts/*.joblib, ml/model_cards/*.json and, unless `evaluate=False`, the FIN-04 evaluation
in ml/reports/ (app.lab.heldout). Metrics are *synthetic* and are labelled as such everywhere they appear.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import joblib
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler

from app.core.config import REPO_ROOT, get_settings
from app.ml.case_features import (
    CASE_FEATURES,
    CASE_LABELS,
    FAMILY,
    STRUCTURE_FEATURES,
    matrix,
)
from app.ml.features import CHAIN_FEATURES, MULE_FEATURES
from app.ml.worlds import (
    HELDOUT_SEEDS,
    LATER_CUTOFF,
    TRAIN_SEEDS,
    CaseRecord,
    WorldData,
    build_worlds,
)

NOTE = "Synthetic Kestrel-Sim worlds. Not real-bank accuracy."
GROUPING = ("StratifiedGroupKFold: a group is every case, chain and account that ground truth ties together "
            "(one ring, or rings that share accounts). No group appears in two folds.")


def _libraries() -> dict[str, str]:
    """Pin what built the model: a pickle loaded under different library versions can silently change scores."""
    import lightgbm
    import sklearn

    return {"python": sys.version.split()[0], "numpy": np.__version__, "scikit-learn": sklearn.__version__,
            "lightgbm": lightgbm.__version__}


def grouped_folds(y: np.ndarray, groups: list[str], n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Stratified, grouped, shuffled once with a fixed seed. Never fewer than 2 folds."""
    k = max(2, min(n_splits, int(y.sum()), len(set(groups))))
    cv = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=0)
    folds = list(cv.split(np.zeros(len(y)), y, groups))
    g = np.asarray(groups)
    for tr, te in folds:  # the property every metric in the report rests on
        assert not set(g[tr]) & set(g[te]), "a group straddles a fold boundary"
    return folds


def _lgbm(**kw) -> LGBMClassifier:
    base = {"n_estimators": 300, "learning_rate": 0.03, "num_leaves": 15, "min_child_samples": 10,
            "colsample_bytree": 0.8, "reg_lambda": 1.0, "random_state": 0, "deterministic": True,
            "force_col_wise": True, "n_jobs": 4, "verbose": -1}
    return LGBMClassifier(**{**base, **kw})


def _best_threshold(p: np.ndarray, y: np.ndarray) -> float:
    """The calibrated score that maximises F1 out-of-fold (ties → the higher, more conservative one)."""
    best, best_f1 = 0.5, -1.0
    for t in sorted(set(np.round(p, 4)), reverse=True):
        a = p >= t
        tp = int((a & (y == 1)).sum())
        if tp == 0:
            continue
        f1 = 2 * tp / (int(a.sum()) + int(y.sum()))
        if f1 > best_f1 + 1e-12:
            best, best_f1 = float(t), f1
    return round(min(best, 0.99), 4)  # scores are shown capped at 0.99 (app.ml.models.explain_cases)


def _binary(p: np.ndarray, y: np.ndarray, t: float) -> dict:
    a = p >= t
    tp, fp, fn = int((a & (y == 1)).sum()), int((a & (y == 0)).sum()), int((~a & (y == 1)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0}


# ── M7 connected-case prioritiser ─────────────────────────────────────────


def fit_case_model(records: list[CaseRecord], names: list[str], label: str) -> dict:
    """LightGBM over case features with grouped OOF scores, Platt calibration and an F1 operating point."""
    from app.ml.case_features import CaseRow

    rows = [CaseRow(r.key, r.values, r.provenance) for r in records]
    X = matrix(rows, names)
    y = np.array([r.y for r in records])
    groups = [r.group for r in records]
    folds = grouped_folds(y, groups, 5)
    oof = np.zeros(len(y))
    fold_of = np.zeros(len(y), dtype=int)
    for i, (tr, te) in enumerate(folds):
        oof[te] = _lgbm().fit(X[tr], y[tr]).booster_.predict(X[te], raw_score=True)
        fold_of[te] = i
    platt = LogisticRegression(C=1.0).fit(oof.reshape(-1, 1), y)
    oof_p = platt.predict_proba(oof.reshape(-1, 1))[:, 1]
    tau = _best_threshold(oof_p, y)
    model = _lgbm().fit(X, y)

    contrib = model.booster_.predict(X, pred_contrib=True)[:, :-1]
    imp = np.abs(contrib).mean(axis=0)
    share = imp / imp.sum() if imp.sum() else imp
    flagged = platt.predict_proba(model.booster_.predict(X, raw_score=True).reshape(-1, 1))[:, 1] >= tau
    fshare = np.abs(contrib[flagged]).mean(axis=0) if flagged.any() else imp
    fshare = fshare / fshare.sum() if fshare.sum() else fshare
    importance = sorted(({"feature": k, "label": CASE_LABELS[k], "family": FAMILY[k], "share": round(float(s), 4)}
                         for k, s in zip(names, share, strict=True)), key=lambda d: -d["share"])
    families = {}
    for d in importance:
        families[d["family"]] = round(families.get(d["family"], 0.0) + d["share"], 4)
    metrics = {
        "roc_auc_oof": round(float(roc_auc_score(y, oof)), 3),
        "pr_auc_oof": round(float(average_precision_score(y, oof)), 3),
        "brier_oof": round(float(brier_score_loss(y, oof_p)), 4),
        **{f"{k}_oof": v for k, v in _binary(oof_p, y, tau).items()},
        "threshold": tau, "positives": int(y.sum()), "negatives": int(len(y) - y.sum()),
        "lookalikes": int(sum(r.kind == "lookalike" for r in records)), "folds": len(folds),
        "groups": len(set(groups)), "top_feature_share": round(float(fshare.max()), 3),
        "top_feature": names[int(fshare.argmax())], "note": NOTE,
    }
    return {"model": model, "calibrator": platt, "threshold": tau, "features": names, "label": label,
            "metrics": metrics, "importance": importance, "families": families,
            "oof_raw": oof, "oof_p": oof_p, "oof_fold": fold_of}


def _m7_artifact(fit: dict, seeds: tuple[int, ...]) -> dict:
    return {k: fit[k] for k in ("model", "calibrator", "threshold", "features", "metrics", "importance", "families")} | {
        "version": "1.0", "train_seeds": list(seeds), "n_train": int(fit["metrics"]["positives"] + fit["metrics"]["negatives"]),
        "cv": GROUPING, "trained_at": datetime.now(UTC).isoformat(), "libraries": _libraries()}


# ── M5 and M6, now on four worlds with grouped CV ─────────────────────────


def train_m5(train: list[WorldData]) -> tuple[dict, dict]:
    X = np.vstack([w.chain_X for w in train])
    y = np.concatenate([w.chain_y for w in train])
    groups = [g for w in train for g in w.chain_groups]
    scaler = StandardScaler().fit(X)
    Z = scaler.transform(X)
    oof = np.zeros(len(y))
    for tr, te in grouped_folds(y, groups, 4):
        lr = LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000).fit(Z[tr], y[tr])
        oof[te] = lr.decision_function(Z[te])
    platt = LogisticRegression(C=10.0).fit(oof.reshape(-1, 1), y)
    oof_p = platt.predict_proba(oof.reshape(-1, 1))[:, 1]
    lr = LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000).fit(Z, y)
    metrics = {"roc_auc_oof": round(float(roc_auc_score(y, oof)), 3),
               "pr_auc_oof": round(float(average_precision_score(y, oof)), 3),
               "brier_oof": round(float(brier_score_loss(y, oof_p)), 4),
               "positives": int(y.sum()), "negatives": int(len(y) - y.sum()), "groups": len(set(groups)),
               "note": f"Grouped out-of-fold metrics on training worlds {', '.join(map(str, TRAIN_SEEDS))}. {NOTE}"}
    art = {"scaler": scaler, "lr": lr, "platt": platt, "features": CHAIN_FEATURES, "metrics": metrics,
           "version": "1.1", "train_seeds": list(TRAIN_SEEDS), "n_train": int(len(y)), "cv": GROUPING,
           "trained_at": datetime.now(UTC).isoformat(), "libraries": _libraries()}
    card = {"model": "M5 chain classifier", "algorithm": "Standardised logistic regression + Platt calibration",
            "features": CHAIN_FEATURES, "coefficients": dict(zip(CHAIN_FEATURES, map(float, lr.coef_[0]), strict=True)),
            "metrics": metrics, "train_seeds": list(TRAIN_SEEDS), "cv": GROUPING}
    return art, card


def train_m6(train: list[WorldData]) -> tuple[dict, dict]:
    X = np.vstack([w.mule_X for w in train])
    y = np.concatenate([w.mule_y for w in train])
    groups = [g for w in train for g in w.mule_groups]

    def model() -> LGBMClassifier:
        return LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=5,
                              class_weight="balanced", random_state=0, deterministic=True, force_col_wise=True,
                              n_jobs=4, verbose=-1)

    oof = np.zeros(len(y))
    for tr, te in grouped_folds(y, groups, 4):
        oof[te] = model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    m = model().fit(X, y)
    top = np.argsort(-oof, kind="stable")[: int(y.sum())]
    metrics = {"roc_auc_oof": round(float(roc_auc_score(y, oof)), 3),
               "pr_auc_oof": round(float(average_precision_score(y, oof)), 3),
               "precision_at_k": round(float(y[top].mean()), 3), "k": int(y.sum()),
               "positives": int(y.sum()), "negatives": int(len(y) - y.sum()), "groups": len(set(groups)),
               "note": f"Grouped out-of-fold metrics on training worlds {', '.join(map(str, TRAIN_SEEDS))}. {NOTE}"}
    art = {"model": m, "features": MULE_FEATURES, "metrics": metrics, "version": "1.1",
           "train_seeds": list(TRAIN_SEEDS), "n_train": int(len(y)), "cv": GROUPING,
           "trained_at": datetime.now(UTC).isoformat(), "libraries": _libraries()}
    card = {"model": "M6 mule-likeness", "algorithm": "LightGBM (200 trees, 15 leaves) with TreeSHAP",
            "features": MULE_FEATURES, "metrics": metrics, "train_seeds": list(TRAIN_SEEDS), "cv": GROUPING}
    return art, card


# ── entry point ───────────────────────────────────────────────────────────


def train_all(size: str = "demo", evaluate: bool = True) -> dict:
    t0 = time.perf_counter()
    jobs = [(s, size, False) for s in TRAIN_SEEDS]
    if evaluate:
        jobs += [(s, size, False) for s in HELDOUT_SEEDS] + [(42, size, True)]
    worlds = build_worlds(jobs)
    train = [w for w in worlds if w.seed in TRAIN_SEEDS]
    heldout = [w for w in worlds if w.seed not in TRAIN_SEEDS]  # never passed to anything that fits
    print(f"  worlds ready ({time.perf_counter() - t0:.0f}s)")

    art_dir = get_settings().artifacts_path
    art_dir.mkdir(parents=True, exist_ok=True)
    cards = REPO_ROOT / "ml" / "model_cards"
    cards.mkdir(parents=True, exist_ok=True)

    m5, m5_card = train_m5(train)
    joblib.dump(m5, art_dir / "chain_classifier.joblib")
    print(f"▸ M5 chain classifier  {m5['metrics']}")
    m6, m6_card = train_m6(train)
    joblib.dump(m6, art_dir / "mule_model.joblib")
    print(f"▸ M6 mule-likeness     {m6['metrics']}")

    cases = [c for w in train for c in w.cases]
    fits = {"M7": fit_case_model(cases, CASE_FEATURES, "M7"),
            "M7-structure": fit_case_model(cases, STRUCTURE_FEATURES, "M7 without detector features")}
    past = [c for c in cases if c.last_t < LATER_CUTOFF]
    fits["M7-past"] = fit_case_model(past, CASE_FEATURES, "M7 trained on cases that ended before the cutoff")
    fits["M7-structure-past"] = fit_case_model(past, STRUCTURE_FEATURES, "M7 without detector features, past only")
    m7 = _m7_artifact(fits["M7"], TRAIN_SEEDS)
    m7["ablation"] = {"M7-structure": fits["M7-structure"]["metrics"]}
    joblib.dump(m7, art_dir / "case_prioritiser.joblib")
    print(f"▸ M7 case prioritiser  {fits['M7']['metrics']}")
    print(f"  without detectors    {fits['M7-structure']['metrics']}")

    m7_card = {"model": "M7 connected-case prioritiser",
               "algorithm": "LightGBM (300 trees, 15 leaves) with TreeSHAP; Platt calibration on grouped "
                            "out-of-fold scores; operating threshold maximises out-of-fold F1",
               "unit": "Connected case (app.ml.cases): chains and seeding signals joined by shared accounts, "
                       "customers, devices or counterparties — never by staff",
               "label": "1 when the case touches a suspicious scenario instance (docs/ml/labeling.md)",
               "features": [{"feature": k, "label": CASE_LABELS[k], "family": FAMILY[k]} for k in CASE_FEATURES],
               "metrics": m7["metrics"], "ablation": m7["ablation"], "importance": m7["importance"],
               "families": m7["families"], "train_seeds": list(TRAIN_SEEDS), "cv": GROUPING,
               "use": "Orders the queue inside each priority band and is shown as a suspicion score. It never "
                      "sets P1, never closes a case and is never a determination — that stays with four-eyes review.",
               "libraries": m7["libraries"]}
    for name, card in (("m5_chain_classifier", m5_card), ("m6_mule_model", m6_card), ("m7_case_prioritiser", m7_card)):
        (cards / f"{name}.json").write_text(json.dumps(card, indent=2))

    from app.ml.models import reload

    reload()
    out = {"m5": m5["metrics"], "m6": m6["metrics"], "m7": m7["metrics"]}
    if evaluate:
        from app.lab.heldout import evaluate as run_eval

        report = run_eval(train, heldout, fits, m7_card)
        out["evaluation"] = report["summary"]
    print(f"✓ Training finished in {time.perf_counter() - t0:.1f}s")
    return out
