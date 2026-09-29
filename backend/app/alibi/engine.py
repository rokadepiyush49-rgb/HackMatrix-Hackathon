"""Alibi — explanation-based access auditing.

Access logs say *who* touched a record; Alibi asks *why*. Each access is tested against
explanation templates (after Fabbri & LeFevre, "Explanation-Based Auditing", PVLDB 2011):

    purpose  TICKET       a service ticket for this customer/account, semantically about this action
             PORTFOLIO    the customer is in the employee's portfolio
             QUEUE        a workflow queue item for this account assigned to the employee
             INTERACTION  a branch token / biometric eKYC (±45 min) or a call-centre record (24 h)
    timing   ROSTER       the access falls inside a rostered shift (regular, overtime or camp)

Verdict: EXPLAINED (purpose ✓ and timing ✓) · PARTIAL (one) · UNEXPLAINED (neither).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.loom.frames import Frames

ACTION_DESC = {
    "MOBILE_UPDATE": "update change registered mobile number phone sim lost new number",
    "LIMIT_CHANGE": "increase raise transfer limit imps per-transaction payment booking dealer fee",
    "ADDRESS_UPDATE": "address change update communication proof house shift bill",
    "CARD_ISSUE": "debit card reissue new card damaged expired",
    "ACCT_VIEW": "account statement certificate passbook view query request loan visa",
}
STATE_ACTIONS = {"MOBILE_UPDATE", "LIMIT_CHANGE", "ADDRESS_UPDATE", "CARD_ISSUE"}
TEMPLATES = ["TICKET", "PORTFOLIO", "QUEUE", "INTERACTION", "ROSTER"]


@dataclass
class AlibiConfig:
    ticket_similarity: float = 0.22
    ticket_window_h: int = 72
    queue_window_d: int = 7
    token_window_min: int = 45
    call_window_h: int = 24
    roster_grace_min: int = 30


class TicketMatcher:
    """TF-IDF (word + character n-grams) similarity between ticket text and an action."""

    def __init__(self, texts: list[str]):
        corpus = list(dict.fromkeys([*texts, *ACTION_DESC.values()]))
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                                   min_df=1).fit(corpus)
        self.desc = {k: self.vec.transform([v]) for k, v in ACTION_DESC.items()}

    def similarity(self, texts: pd.Series, actions: pd.Series) -> np.ndarray:
        out = np.zeros(len(texts))
        if len(texts) == 0:
            return out
        m = self.vec.transform(texts.fillna("").tolist())
        for action, d in self.desc.items():
            idx = np.where(actions.to_numpy() == action)[0]
            if len(idx):
                out[idx] = cosine_similarity(m[idx], d).ravel()
        return out


def _fmt(t: pd.Timestamp) -> str:
    return t.strftime("%d %b %H:%M")


def explain(f: Frames, cfg: AlibiConfig | None = None,
            exclude_work_items: set[str] | None = None,
            exclude_rosters: set[str] | None = None,
            only_access_ids: set[str] | None = None) -> pd.DataFrame:
    """Return one row per access with verdict, matched templates and every check made.

    `exclude_*` supports counterfactuals ("what if this ticket did not exist?").
    """
    cfg = cfg or AlibiConfig()
    a = f.access_event.copy()
    if only_access_ids is not None:
        a = a[a["id"].isin(only_access_ids)]
    a = a.merge(f.employee[["id", "branch_id"]].rename(columns={"id": "employee_id",
                                                                 "branch_id": "emp_branch"}),
                on="employee_id", how="left")
    w = f.work_item
    if exclude_work_items:
        w = w[~w["id"].isin(exclude_work_items)]
    ros = f.roster
    if exclude_rosters:
        ros = ros[~ros["id"].isin(exclude_rosters)]

    matcher = TicketMatcher(f.work_item.loc[f.work_item["kind"] == "TICKET", "text"].dropna().tolist())

    # candidate work items joined by customer OR account
    wi_cols = ["id", "kind", "ref", "customer_id", "account_id", "employee_id", "branch_id", "text",
               "created_at"]
    wk = w[wi_cols].rename(columns={"id": "wi_id", "employee_id": "wi_emp", "branch_id": "wi_branch",
                                    "customer_id": "wi_cust", "account_id": "wi_acct"})
    base = a[["id", "employee_id", "emp_branch", "action", "account_id", "customer_id", "occurred_at"]]
    by_cust = base.merge(wk, left_on="customer_id", right_on="wi_cust", how="inner")
    by_acct = base.merge(wk, left_on="account_id", right_on="wi_acct", how="inner")
    cand = pd.concat([by_cust, by_acct]).drop_duplicates(["id", "wi_id"])
    dt = (cand["occurred_at"] - cand["created_at"]).dt.total_seconds() / 60.0  # minutes, + = before

    # TICKET
    tk = cand[(cand["kind"] == "TICKET") & (dt >= -5) & (dt <= cfg.ticket_window_h * 60)
              & ((cand["wi_emp"] == cand["employee_id"]) | (cand["wi_branch"] == cand["emp_branch"]))].copy()
    tk["sim"] = matcher.similarity(tk["text"], tk["action"])
    tk["ok"] = np.where(tk["action"].isin(STATE_ACTIONS), tk["sim"] >= cfg.ticket_similarity, True)
    tk = tk.sort_values(["ok", "sim"], ascending=False).drop_duplicates("id")

    # QUEUE
    qu = cand[(cand["kind"] == "QUEUE") & (cand["wi_emp"] == cand["employee_id"])
              & (dt >= -10) & (dt <= cfg.queue_window_d * 1440)].drop_duplicates("id")

    # INTERACTION: token / eKYC at the employee's branch close in time, or a call-centre record
    near = (cand["kind"].isin(["TOKEN", "EKYC"]) & (dt.abs() <= cfg.token_window_min)
            & (cand["wi_branch"] == cand["emp_branch"]))
    call = (cand["kind"] == "CALL") & (dt >= 0) & (dt <= cfg.call_window_h * 60)
    it = cand[near | call].sort_values("created_at", ascending=False).drop_duplicates("id")

    # PORTFOLIO
    rm = f.customer.set_index("id")["rm_employee_id"]
    portfolio_ok = a["customer_id"].map(rm).eq(a["employee_id"]).fillna(False).to_numpy()

    # ROSTER (merge_asof per employee on shift start, with grace)
    grace = pd.Timedelta(minutes=cfg.roster_grace_min)
    left = a[["id", "employee_id", "occurred_at"]].assign(key=lambda d: d["occurred_at"] + grace)
    left = left.sort_values("key")
    right = ros[["id", "employee_id", "shift_start", "shift_end", "duty_type"]].rename(
        columns={"id": "roster_id"}).sort_values("shift_start")
    rj = pd.merge_asof(left, right, left_on="key", right_on="shift_start", by="employee_id",
                       direction="backward")
    rj["ok"] = rj["shift_end"].notna() & (rj["occurred_at"] <= rj["shift_end"] + grace)
    rj = rj.set_index("id")
    last_end = rj["shift_end"]

    tk_i, qu_i, it_i = tk.set_index("id"), qu.set_index("id"), it.set_index("id")
    rows = []
    for i, r in enumerate(a.itertuples(index=False)):
        checks, matches = [], []
        # ticket
        if r.id in tk_i.index:
            t = tk_i.loc[r.id]
            note = f"{t['ref']} · “{t['text'][:70]}” · similarity {t['sim']:.2f}"
            ok = bool(t["ok"])
            if not ok:
                note += " (below threshold — ticket is not about this action)"
            checks.append({"template": "TICKET", "ok": ok, "ref": t["ref"], "work_item": t["wi_id"],
                           "at": t["created_at"].isoformat(), "similarity": round(float(t["sim"]), 3),
                           "note": note})
        else:
            checks.append({"template": "TICKET", "ok": False,
                           "note": f"No ticket for this customer in the {cfg.ticket_window_h} h before"})
        # portfolio
        checks.append({"template": "PORTFOLIO", "ok": bool(portfolio_ok[i]),
                       "note": "Customer is in this employee's portfolio" if portfolio_ok[i]
                       else "Customer is not in this employee's portfolio"})
        # queue
        if r.id in qu_i.index:
            q = qu_i.loc[r.id]
            checks.append({"template": "QUEUE", "ok": True, "ref": q["ref"], "work_item": q["wi_id"],
                           "at": q["created_at"].isoformat(), "note": f"{q['ref']} · {q['text']}"})
        else:
            checks.append({"template": "QUEUE", "ok": False, "note": "No queue item assigned for this account"})
        # interaction
        if r.id in it_i.index:
            x = it_i.loc[r.id]
            checks.append({"template": "INTERACTION", "ok": True, "ref": x["ref"], "work_item": x["wi_id"],
                           "at": x["created_at"].isoformat(),
                           "note": f"{x['ref']} · {x['text']} at {_fmt(x['created_at'])}"})
        else:
            checks.append({"template": "INTERACTION", "ok": False,
                           "note": "No branch token, eKYC or call-centre record for this customer nearby"})
        # roster
        if r.id in rj.index and bool(rj.at[r.id, "ok"]):
            s = rj.loc[r.id]
            checks.append({"template": "ROSTER", "ok": True, "ref": s["roster_id"],
                           "note": f"{s['duty_type'].title()} shift {s['shift_start']:%H:%M}–{s['shift_end']:%H:%M}"})
        else:
            le = last_end.get(r.id) if r.id in last_end.index else None
            note = "No rostered shift covers this time"
            if le is not None and pd.notna(le):
                note += f" (last shift ended {_fmt(le)})"
            checks.append({"template": "ROSTER", "ok": False, "note": note})

        purpose_ok = any(c["ok"] for c in checks[:4])
        timing_ok = checks[4]["ok"]
        verdict = "EXPLAINED" if purpose_ok and timing_ok else "PARTIAL" if (purpose_ok or timing_ok) else "UNEXPLAINED"
        matches = [c for c in checks if c["ok"]]
        rows.append((r.id, r.employee_id, verdict, purpose_ok, timing_ok, matches, checks, r.occurred_at))

    return pd.DataFrame(rows, columns=["access_event_id", "employee_id", "verdict", "purpose_ok",
                                       "timing_ok", "matches", "checked", "occurred_at"])
