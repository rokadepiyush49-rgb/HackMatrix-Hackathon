"""Mend — counterfactual control simulation.

For a chain, which control would have broken it, how early, how much money would it have
saved, and what would it have cost legitimate operations over the last 90 days?
Friction is measured on the same synthetic history, never guessed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from app.loom.frames import Frames


@dataclass(frozen=True)
class Control:
    id: str
    name: str
    description: str
    breaks_at: str  # chain link code where it bites
    effort: str  # Low | Medium | High
    kinds: tuple[str, ...]


CONTROLS: list[Control] = [
    Control("C1", "Expire temporary entitlements automatically",
            "Temporary grants lapse at their intended expiry; no manual revocation needed.", "E0", "Low",
            ("INSIDER_ATO",)),
    Control("C2", "Maker-checker for registered-mobile changes",
            "A second staff member approves every change of a customer's registered mobile.", "E3", "Medium",
            ("INSIDER_ATO",)),
    Control("C3", "Block mobile override without biometric",
            "Overrides require a biometric eKYC of the customer at the counter.", "E3", "Low", ("INSIDER_ATO",)),
    Control("C4", "After-hours step-up approval",
            "Sensitive changes outside a rostered shift need a manager's approval.", "E3", "Medium", ("INSIDER_ATO",)),
    Control("C5", "24 h cooling-off for new payees after a contact change",
            "Payments to payees added within 24 h of a mobile/password change are held for 24 h and "
            "the old number is notified.", "E5", "Medium", ("INSIDER_ATO", "EXTERNAL_ATO")),
    Control("C6", "Dormant-account reactivation needs a branch visit",
            "The first debit after 24 months of inactivity requires the customer in person.", "E5", "Low",
            ("INSIDER_ATO",)),
    Control("C7", "Raised limits take effect after 12 h",
            "A higher per-transaction limit becomes usable only 12 hours after it is set.", "E5", "Low",
            ("INSIDER_ATO",)),
    Control("C8", "Opener cannot approve their own KYC",
            "The employee who opens an account cannot also approve its KYC.", "F1", "Low", ("MULE_FACTORY",)),
]
BY_ID = {c.id: c for c in CONTROLS}


def friction(f: Frames, chain_refs: set[str], alibi: pd.DataFrame) -> dict[str, dict]:
    """Legitimate operations each control would have touched in the window (excluding flagged chains)."""
    days = max((f.window_end - f.window_start).days, 1)
    sc = f.state_change[~f.state_change["id"].isin(chain_refs)]
    emp_sc = sc[sc["actor_type"] == "EMPLOYEE"]
    total_sensitive = max(len(emp_sc), 1)
    mob = emp_sc[emp_sc["field"] == "REGISTERED_MOBILE"]
    overrides = emp_sc[emp_sc["auth_method"] == "OVERRIDE"]
    ae = f.access_event[~f.access_event["id"].isin(chain_refs)]
    ex = alibi.set_index("access_event_id")
    sens = ae[ae["action"].isin(["MOBILE_UPDATE", "LIMIT_CHANGE", "ADDRESS_UPDATE"])]
    off = sens[sens["id"].isin(ex.index[~ex["timing_ok"]])]

    # expired-entitlement uses outside flagged chains
    ent = f.entitlement[f.entitlement["intended_expiry"].notna()]
    expired_uses = 0
    for g in ent.itertuples(index=False):
        uses = ae[(ae["employee_id"] == g.employee_id) & ae["override_used"] & (ae["occurred_at"] > g.intended_expiry)]
        expired_uses += len(uses)

    # payments to new payees within 24 h of a contact change
    contact = sc[sc["field"].isin(["REGISTERED_MOBILE", "PASSWORD"])]
    ben = f.beneficiary
    tx = f.txn[~f.txn["id"].isin(chain_refs)]
    cooled = 0
    for c in contact.itertuples(index=False):
        b = ben[(ben["account_id"] == c.account_id) & (ben["added_at"] > c.occurred_at)
                & (ben["added_at"] <= c.occurred_at + pd.Timedelta(hours=24))]
        if len(b):
            cooled += int(tx[(tx["from_account"] == c.account_id) & tx["to_account"].isin(b["counterparty_account"])
                             & (tx["occurred_at"] <= c.occurred_at + pd.Timedelta(hours=48))].shape[0])

    dormant = f.account[f.account["status"] == "INOPERATIVE"]["id"]
    reactivations = int(tx[tx["from_account"].isin(dormant)]["from_account"].nunique())

    lim = sc[sc["field"] == "TXN_LIMIT"]
    fast = 0
    for c in lim.itertuples(index=False):
        fast += int(tx[(tx["from_account"] == c.account_id) & (tx["occurred_at"] > c.occurred_at)
                       & (tx["occurred_at"] <= c.occurred_at + pd.Timedelta(hours=12))
                       & (tx["amount"] >= float(c.old_value) / 100)].shape[0])

    self_appr = int(((f.account["opened_by"] == f.account["kyc_approved_by"]) & f.account["opened_by"].notna()
                     & (f.account["opened_at"] >= f.window_start) & ~f.account["id"].isin(chain_refs)).sum())

    def row(n: int, approvals_per_day: float, delay: str) -> dict:
        return {"legit_ops_affected": int(n), "share_of_sensitive_ops": round(n / total_sensitive, 4),
                "extra_approvals_per_day": round(approvals_per_day, 2), "customer_delay": delay}

    return {
        "C1": row(expired_uses, 0.0, "none"),
        "C2": row(len(mob), len(mob) / days, "~4 min per change while a checker approves"),
        "C3": row(len(overrides), 0.0, "customer must complete biometric eKYC"),
        "C4": row(len(off), len(off) / days, "waits for a manager's approval"),
        "C5": row(cooled, 0.0, "payment held 24 h"),
        "C6": row(reactivations, 0.0, "one branch visit"),
        "C7": row(fast, 0.0, "large payment waits up to 12 h"),
        "C8": row(self_appr, self_appr / days, "a second approver signs the KYC"),
    }


def applies(control: Control, chain: dict, links: list[dict]) -> dict | None:
    """Would this control have broken this chain? Returns where and when, or None."""
    feats = chain.get("features", {})
    codes = {lk["code"]: lk for lk in links}
    kind = chain["kind"]
    if kind not in control.kinds:
        return None
    if control.id == "C1" and feats.get("expired_entitlement") and "E0" in codes:
        e0 = codes["E0"]
        return {"link": "E0", "at": e0.get("expiry") or e0["t"], "why": "The override would have lapsed at its intended expiry"}
    if control.id == "C2" and "E3" in codes and "mobile" in codes["E3"]["title"].lower():
        return {"link": "E3", "at": codes["E3"]["t"], "why": "The mobile change would have waited for a second approver"}
    if control.id == "C3" and feats.get("override") and "E3" in codes:
        return {"link": "E3", "at": codes["E3"]["t"], "why": "The override would have demanded the customer's biometric"}
    if control.id == "C4" and not feats.get("timing_explained", 1) and "E3" in codes:
        return {"link": "E3", "at": codes["E3"]["t"], "why": "An after-hours change would have needed a manager"}
    if control.id == "C5" and "E5" in codes and feats.get("n_new_payees", 0) > 0:
        return {"link": "E5", "at": codes["E5"]["t"], "why": "Payments to the new payees would have been held for 24 h"}
    if control.id == "C6" and feats.get("dormant") and "E5" in codes:
        return {"link": "E5", "at": codes["E5"]["t"], "why": "The dormant account's first debit would have needed a branch visit"}
    if control.id == "C7" and "E3′" in codes and "E5" in codes:
        t3, t5 = pd.Timestamp(codes["E3′"]["t"]), pd.Timestamp(codes["E5"]["t"])
        if (t5 - t3) < pd.Timedelta(hours=12):
            return {"link": "E5", "at": codes["E5"]["t"], "why": "The raised limit would not yet have been usable"}
    if control.id == "C8" and kind == "MULE_FACTORY":
        first = next((lk for lk in links if lk["code"] == "F1"), None)
        if first:
            return {"link": "F1", "at": first["t"], "why": "The same employee could not have approved these openings"}
    return None


def simulate(chain: dict, links: list[dict], selected: list[str], fr: dict[str, dict]) -> dict:
    payout = next((lk for lk in links if lk["code"] in ("E5", "F5", "F4")), None)
    payout_t = pd.Timestamp(payout["t"]) if payout else None
    per_control = []
    for c in CONTROLS:
        hit = applies(c, chain, links)
        lead = None
        if hit and payout_t is not None:
            lead = (payout_t - pd.Timestamp(hit["at"])).total_seconds()
        per_control.append({**asdict(c), "kinds": list(c.kinds), "applicable": chain["kind"] in c.kinds,
                            "breaks": bool(hit), "hit": hit, "lead_time_s": lead,
                            "prevented": chain["amount_at_risk"] if hit else 0.0,
                            "friction": fr.get(c.id, {})})
    chosen = [p for p in per_control if p["id"] in selected]
    breaking = [p for p in chosen if p["breaks"]]
    earliest = min(breaking, key=lambda p: pd.Timestamp(p["hit"]["at"])) if breaking else None
    candidates = [p for p in per_control if p["breaks"]]
    effort_rank = {"Low": 0, "Medium": 1, "High": 2}
    rec = min(candidates, key=lambda p: (p["friction"].get("legit_ops_affected", 1e9), effort_rank[p["effort"]],
                                         -(p["lead_time_s"] or 0))) if candidates else None
    return {
        "chain_id": chain["id"], "amount_at_risk": chain["amount_at_risk"],
        "controls": per_control,
        "selected": selected,
        "result": {
            "breaks": bool(earliest),
            "broken_at": earliest["hit"] if earliest else None,
            "prevented": chain["amount_at_risk"] if earliest else 0.0,
            "lead_time_s": earliest["lead_time_s"] if earliest else None,
            "legit_ops_affected": sum(p["friction"].get("legit_ops_affected", 0) for p in chosen),
            "extra_approvals_per_day": round(sum(p["friction"].get("extra_approvals_per_day", 0) for p in chosen), 2),
        },
        "recommended": {"id": rec["id"], "name": rec["name"], "lead_time_s": rec["lead_time_s"],
                        "legit_ops_affected": rec["friction"].get("legit_ops_affected"),
                        "why": rec["hit"]["why"]} if rec else None,
        "note": "Friction is measured on the synthetic 90-day history.",
    }
