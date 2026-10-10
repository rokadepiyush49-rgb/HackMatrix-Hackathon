"""M1 (access rhythm) and M2 (navigation) against simple baselines and one alternative (FIN-04 evidence).

    python -m app.cli eval-behaviour        → ml/reports/m1_m2_eval.json

M1 and M2 are unsupervised: they are fitted on each run's own 90-day window and never see a label, so no
world is used to fit them here either. Thresholds (M1 share < 0.004 after 20:00; M2 bottom 0.5% for the
role) were set on the demo world (seed 42), so it is left out; worlds 7–11 are scored instead.

Unit: one staff session. Positive: a session in which an insider scenario's labelled staff actions took
place (S4/S5 suspicious variants). Look-alikes: sessions behind the legitimate twins (camp duty, declared
relationships) — after-hours, sensitive, and innocent. The positive class is tiny (a few sessions per
world), so every number comes with its counts, and none is a claim about real-bank accuracy.

Compared on the same sessions:
  M1               leave-one-out hour-of-week share, shrunk toward the role        (deployed)
  M2               role-conditioned Markov log-likelihood percentile               (deployed)
  AFTER_HOURS      the session starts at or after 20:00 or before 07:00             (rule baseline)
  FIRST_LATE       after hours and the person's first after-hours session          (rule baseline)
  SENSITIVE        count of sensitive actions (mobile, limit, nominee, override)    (rule baseline)
  M2-LOO           M2 with the scored session's own transitions removed from the
                   role counts before scoring                                       (alternative)
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

SEEDS = (7, 8, 9, 10, 11)
SENSITIVE = {"MOBILE_UPDATE", "LIMIT_CHANGE", "NOMINEE_UPDATE", "ADDRESS_UPDATE", "KYC_APPROVE", "ACCT_OPEN"}
M1_SHARE, M2_PCT = 0.004, 0.005


def _late(ts: pd.Series) -> pd.Series:
    h = ts.dt.hour
    return (h >= 20) | (h < 7)


def _m2_loo(f, nav_model) -> pd.DataFrame:
    """Score every session with its own transitions removed from its role's counts."""
    from app.ml.baselines import _sequences

    seqs = _sequences(f)
    sess_emp = f.session.set_index("id")["actor_id"]
    role = f.employee.set_index("id")["role"]
    vocab = nav_model.vocab
    V = len(vocab)
    counts: dict[str, Counter] = defaultdict(Counter)
    rows: dict[str, Counter] = defaultdict(Counter)
    for sid, seq in seqs.items():
        r = role.get(sess_emp.get(sid))
        for a, b in zip(seq, seq[1:], strict=False):
            counts[r][(a, b)] += 1
            rows[r][a] += 1
    out = []
    for sid, seq in seqs.items():
        r = role.get(sess_emp.get(sid))
        if r is None or len(seq) < 3:
            continue
        own = Counter(zip(seq, seq[1:], strict=False))
        own_rows = Counter(a for a, _ in own.elements())
        lls = [np.log((counts[r][(a, b)] - own[(a, b)] + 0.1) / (rows[r][a] - own_rows[a] + 0.1 * V))
               for a, b in zip(seq, seq[1:], strict=False)]
        out.append((sid, r, float(np.mean(lls))))
    df = pd.DataFrame(out, columns=["session_id", "role", "ll"])
    df["percentile"] = df.groupby("role")["ll"].rank(pct=True, method="max")
    return df


def score_world(seed: int, size: str = "demo") -> dict:
    from app.loom.frames import frames_from_world
    from app.ml import baselines
    from kestrel_sim import generate

    world = generate(seed=seed, size=size)
    f = frames_from_world(world)
    ae = f.access_event.set_index("id")
    pos_events = {e for x in world.labels if x["variant"] == "suspicious" and x["scenario"] in ("S4", "S5")
                  for e in x["events"]}
    twin_events = {e for x in world.labels if x["variant"] == "twin" and x["scenario"] in ("S4", "S5")
                   for e in x["events"]}
    pos = {ae.at[e, "session_id"] for e in pos_events if e in ae.index and pd.notna(ae.at[e, "session_id"])}
    twin = {ae.at[e, "session_id"] for e in twin_events if e in ae.index and pd.notna(ae.at[e, "session_id"])} - pos

    sess = baselines.session_surprise(f, baselines.fit_rhythm(f))
    nav_model = baselines.fit_navigation(f)
    nav = baselines.session_navigation(f, nav_model).set_index("session_id")
    loo = _m2_loo(f, nav_model).set_index("session_id")
    in_session = f.access_event.dropna(subset=["session_id"])
    acts = in_session.groupby("session_id")["action"].apply(lambda s: int(sum(a in SENSITIVE for a in s)))
    if "auth_method" in in_session:
        acts = acts.add(in_session[in_session["auth_method"] == "OVERRIDE"].groupby("session_id").size(), fill_value=0)

    s = sess.set_index("id")
    s["late_any"] = _late(s["started_at"])
    first_late = s.sort_values("started_at").groupby("actor_id")["late_any"].cumsum()
    s["first_late"] = s["late_any"] & (first_late == 1)
    df = pd.DataFrame(index=s.index)
    df["y"] = df.index.isin(pos).astype(int)
    df["twin"] = df.index.isin(twin)
    df["M1"] = -s["share"]
    df["M1_flag"] = (s["share"] < M1_SHARE) & s["late"]
    df["M2"] = -nav["percentile"].reindex(df.index).fillna(1.0)
    df["M2_flag"] = nav["percentile"].reindex(df.index).fillna(1.0) < M2_PCT
    df["M2-LOO"] = -loo["percentile"].reindex(df.index).fillna(1.0)
    df["M2-LOO_flag"] = loo["percentile"].reindex(df.index).fillna(1.0) < M2_PCT
    df["AFTER_HOURS"] = s["late_any"].astype(float)
    df["AFTER_HOURS_flag"] = s["late_any"]
    df["FIRST_LATE"] = s["first_late"].astype(float)
    df["FIRST_LATE_flag"] = s["first_late"]
    df["SENSITIVE"] = acts.reindex(df.index).fillna(0).astype(float)
    df["SENSITIVE_flag"] = df["SENSITIVE"] >= 2
    return {"seed": seed, "frame": df.reset_index(names="session_id").to_dict("list")}


METHODS = ("M1", "M2", "AFTER_HOURS", "FIRST_LATE", "SENSITIVE", "M2-LOO")


def _metrics(df: pd.DataFrame, m: str) -> dict:
    y = df["y"].to_numpy()
    flag = df[f"{m}_flag"].to_numpy().astype(bool)
    tp = int((flag & (y == 1)).sum())
    out = {"flagged": int(flag.sum()), "tp": tp, "precision": round(tp / flag.sum(), 3) if flag.sum() else None,
           "recall": round(tp / y.sum(), 3) if y.sum() else None,
           "lookalikes_flagged": int((flag & df["twin"].to_numpy()).sum()),
           "flagged_per_1000_sessions": round(1000 * flag.sum() / len(df), 2)}
    if 0 < y.sum() < len(y):
        out["pr_auc"] = round(float(average_precision_score(y, df[m].to_numpy())), 3)
        out["pr_auc_chance"] = round(float(y.mean()), 5)
    return out


def evaluate(seeds=SEEDS, size: str = "demo", out_path=None) -> dict:
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=min(4, len(seeds))) as pool:
        worlds = list(pool.map(score_world, seeds, [size] * len(seeds)))
    frames = {w["seed"]: pd.DataFrame(w["frame"]) for w in worlds}
    pooled = pd.concat(frames.values(), ignore_index=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": "Synthetic Kestrel-Sim worlds. Unsupervised models scored against simulator ground truth; not "
                "real-bank accuracy. The positive class is a handful of sessions per world.",
        "unit": "staff session", "worlds": list(seeds), "excluded": {"42": "thresholds were set on the demo world"},
        "label": "1 when an S4/S5 suspicious variant's labelled staff action happened in the session",
        "counts": {str(k): {"sessions": len(v), "positives": int(v["y"].sum()), "lookalike_sessions": int(v["twin"].sum())}
                   for k, v in frames.items()} | {"pooled": {"sessions": len(pooled), "positives": int(pooled["y"].sum()),
                                                            "lookalike_sessions": int(pooled["twin"].sum())}},
        "thresholds": {"M1": f"share < {M1_SHARE} and starts at or after 20:00",
                       "M2": f"bottom {M2_PCT:.1%} of the role", "M2-LOO": f"bottom {M2_PCT:.1%} of the role",
                       "AFTER_HOURS": "starts at or after 20:00 or before 07:00",
                       "FIRST_LATE": "after hours and the person's first after-hours session",
                       "SENSITIVE": "two or more sensitive actions or override uses"},
        "pooled": {m: _metrics(pooled, m) for m in METHODS},
        "per_world": {str(k): {m: _metrics(v, m) for m in METHODS} for k, v in frames.items()},
        "seconds": round(time.perf_counter() - t0, 1),
    }
    p, a = report["pooled"]["M2"].get("pr_auc"), report["pooled"]["M2-LOO"].get("pr_auc")
    wins = sum(1 for w in report["per_world"].values()
               if (w["M2-LOO"].get("pr_auc") or 0) >= (w["M2"].get("pr_auc") or 0) + 0.02)
    report["decision"] = {
        "rule": "Replace M2 only if M2-LOO raises pooled PR-AUC by ≥ 0.02, wins by ≥ 0.02 in a majority of worlds, "
                "and flags no more look-alikes.",
        "m2_loo_pr_auc_delta": None if p is None or a is None else round(a - p, 3),
        "worlds_won": wins,
        "replace_m2": bool(p is not None and a is not None and a - p >= 0.02 and wins > len(seeds) / 2
                           and report["pooled"]["M2-LOO"]["lookalikes_flagged"]
                           <= report["pooled"]["M2"]["lookalikes_flagged"]),
    }
    report["m2_threshold_study"] = _threshold_study(frames)
    if out_path:
        out_path.write_text(json.dumps(report, indent=2))
    return report


TUNE, TEST = (7, 8, 9), (10, 11)
CANDIDATES = (0.005, 0.01, 0.02, 0.05, 0.10)


def _threshold_study(frames: dict) -> dict:
    """Pick M2's percentile threshold on worlds 7–9 by F1, then report it once on worlds 10–11."""
    tune = pd.concat([frames[s] for s in TUNE if s in frames], ignore_index=True)
    test = pd.concat([frames[s] for s in TEST if s in frames], ignore_index=True)

    def at(df: pd.DataFrame, pct: float) -> dict:
        flag = (-df["M2"]) < pct
        y = df["y"].astype(bool)
        tp = int((flag & y).sum())
        p = tp / flag.sum() if flag.sum() else 0.0
        r = tp / y.sum() if y.sum() else 0.0
        return {"threshold": pct, "flagged": int(flag.sum()), "tp": tp, "precision": round(p, 3), "recall": round(r, 3),
                "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0, "lookalikes_flagged": int((flag & df["twin"]).sum())}

    sweep = [at(tune, c) for c in CANDIDATES]
    best = max(sweep, key=lambda x: (x["f1"], -x["threshold"]))
    return {"tune_worlds": list(TUNE), "test_worlds": list(TEST), "candidates": list(CANDIDATES), "tune_sweep": sweep,
            "chosen_on_tune": best["threshold"], "test_at_chosen": at(test, best["threshold"]),
            "test_at_deployed": at(test, M2_PCT),
            "note": "Chosen on the tuning worlds only; the test worlds are reported once at the chosen and deployed "
                    "thresholds. Changing the deployed threshold would change M2 signals, which are M7 features, so "
                    "M7 would have to be retrained and re-evaluated before any change."}
