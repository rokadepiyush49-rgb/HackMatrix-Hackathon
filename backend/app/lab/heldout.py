"""FIN-04 evaluation: M7 against the documented rule baselines (docs/ml/rule_baseline.md).

Three test sets, four methods, every number with a 95% bootstrap interval over groups.

  cv       Unseen connected cases — grouped out-of-fold predictions over training worlds 7–10.
  heldout  Unseen accounts and cases — worlds 11 (randomised) and 42 (the demo world), never used for
           fitting, thresholds or feature choices.
  later    Later events — models refitted on training cases that ended before the cutoff (2 Sep), scored
           on held-out cases that later events produced or changed: every case with an event on or after
           the cutoff, including the one the 22 Sep live feed extends.

  RB-1           documented rule set (app.lab.rule_baseline), no learned parameter
  RB-2           SUTRA's priority lattice with every model input off; P1–P3 counts as an alert
  M7             connected-case prioritiser at its out-of-fold F1 threshold
  M7-structure   the same model without detector-evidence features (graph + sequence only)

Look-alikes — legitimate twins and mule look-alikes — are in every test set and reported separately.
The report states what it measured. It never claims a winner: the reader compares the rows.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime

import numpy as np
from sklearn.metrics import average_precision_score

from app.core.config import REPO_ROOT
from app.lab.rule_baseline import QUEUED, describe
from app.ml.case_features import CASE_LABELS, CaseRow
from app.ml.models import explain_cases
from app.ml.worlds import LATER_CUTOFF, TRAIN_SEEDS, CaseRecord, WorldData

METHODS = ["RB-1", "RB-2", "M7", "M7-structure"]
METHOD_LABELS = {"RB-1": "Rule baseline RB-1", "RB-2": "SUTRA lattice, rules only (RB-2)",
                 "M7": "M7 connected-case prioritiser", "M7-structure": "M7 without detector features"}
B = 1000
REPORTS = REPO_ROOT / "ml" / "reports"
RB2_ORDINAL = {"P1": 3.0, "P2": 2.0, "P3": 1.0, "WATCH": 0.5}


def _ci(values: list[float], point: float) -> dict:
    v = np.array([x for x in values if x == x])
    if not len(v) or point != point:
        return {"value": None if point != point else round(point, 3), "lo": None, "hi": None}
    return {"value": round(point, 3), "lo": round(float(np.percentile(v, 2.5)), 3),
            "hi": round(float(np.percentile(v, 97.5)), 3)}


def _point(y: np.ndarray, a: np.ndarray, la: np.ndarray, score: np.ndarray) -> dict[str, float]:
    tp, fp, fn = int((a & (y == 1)).sum()), int((a & (y == 0)).sum()), int((~a & (y == 1)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fn else float("nan")
    ap = float(average_precision_score(y, score)) if 0 < y.sum() < len(y) else float("nan")
    la_fp = float(a[la].mean()) if la.any() else float("nan")
    return {"precision": prec, "recall": rec, "f1": f1, "pr_auc": ap, "lookalike_fp_rate": la_fp}


def _metrics(recs: list[CaseRecord], alert: np.ndarray, score: np.ndarray, accounts: int,
             rng: np.random.Generator) -> dict:
    y = np.array([r.y for r in recs])
    la = np.array([r.kind == "lookalike" for r in recs])
    point = _point(y, alert, la, score)
    members: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(recs):
        members[r.group].append(i)
    groups = list(members.values())
    boot = defaultdict(list)
    for _ in range(B):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[j] for j in pick])
        for k, v in _point(y[idx], alert[idx], la[idx], score[idx]).items():
            boot[k].append(v)
    tp = int((alert & (y == 1)).sum())
    return {"alerts": int(alert.sum()), "tp": tp, "fp": int(alert.sum()) - tp, "fn": int(y.sum()) - tp,
            "lookalike_alerts": int(alert[la].sum()),
            "alerts_per_1k_accounts": round(1000 * float(alert.sum()) / max(accounts, 1), 2),
            **{k: _ci(boot[k], v) for k, v in point.items()}}


def _scores(recs: list[CaseRecord], fit: dict) -> tuple[np.ndarray, np.ndarray, list]:
    rows = [CaseRow(r.key, r.values, r.provenance) for r in recs]
    s = explain_cases(fit, rows) if rows else []
    return (np.array([x.p for x in s]), np.array([x.raw for x in s]), s)


def _test_set(key: str, title: str, recs: list[CaseRecord], accounts: int, worlds: list[str],
              m7: tuple[np.ndarray, np.ndarray, float, list], m7s: tuple[np.ndarray, np.ndarray, float, list],
              rng: np.random.Generator) -> tuple[dict, list[dict]]:
    y = np.array([r.y for r in recs])
    alerts = {
        "RB-1": np.array([bool(r.rb1) for r in recs]),
        "RB-2": np.array([r.rb2 in QUEUED for r in recs]),
        "M7": m7[0] >= m7[2],
        "M7-structure": m7s[0] >= m7s[2],
    }
    scores = {
        "RB-1": np.array([float(len(r.rb1)) for r in recs]),
        "RB-2": np.array([RB2_ORDINAL.get(r.rb2 or "", 0.0) for r in recs]),
        "M7": m7[1], "M7-structure": m7s[1],
    }
    rows = []
    for m in METHODS:
        row = {"method": m, "label": METHOD_LABELS[m], **_metrics(recs, alerts[m], scores[m], accounts, rng)}
        if m.startswith("M7"):
            row["threshold"] = (m7 if m == "M7" else m7s)[2]
            k = int(alerts["RB-1"].sum())
            top = np.argsort(-scores[m], kind="stable")[:k]
            row["at_rb1_budget"] = {"k": k, "tp": int(y[top].sum()),
                                    "precision": round(float(y[top].mean()), 3) if k else None,
                                    "recall": round(float(y[top].sum() / max(y.sum(), 1)), 3)}
        rows.append(row)

    by_typ = []
    for typ in sorted({r.typology for r in recs if r.y}):
        idx = np.array([r.y == 1 and r.typology == typ for r in recs])
        by_typ.append({"typology": typ, "cases": int(idx.sum()),
                       "recall": {m: round(float(alerts[m][idx].mean()), 3) for m in METHODS}})
    by_la = []
    for typ in sorted({t for r in recs if r.kind == "lookalike" for t in r.typology.split("+")}):
        idx = np.array([r.kind == "lookalike" and typ in r.typology.split("+") for r in recs])
        by_la.append({"type": typ, "cases": int(idx.sum()),
                      "alerted": {m: int(alerts[m][idx].sum()) for m in METHODS}})

    preds = []
    for i, r in enumerate(recs):
        top = [c for c in m7[3][i].contributions if c["contribution"] > 0][:3] if m7[3] else []
        preds.append({
            "test_set": key, "world": r.world, "case_key": r.key, "label": r.y, "label_kind": r.kind,
            "typology": r.typology, "scenario_instances": ";".join(r.labels), "group": r.group,
            "first_seen": r.first_t.isoformat(), "last_seen": r.last_t.isoformat(), "late_event": int(r.late),
            "rb1_alert": int(alerts["RB-1"][i]), "rb1_clauses": ";".join(r.rb1),
            "rb2_priority": r.rb2 or "", "rb2_alert": int(alerts["RB-2"][i]),
            "m7_score": round(float(m7[0][i]), 4), "m7_alert": int(alerts["M7"][i]),
            "m7_structure_score": round(float(m7s[0][i]), 4), "m7_structure_alert": int(alerts["M7-structure"][i]),
            "top_features": ";".join(f"{c['feature']}={c['contribution']:+.2f}" for c in top),
            "supporting_refs": ";".join(dict.fromkeys(ref for c in top for ref in c["refs"][:4])),
            "detectors": ";".join(r.detectors), "chains": ";".join(r.chains),
        })
    return {"key": key, "title": title, "worlds": worlds, "cases": len(recs), "positives": int(y.sum()),
            "lookalikes": int(sum(r.kind == "lookalike" for r in recs)),
            "background": int(sum(r.kind == "background" for r in recs)), "accounts": accounts,
            "rows": rows, "by_typology": by_typ, "lookalikes_by_type": by_la}, preds


def evaluate(train: list[WorldData], heldout: list[WorldData], fits: dict, m7_card: dict) -> dict:
    rng = np.random.default_rng(0)
    assert not {w.seed for w in heldout} & set(TRAIN_SEEDS)
    sets, preds = [], []

    # (a) grouped out-of-fold over the training worlds
    cv = [c for w in train for c in w.cases]
    oof = {m: (fits[m]["oof_p"], fits[m]["oof_raw"], fits[m]["threshold"]) for m in ("M7", "M7-structure")}
    m7_cv = (*oof["M7"], _scores(cv, fits["M7"])[2])  # explanations from the final model, for the CSV only
    s, p = _test_set("cv", "Unseen connected cases — grouped 5-fold out-of-fold, training worlds 7–10",
                     cv, sum(w.accounts for w in train), [w.name for w in train], m7_cv,
                     (*oof["M7-structure"], []), rng)
    s["note"] = ("Out-of-fold scores; the operating threshold was chosen on these same scores, so this set is "
                 "slightly optimistic for M7. The held-out and later sets use that threshold frozen.")
    sets.append(s)
    preds += p

    # (b) held-out worlds 11 and 42
    hw = [w for w in heldout if w.name in ("11", "42")]
    ho = [c for w in hw for c in w.cases]
    sc, scs = _scores(ho, fits["M7"]), _scores(ho, fits["M7-structure"])
    s, p = _test_set("heldout", "Unseen accounts and connected cases — held-out worlds 11 and 42", ho,
                     sum(w.accounts for w in hw), [w.name for w in hw],
                     (sc[0], sc[1], fits["M7"]["threshold"], sc[2]),
                     (scs[0], scs[1], fits["M7-structure"]["threshold"], scs[2]), rng)
    sets.append(s)
    preds += p

    # (c) later events: past-only models, cases that events on or after the cutoff produced or changed
    lw = [w for w in heldout if w.name in ("11", "42+feed")]
    later = [c for w in lw for c in w.cases if c.last_t >= LATER_CUTOFF or c.late]
    sc, scs = _scores(later, fits["M7-past"]), _scores(later, fits["M7-structure-past"])
    s, p = _test_set("later", f"Later events — held-out cases with an event on or after {LATER_CUTOFF:%d %b} "
                              "(including the 22 Sep live feed); models refitted on cases that ended before it",
                     later, sum(w.accounts for w in lw), [w.name for w in lw],
                     (sc[0], sc[1], fits["M7-past"]["threshold"], sc[2]),
                     (scs[0], scs[1], fits["M7-structure-past"]["threshold"], scs[2]), rng)
    sets.append(s)
    preds += p
    feed = [{"case_key": r.key, "label_kind": r.kind, "typology": r.typology, "instances": list(r.labels),
             "rb1": list(r.rb1), "rb2": r.rb2, "m7_score": round(float(sc[0][i]), 3),
             "m7_alert": bool(sc[0][i] >= fits["M7-past"]["threshold"]),
             "top_features": [{"label": c["label"], "contribution": c["contribution"], "refs": c["refs"][:4]}
                              for c in sc[2][i].contributions[:4]]}
            for i, r in enumerate(later) if r.late]

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": "Every number is measured on synthetic Kestrel-Sim worlds. None is a claim about real-bank accuracy.",
        "unit": "Connected case (app.ml.cases). Labels: docs/ml/labeling.md. Features: docs/ml/features.md.",
        "train_worlds": [w.name for w in train], "heldout_worlds": [w.name for w in heldout],
        "later_cutoff": LATER_CUTOFF.isoformat(), "bootstrap": {"replicates": B, "unit": "group", "interval": "95%"},
        "baselines": describe(), "methods": METHOD_LABELS,
        "models": {m: {"label": fits[m]["label"], "threshold": fits[m]["threshold"], "metrics": fits[m]["metrics"],
                       "families": fits[m]["families"], "importance": fits[m]["importance"][:10]}
                   for m in ("M7", "M7-structure", "M7-past", "M7-structure-past")},
        "feature_labels": CASE_LABELS, "model_card": m7_card,
        "test_sets": sets, "live_feed": feed,
        "live_feed_note": ("The 22 Sep evening holds a second insider takeover that pays into the 21 Sep mule ring, "
                           "and a legitimate pension camp. The camp opens no case: Alibi explains both mobile "
                           "changes and no seeding detector fires."),
    }
    report["summary"] = {s["key"]: {r["method"]: {"precision": r["precision"]["value"], "recall": r["recall"]["value"],
                                                  "lookalike_fp_rate": r["lookalike_fp_rate"]["value"]}
                                    for r in s["rows"]} for s in sets}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "fin04_eval.json").write_text(json.dumps(report, indent=2, default=str))
    (REPORTS / "model_card_m7.json").write_text(json.dumps(m7_card, indent=2))
    (REPORTS / "rule_baseline.json").write_text(json.dumps(
        {"baselines": describe(), "results": [{"test_set": s["key"], **{k: v for k, v in r.items()}}
                                              for s in sets for r in s["rows"] if r["method"].startswith("RB")]},
        indent=2))
    with (REPORTS / "heldout_predictions.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(preds[0]))
        w.writeheader()
        w.writerows(preds)
    _print(report)
    return report


def _print(report: dict) -> None:
    def fmt(m: dict) -> str:
        return "  —  " if m["value"] is None else f"{m['value']:.2f}"

    print("▸ FIN-04 evaluation (synthetic) — precision · recall · F1 · look-alike FP rate")
    for s in report["test_sets"]:
        print(f"  {s['key']:<8} {s['cases']} cases, {s['positives']} suspicious, {s['lookalikes']} look-alikes")
        for r in s["rows"]:
            print(f"    {r['method']:<13} alerts {r['alerts']:>4}  P {fmt(r['precision'])}  R {fmt(r['recall'])}  "
                  f"F1 {fmt(r['f1'])}  look-alike FP {fmt(r['lookalike_fp_rate'])}")
    print(f"  → {REPORTS.relative_to(REPO_ROOT)}/fin04_eval.json, heldout_predictions.csv, rule_baseline.json")
