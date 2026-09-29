"""Behavioural baselines for staff.

M1 — access rhythm. Each employee's share of sessions per hour-of-week bin (168 bins),
     shrunk toward the peer group (same role) with empirical-Bayes weight k. A session
     is *surprising* when its leave-one-out shrunk share is below a threshold.
M2 — navigation. A role-conditioned first-order Markov chain over access actions within a
     session; a session is unusual when its mean transition log-likelihood falls in the
     bottom percentile for the role. The rarest transitions are reported as evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.loom.frames import Frames

K_SHRINK = 20.0


def _bin(ts: pd.Series) -> np.ndarray:
    return (ts.dt.weekday * 24 + ts.dt.hour).to_numpy()


@dataclass
class RhythmModel:
    counts: dict[str, np.ndarray]
    totals: dict[str, int]
    peer_share: dict[str, np.ndarray]
    role: dict[str, str]

    def share_loo(self, emp: str, hbin: int) -> float:
        c, n, p = self.counts[emp], self.totals[emp], self.peer_share[self.role[emp]]
        return float((max(c[hbin] - 1, 0) + K_SHRINK * p[hbin]) / (max(n - 1, 0) + K_SHRINK))

    def shrunk(self, emp: str) -> np.ndarray:
        c, n, p = self.counts[emp], self.totals[emp], self.peer_share[self.role[emp]]
        return (c + K_SHRINK * p) / (n + K_SHRINK)


def fit_rhythm(f: Frames) -> RhythmModel:
    s = f.session[f.session["actor_type"] == "EMPLOYEE"]
    role = f.employee.set_index("id")["role"].to_dict()
    counts, totals = {}, {}
    bins = pd.Series(_bin(s["started_at"]), index=s.index)
    for emp, grp in s.groupby("actor_id"):
        c = np.bincount(bins.loc[grp.index], minlength=168).astype(float)
        counts[emp], totals[emp] = c, int(c.sum())
    for emp in role:
        counts.setdefault(emp, np.zeros(168))
        totals.setdefault(emp, 0)
    peer = {}
    for r in set(role.values()):
        members = [e for e, rr in role.items() if rr == r]
        tot = sum(counts[e] for e in members)
        peer[r] = (tot + 0.01) / (tot.sum() + 1.68)
    return RhythmModel(counts, totals, peer, role)


def session_surprise(f: Frames, model: RhythmModel) -> pd.DataFrame:
    s = f.session[f.session["actor_type"] == "EMPLOYEE"].copy()
    s["hbin"] = _bin(s["started_at"])
    s["share"] = [model.share_loo(e, h) for e, h in zip(s["actor_id"], s["hbin"], strict=True)]
    s["late"] = s["started_at"].dt.hour >= 20
    late_by_emp = s.groupby("actor_id")["late"].agg(["sum", "count"])
    s["late_prior"] = s["actor_id"].map(late_by_emp["sum"]) - s["late"].astype(int)
    s["sessions_prior"] = s["actor_id"].map(late_by_emp["count"]) - 1
    role = f.employee.set_index("id")["role"]
    s["role"] = s["actor_id"].map(role)
    peer_late = s.groupby("role")["late"].mean()
    s["peer_late_share"] = s["role"].map(peer_late)
    return s[["id", "actor_id", "role", "channel", "device_id", "started_at", "hbin", "share", "late",
              "late_prior", "sessions_prior", "peer_late_share"]]


# ── M2: navigation ────────────────────────────────────────────────────────────


@dataclass
class NavModel:
    probs: dict[str, dict[tuple[str, str], float]]
    vocab: list[str]
    role_scores: dict[str, np.ndarray]


def _sequences(f: Frames) -> dict[str, list[str]]:
    a = f.access_event.dropna(subset=["session_id"]).sort_values("occurred_at")
    return {sid: ["START", *grp["action"].tolist()] for sid, grp in a.groupby("session_id")}


def fit_navigation(f: Frames) -> NavModel:
    seqs = _sequences(f)
    sess_emp = f.session.set_index("id")["actor_id"]
    role = f.employee.set_index("id")["role"]
    vocab = sorted({x for s in seqs.values() for x in s})
    counts: dict[str, Counter] = defaultdict(Counter)
    for sid, seq in seqs.items():
        r = role.get(sess_emp.get(sid))
        for a, b in zip(seq, seq[1:], strict=False):
            counts[r][(a, b)] += 1
    probs = {}
    for r, c in counts.items():
        row_tot = Counter()
        for (a, _b), n in c.items():
            row_tot[a] += n
        probs[r] = {(a, b): (c[(a, b)] + 0.1) / (row_tot[a] + 0.1 * len(vocab))
                    for a in vocab for b in vocab}
    model = NavModel(probs, vocab, {})
    per_role = defaultdict(list)
    for sid, seq in seqs.items():
        r = role.get(sess_emp.get(sid))
        if r and len(seq) >= 3:
            per_role[r].append(model.score(seq, r)[0])
    model.role_scores = {r: np.sort(np.array(v)) for r, v in per_role.items()}
    return model


def _score(self: NavModel, seq: list[str], role: str) -> tuple[float, list[dict]]:
    p = self.probs.get(role, {})
    trans = [(a, b, p.get((a, b), 1e-4)) for a, b in zip(seq, seq[1:], strict=False)]
    ll = float(np.mean([np.log(x[2]) for x in trans])) if trans else 0.0
    rare = sorted(({"from": a, "to": b, "p": round(q, 4)} for a, b, q in trans if q < 0.02),
                  key=lambda d: d["p"])[:3]
    return ll, rare


def _percentile(self: NavModel, ll: float, role: str) -> float:
    arr = self.role_scores.get(role)
    if arr is None or len(arr) == 0:
        return 0.5
    return float(np.searchsorted(arr, ll, side="right") / len(arr))


NavModel.score = _score
NavModel.percentile = _percentile


def session_navigation(f: Frames, model: NavModel) -> pd.DataFrame:
    seqs = _sequences(f)
    sess_emp = f.session.set_index("id")["actor_id"]
    role = f.employee.set_index("id")["role"]
    rows = []
    for sid, seq in seqs.items():
        emp = sess_emp.get(sid)
        r = role.get(emp)
        if r is None or len(seq) < 3:
            continue
        ll, rare = model.score(seq, r)
        rows.append((sid, emp, r, len(seq) - 1, ll, model.percentile(ll, r), rare, seq[1:]))
    return pd.DataFrame(rows, columns=["session_id", "employee_id", "role", "n_transitions", "ll",
                                       "percentile", "rare", "actions"])
