"""Feature definitions for M5 (chain classifier) and M6 (mule-likeness)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.loom.frames import Frames

CHAIN_FEATURES = [
    "log_latency", "override", "purpose_explained", "timing_explained", "new_device",
    "password_reset", "n_new_payees", "limit_ratio", "amount_to_balance", "pass_through",
    "dormant", "recipients_approved_by_employee", "loop", "expired_entitlement", "night",
]

CHAIN_LABELS = {
    "log_latency": "Access-to-money latency",
    "override": "Override used",
    "purpose_explained": "Purpose explained by Alibi",
    "timing_explained": "Timing explained by roster",
    "new_device": "Payout from a never-seen device",
    "password_reset": "Password reset before payout",
    "n_new_payees": "New payees added",
    "limit_ratio": "Payout as share of limit",
    "amount_to_balance": "Share of balance moved",
    "pass_through": "Share forwarded downstream",
    "dormant": "Dormant account",
    "recipients_approved_by_employee": "Recipients KYC-approved by same employee",
    "loop": "Money looped back",
    "expired_entitlement": "Expired entitlement used",
    "night": "Night-time activity",
}


def chain_row(features: dict) -> dict:
    row = {k: float(features.get(k, 0.0)) for k in CHAIN_FEATURES}
    row["log_latency"] = float(np.log1p(max(features.get("latency_min", 0.0), 0.0)))
    return row


MULE_FEATURES = ["age_days", "presenceless", "self_approved", "n_senders", "log_inflow",
                 "pass_through_share", "atm_share", "device_shared", "phone_shared", "retention"]

MULE_LABELS = {
    "age_days": "Account age (days)", "presenceless": "Opened without customer present",
    "self_approved": "Opener approved own KYC", "n_senders": "Distinct senders",
    "log_inflow": "Inflow volume", "pass_through_share": "Inflow moved on within 60 min",
    "atm_share": "Share cashed out at ATMs", "device_shared": "Device shared with other customers",
    "phone_shared": "Phone shared with other customers", "retention": "Balance kept",
}


def mule_frame(f: Frames) -> pd.DataFrame:
    acc = f.account[f.account["kind"] != "EXTERNAL"].set_index("id")
    end = f.window_end
    t = f.txn
    cash = {"X-CASH", "X-ATM"}
    inflow = t[t["to_account"].isin(acc.index) & ~t["from_account"].isin(cash)]
    outflow = t[t["from_account"].isin(acc.index)]
    n_send = inflow.groupby("to_account")["from_account"].nunique()
    in_amt = inflow.groupby("to_account")["amount"].sum()
    out_amt = outflow.groupby("from_account")["amount"].sum()
    atm_amt = outflow[outflow["to_account"] == "X-ATM"].groupby("from_account")["amount"].sum()

    # pass-through: share of inflow amount matched by outflow within 60 min
    pt = pd.Series(0.0, index=acc.index)
    big_in = inflow[inflow["amount"] >= 10_000]
    out_sorted = {a: (g["occurred_at"].array.asi8, g["amount"].to_numpy().cumsum())
                  for a, g in outflow.sort_values("occurred_at").groupby("from_account")}
    moved = {}
    for r in big_in.itertuples(index=False):
        ob = out_sorted.get(r.to_account)
        if ob is None:
            continue
        times, cs = ob
        lo = np.searchsorted(times, r.occurred_at.value, side="right")
        hi = np.searchsorted(times, r.occurred_at.value + 3_600_000_000_000, side="right")
        if hi > lo:
            m = cs[hi - 1] - (cs[lo - 1] if lo > 0 else 0)
            moved[r.to_account] = moved.get(r.to_account, 0.0) + min(m, r.amount)
    for a, m in moved.items():
        pt[a] = m / max(in_amt.get(a, 1.0), 1.0)

    cs = f.session[(f.session["actor_type"] == "CUSTOMER") & f.session["device_id"].notna()]
    dev_users = cs.groupby("device_id")["actor_id"].nunique()
    cust_dev_shared = cs.assign(n=cs["device_id"].map(dev_users)).groupby("actor_id")["n"].max() > 1
    phone_n = f.customer.groupby("phone_tok")["id"].transform("count")
    phone_shared = pd.Series((phone_n > 1).to_numpy(), index=f.customer["id"])

    presence = f.work_item[f.work_item["kind"].isin(["TOKEN", "EKYC"])].groupby("customer_id")["created_at"].apply(list)

    def presenceless(opened_at, customer_id) -> float:
        if pd.isna(opened_at) or opened_at < f.window_start:
            return 0.0
        times = presence.get(customer_id, [])
        return float(not any(abs(x - opened_at) <= pd.Timedelta(hours=24) for x in times))

    rows = []
    for aid, a in acc.iterrows():
        rows.append({
            "account_id": aid,
            "age_days": float((end - a["opened_at"]).days) if pd.notna(a["opened_at"]) else 5000.0,
            "presenceless": presenceless(a["opened_at"], a["customer_id"]),
            "self_approved": float(pd.notna(a["opened_by"]) and a["opened_by"] == a["kyc_approved_by"]),
            "n_senders": float(n_send.get(aid, 0)),
            "log_inflow": float(np.log1p(in_amt.get(aid, 0.0))),
            "pass_through_share": float(min(pt.get(aid, 0.0), 1.5)),
            "atm_share": float(atm_amt.get(aid, 0.0) / max(out_amt.get(aid, 0.0), 1.0)),
            "device_shared": float(bool(cust_dev_shared.get(a["customer_id"], False))),
            "phone_shared": float(bool(phone_shared.get(a["customer_id"], False))),
            "retention": float(max(0.0, 1 - out_amt.get(aid, 0.0) / max(in_amt.get(aid, 0.0), 1.0))),
        })
    return pd.DataFrame(rows).set_index("account_id")
