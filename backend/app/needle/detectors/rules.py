"""Rule detectors R1–R10. Cheap, high-recall, readable. Each returns signal dicts."""

from __future__ import annotations

import pandas as pd

from app.loom.frames import Frames
from app.needle.registry import DETECTORS

OUTFLOW_CHANNELS = {"IMPS", "UPI", "NEFT", "RTGS"}
SENSITIVE = {"ACCT_VIEW", "MOBILE_UPDATE", "LIMIT_CHANGE", "ADDRESS_UPDATE", "CARD_ISSUE",
             "KYC_APPROVE", "ACCT_OPEN", "CUST_SEARCH"}


def signal(code: str, entities, events, start, end, strength: float, summary: str, **payload) -> dict:
    d = DETECTORS[code]
    return {"detector": code, "family": d.family, "version": d.version,
            "entity_refs": sorted({e for e in entities if isinstance(e, str) and e}),
            "event_refs": [e for e in dict.fromkeys(events) if isinstance(e, str)],
            "window_start": start, "window_end": end, "strength": round(float(strength), 3),
            "summary": summary, "payload": payload}


def rupees(x: float) -> str:
    x = float(x)
    if x >= 1e5:
        return f"₹{x / 1e5:.2f} L".replace(".00 L", " L")
    return f"₹{x:,.0f}"


# ── helpers ────────────────────────────────────────────────────────────────


def limit_at(f: Frames) -> callable:
    """Per-transaction limit in force for an account at time t (from the change history)."""
    ch = f.state_change[f.state_change["field"] == "TXN_LIMIT"].sort_values("occurred_at")
    hist = {a: list(zip(g["occurred_at"], g["old_value"].astype(float), g["new_value"].astype(float), strict=True))
            for a, g in ch.groupby("account_id")}
    current = f.account.set_index("id")["daily_limit_paise"].to_dict()

    def lookup(acct: str, t: pd.Timestamp) -> float:
        h = hist.get(acct)
        if not h:
            return current.get(acct, 0) / 100.0
        val = h[0][1]
        for ts, _old, new in h:
            if ts <= t:
                val = new
        return val / 100.0

    return lookup


# ── R1 structuring ─────────────────────────────────────────────────────────


def r1_structuring(f: Frames, cluster: dict[str, str]) -> list[dict]:
    p = DETECTORS["R1"].params
    acct_cust = f.account.set_index("id")["customer_id"]
    dep = f.txn[(f.txn["kind"] == "CASH_DEPOSIT") & f.txn["amount"].between(p["band_min"], p["band_max"])].copy()
    dep["customer_id"] = dep["to_account"].map(acct_cust)
    dep["person"] = dep["customer_id"].map(cluster)
    out = []
    win = pd.Timedelta(hours=p["window_h"])
    for person, g in dep.groupby("person"):
        g = g.sort_values("occurred_at")
        times = g["occurred_at"].tolist()
        best = None
        for i in range(len(g)):
            w = g[(g["occurred_at"] >= times[i]) & (g["occurred_at"] <= times[i] + win)]
            spread = w["to_account"].nunique() >= 2 or w["branch_id"].nunique() >= 2
            if len(w) >= p["min_count"] and spread and (best is None or len(w) > len(best)):
                best = w
        if best is not None:
            out.append(signal(
                "R1", [person, *best["to_account"], *best["customer_id"]], best["id"],
                best["occurred_at"].min(), best["occurred_at"].max(), min(1.0, len(best) / 6),
                f"{len(best)} cash deposits of {rupees(best['amount'].min())}–{rupees(best['amount'].max())} "
                f"across {best['branch_id'].nunique()} branches and {best['to_account'].nunique()} accounts "
                f"of one resolved person in {(best['occurred_at'].max() - best['occurred_at'].min()).total_seconds() / 3600:.0f} h",
                person=person, accounts=sorted(best["to_account"].unique()),
                branches=sorted(best["branch_id"].dropna().unique()), total=float(best["amount"].sum())))
    return out


# ── R2 limit-hugging ───────────────────────────────────────────────────────


def r2_limit_hugging(f: Frames) -> list[dict]:
    p = DETECTORS["R2"].params
    lookup = limit_at(f)
    internal = set(f.account.loc[f.account["kind"] != "EXTERNAL", "id"])
    t = f.txn[f.txn["channel"].isin(OUTFLOW_CHANNELS) & f.txn["from_account"].isin(internal)].copy()
    t = t[t["amount"] >= 20_000]
    t["limit"] = [lookup(a, ts) for a, ts in zip(t["from_account"], t["occurred_at"], strict=True)]
    t = t[(t["limit"] > 0) & (t["amount"] >= p["ratio"] * t["limit"]) & (t["amount"] <= t["limit"] * 1.0001)]
    out = []
    for acct, g in t.groupby("from_account"):
        g = g.sort_values("occurred_at")
        for i in range(len(g)):
            w = g[(g["occurred_at"] >= g["occurred_at"].iloc[i])
                  & (g["occurred_at"] <= g["occurred_at"].iloc[i] + pd.Timedelta(minutes=p["window_min"]))]
            if len(w) >= p["min_count"]:
                out.append(signal(
                    "R2", [acct, *w["to_account"]], w["id"], w["occurred_at"].min(), w["occurred_at"].max(),
                    min(1.0, len(w) / 3),
                    f"{len(w)} transfers at {w['amount'].div(w['limit']).min():.0%}–{w['amount'].div(w['limit']).max():.0%} "
                    f"of the {rupees(w['limit'].iloc[0])} per-transaction limit within "
                    f"{(w['occurred_at'].max() - w['occurred_at'].min()).total_seconds() / 60:.0f} min",
                    account=acct, limit=float(w["limit"].iloc[0]), amounts=w["amount"].tolist()))
                break
    return out


# ── R3 dormant reactivation ────────────────────────────────────────────────


def r3_dormant(f: Frames) -> list[dict]:
    months = DETECTORS["R3"].params["inactive_months"]
    dormant = f.account[(f.account["status"] == "INOPERATIVE") & f.account["status_since"].notna()]
    out = []
    for a in dormant.itertuples(index=False):
        debits = f.txn[(f.txn["from_account"] == a.id)].sort_values("occurred_at")
        if debits.empty:
            continue
        first = debits.iloc[0]
        inactive = (first["occurred_at"] - a.status_since).days / 30.44
        if inactive >= months:
            out.append(signal("R3", [a.id, a.customer_id], [first["id"]], first["occurred_at"],
                              first["occurred_at"], 1.0,
                              f"First debit after {inactive:.0f} months of inactivity "
                              f"({rupees(first['amount'])} on {first['occurred_at']:%d %b %H:%M})",
                              account=a.id, inactive_months=round(inactive, 1)))
    return out


# ── R4 contact change → payee → payout ─────────────────────────────────────


def r4_contact_payout(f: Frames) -> list[dict]:
    win = pd.Timedelta(hours=DETECTORS["R4"].params["window_h"])
    ch = f.state_change[f.state_change["field"].isin(["REGISTERED_MOBILE", "PASSWORD", "EMAIL"])]
    accts = set(ch["account_id"])
    ben_by = {a: g for a, g in f.beneficiary[f.beneficiary["account_id"].isin(accts)].groupby("account_id")}
    tx = f.txn[f.txn["channel"].isin(OUTFLOW_CHANNELS) & f.txn["from_account"].isin(accts)]
    tx_by = {a: g for a, g in tx.groupby("from_account")}
    out = []
    empty = f.beneficiary.iloc[0:0]
    for c in ch.itertuples(index=False):
        ben = ben_by.get(c.account_id, empty)
        b = ben[(ben["added_at"] > c.occurred_at) & (ben["added_at"] <= c.occurred_at + win)]
        if b.empty:
            continue
        tx_a = tx_by.get(c.account_id)
        if tx_a is None:
            continue
        p = tx_a[tx_a["to_account"].isin(b["counterparty_account"])
                 & (tx_a["occurred_at"] > c.occurred_at) & (tx_a["occurred_at"] <= c.occurred_at + win)]
        if p.empty:
            continue
        mins = (p["occurred_at"].min() - c.occurred_at).total_seconds() / 60
        out.append(signal("R4", [c.account_id, c.actor_id, *b["counterparty_account"]],
                          [c.id, *b["id"], *p["id"]], c.occurred_at, p["occurred_at"].max(),
                          min(1.0, 60 / max(mins, 1) + 0.3),
                          f"{c.field.replace('_', ' ').lower()} changed, {len(b)} new payee(s), "
                          f"{rupees(p['amount'].sum())} paid to them {mins:.0f} min later",
                          account=c.account_id, change_id=c.id, minutes=round(mins, 1)))
    return out


# ── R5 / R6 from Alibi, R7 overrides ───────────────────────────────────────


def r5_r6_from_alibi(f: Frames, ex: pd.DataFrame) -> list[dict]:
    a = f.access_event.set_index("id")
    e = ex.set_index("access_event_id")
    out = []
    off = e[~e["timing_ok"]]
    off = off.join(a[["session_id", "action", "account_id"]])
    off = off[off["action"].isin(SENSITIVE)]
    for sid, g in off.groupby("session_id"):
        emp = g["employee_id"].iloc[0]
        out.append(signal("R5", [emp, *g["account_id"].dropna()], g.index, g["occurred_at"].min(),
                          g["occurred_at"].max(), 0.6,
                          f"{len(g)} sensitive action(s) outside any rostered shift", session=sid))
    nop = e[~e["purpose_ok"]].join(a[["session_id", "action", "account_id", "customer_id"]])
    nop = nop[nop["action"].isin(SENSITIVE)]
    for aid, r in nop.iterrows():
        out.append(signal("R6", [r["employee_id"], r["account_id"], r["customer_id"]], [aid],
                          r["occurred_at"], r["occurred_at"], 0.4,
                          f"{r['action'].replace('_', ' ').lower()} with no ticket, portfolio, queue or interaction",
                          access=aid))
    return out


def r7_override(f: Frames) -> list[dict]:
    a = f.access_event[f.access_event["override_used"]]
    return [signal("R7", [r.employee_id, r.account_id], [r.id], r.occurred_at, r.occurred_at, 0.7,
                   f"{r.action.replace('_', ' ').lower()} performed with an override", access=r.id)
            for r in a.itertuples(index=False)]


# ── R8 SoD, R9 expired entitlements ────────────────────────────────────────


def active_entitlements(f: Frames, emp: str, t: pd.Timestamp) -> pd.DataFrame:
    e = f.entitlement[f.entitlement["employee_id"] == emp]
    return e[(e["valid_from"] <= t) & (e["revoked_at"].isna() | (e["revoked_at"] > t))]


def r8_sod(f: Frames) -> list[dict]:
    toxic = set(DETECTORS["R8"].params["toxic"])
    out = []
    ent = f.entitlement
    for emp, g in ent.groupby("employee_id"):
        if not toxic.issubset(set(g["permission_code"])):
            continue
        since = g[g["permission_code"].isin(toxic)]["valid_from"].max()
        out.append(signal("R8", [emp], g[g["permission_code"].isin(toxic)]["id"], since, since, 0.7,
                          "Holds a toxic combination: KYC approval + card issue + mobile override",
                          kind="toxic_combination", employee=emp))
    self_appr = f.account[(f.account["opened_by"].notna()) & (f.account["opened_by"] == f.account["kyc_approved_by"])
                          & (f.account["opened_at"] >= f.window_start - pd.Timedelta(days=90))]
    for emp, g in self_appr.groupby("opened_by"):
        out.append(signal("R8", [emp, *g["id"]], g["id"], g["opened_at"].min(), g["opened_at"].max(),
                          min(1.0, len(g) / 5),
                          f"Approved KYC for {len(g)} account(s) they opened themselves",
                          kind="self_approval", employee=emp, accounts=sorted(g["id"])))
    return out


def r9_expired(f: Frames) -> list[dict]:
    out = []
    ov = f.access_event[f.access_event["override_used"]]
    for r in ov.itertuples(index=False):
        ents = active_entitlements(f, r.employee_id, r.occurred_at)
        grant = ents[ents["permission_code"] == "MOBILE_UPDATE_OVERRIDE"]
        if grant.empty:
            continue
        g = grant.sort_values("valid_from").iloc[-1]
        if pd.notna(g["intended_expiry"]) and g["intended_expiry"] < r.occurred_at:
            days = (r.occurred_at - g["intended_expiry"]).days
            out.append(signal("R9", [r.employee_id, r.account_id], [r.id, g["id"]], g["valid_from"],
                              r.occurred_at, 0.9,
                              f"Override used {days} day(s) after the entitlement's intended expiry "
                              f"({g['request_ref']}, expired {g['intended_expiry']:%d %b})",
                              entitlement=g["id"], request_ref=g["request_ref"], access=r.id))
    return out


# ── R10 presence-less opening ──────────────────────────────────────────────


def r10_presence(f: Frames) -> list[dict]:
    win = pd.Timedelta(hours=DETECTORS["R10"].params["window_h"])
    opened = f.account[(f.account["kind"] != "EXTERNAL") & (f.account["opened_at"] >= f.window_start)]
    presence = f.work_item[f.work_item["kind"].isin(["TOKEN", "EKYC"])]
    by_cust = presence.groupby("customer_id")["created_at"].apply(list).to_dict()
    out = []
    for a in opened.itertuples(index=False):
        times = by_cust.get(a.customer_id, [])
        if any(abs(t - a.opened_at) <= win for t in times):
            continue
        out.append(signal("R10", [a.id, a.customer_id, a.opened_by, a.kyc_approved_by], [a.id],
                          a.opened_at, a.opened_at, 0.6,
                          f"Opened {a.opened_at:%d %b} with no branch token or biometric eKYC "
                          f"(mode {a.opening_mode})",
                          account=a.id, opened_by=a.opened_by, approver=a.kyc_approved_by))
    return out
