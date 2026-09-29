"""Evidence items: every claim in a brief points at one of these.

Grading (adapted from the intelligence convention of rating source and information apart):
  reliability  A system of record · B operational log · C derived by a SUTRA model · D LLM-extracted
  credibility  1 corroborated by an independent system · 2 consistent, not independently confirmed
               3 uncorroborated · 4 contradicted
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import orjson
import pandas as pd

from app.brief.context import BriefContext
from app.needle.chains import ChainDraft
from app.needle.detectors.rules import rupees


@dataclass
class EvidenceItem:
    kind: str
    summary: str
    source_system: str
    source_table: str
    source_ref: str
    reliability: str
    observed_at: pd.Timestamp
    ingested_at: pd.Timestamp | None
    entities: list[str]
    facts: dict = field(default_factory=dict)
    supports: list[str] = field(default_factory=lambda: ["claim"])
    rebuts: list[str] = field(default_factory=list)
    code: str = ""
    credibility: int = 2
    link_codes: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        body = orjson.dumps({"kind": self.kind, "source": [self.source_system, self.source_table, self.source_ref],
                             "observed_at": self.observed_at.isoformat(), "facts": self.facts},
                            option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS, default=str)
        return hashlib.sha256(body).hexdigest()


def _ts(x) -> pd.Timestamp:
    return pd.Timestamp(x)


class EvidenceBook:
    """Collects items for one chain, dedupes by source row, grades and numbers them."""

    def __init__(self) -> None:
        self.items: list[EvidenceItem] = []
        self._by_ref: dict[tuple[str, str, str], EvidenceItem] = {}

    def add(self, item: EvidenceItem, link_code: str | None = None) -> EvidenceItem:
        key = (item.source_table, item.source_ref, item.kind)
        if key in self._by_ref:
            existing = self._by_ref[key]
            if link_code and link_code not in existing.link_codes:
                existing.link_codes.append(link_code)
            return existing
        if link_code:
            item.link_codes.append(link_code)
        self._by_ref[key] = item
        self.items.append(item)
        return item

    def finalise(self) -> list[EvidenceItem]:
        self.items.sort(key=lambda e: (e.observed_at, e.reliability))
        for i, e in enumerate(self.items):
            e.code = f"EV-{101 + i}"
        systems_by_entity: dict[str, set[str]] = {}
        for e in self.items:
            if e.reliability in "AB":
                for ent in e.entities:
                    systems_by_entity.setdefault(ent, set()).add(e.source_system)
        for e in self.items:
            if e.reliability in "AB":
                others = set().union(*(systems_by_entity.get(ent, set()) for ent in e.entities)) - {e.source_system}
                e.credibility = 1 if others else 2
            elif e.reliability == "C":
                e.credibility = 2
            else:
                e.credibility = 3
        return self.items


# ── source-row → evidence converters ───────────────────────────────────────


def ev_entitlement(g) -> EvidenceItem:
    expired = pd.notna(g["intended_expiry"])
    return EvidenceItem(
        "ENTITLEMENT",
        f"{g['permission_code']} granted to {g['employee_id']} on {g['valid_from']:%d %b %H:%M} via "
        f"{g['request_ref'] or 'role baseline'} (“{g['reason']}”)"
        + (f"; intended expiry {g['intended_expiry']:%d %b %H:%M}; never revoked" if expired else ""),
        "IAM", "entitlement", g["id"], "A", _ts(g["valid_from"]), _ts(g["valid_from"]),
        [g["employee_id"]], {"permission": g["permission_code"], "request_ref": g["request_ref"],
                             "intended_expiry": str(g["intended_expiry"]), "revoked_at": str(g["revoked_at"])})


def ev_session(s, sid: str) -> EvidenceItem:
    system = {"VPN": "VPN gateway", "BRANCH": "Branch SSO", "NETBANKING": "Digital channel",
              "MOBILE": "Digital channel"}.get(s["channel"], "Session log")
    end = s["ended_at"]
    return EvidenceItem(
        "SESSION", f"{s['channel']} session {sid} by {s['actor_id']} from device {s['device_id']} "
        f"({s['geo_city']}), {s['started_at']:%d %b %H:%M}–{end:%H:%M}",
        system, "session", sid, "B", _ts(s["started_at"]), None, [s["actor_id"], s["device_id"]],
        {"channel": s["channel"], "device": s["device_id"], "geo": s["geo_city"], "ip": s["ip"]})


def ev_access(ae, acct_row) -> EvidenceItem:
    fields = ", ".join(ae["fields"]) if len(ae["fields"]) else "profile"
    status = acct_row["status"].lower() if acct_row is not None else ""
    bal = rupees(acct_row["balance_paise"] / 100) if acct_row is not None else ""
    return EvidenceItem(
        "ACCESS", f"{ae['employee_id']} {ae['action'].replace('_', ' ').lower()} on {ae['account_id'] or ae['customer_id']}"
        + (f" ({status}, balance {bal})" if status else "") + f" — fields: {fields}"
        + (" · override flag set" if ae["override_used"] else ""),
        "CBS app audit", "access_event", ae["id"], "B", _ts(ae["occurred_at"]), _ts(ae["ingested_at"]),
        [ae["employee_id"], ae["account_id"], ae["customer_id"]],
        {"action": ae["action"], "fields": list(ae["fields"]), "override": bool(ae["override_used"])})


def ev_alibi(access_id: str, card: dict, t) -> EvidenceItem:
    found = [c["template"].title() for c in card["checked"] if c["ok"]]
    missing = [c["note"] for c in card["checked"] if not c["ok"]]
    verdict = card["verdict"].lower()
    summary = (f"Alibi {verdict}: {len(found)} of 5 reasons found" + (f" ({', '.join(found)})" if found else "")
               + (". " + "; ".join(missing[:3]) if missing else ""))
    return EvidenceItem("ALIBI", summary, "SUTRA Alibi", "explanation", access_id, "C", _ts(t), None, [],
                        {"verdict": card["verdict"], "checked": card["checked"]})


def ev_roster(emp: str, card: dict, t) -> EvidenceItem | None:
    roster = next((c for c in card["checked"] if c["template"] == "ROSTER"), None)
    if roster is None:
        return None
    return EvidenceItem("ROSTER", f"Roster for {emp}: {roster['note']}", "HRMS", "roster",
                        roster.get("ref") or f"{emp}:{pd.Timestamp(t):%Y-%m-%d}", "A", _ts(t), None, [emp],
                        {"on_duty": roster["ok"], "note": roster["note"]},
                        supports=[] if roster["ok"] else ["claim"], rebuts=["claim"] if roster["ok"] else [])


def ev_state_change(c) -> EvidenceItem:
    if c["field"] == "REGISTERED_MOBILE":
        what = f"Registered mobile changed {c['old_value']} → {c['new_value']}"
    elif c["field"] == "TXN_LIMIT":
        what = f"Per-transaction limit changed {rupees(float(c['old_value']) / 100)} → {rupees(float(c['new_value']) / 100)}"
    elif c["field"] == "PASSWORD":
        what = "Net-banking password reset"
    else:
        what = f"{c['field'].replace('_', ' ').title()} changed"
    auth = {"OVERRIDE": "with an override — no OTP to the old number",
            "OTP_NEW_NUMBER": "via OTP sent to the new number", "BIOMETRIC": "with biometric eKYC",
            "OTP_OLD_NUMBER": "with OTP to the old number", "OTP_REGISTERED": "via OTP to the registered number",
            "MAKER_CHECKER": "maker-checker"}.get(c["auth_method"], c["auth_method"])
    system = "CBS" if c["actor_type"] == "EMPLOYEE" else "Digital channel"
    return EvidenceItem("STATE_CHANGE", f"{what} on {c['account_id']} by {c['actor_id']} {auth}", system,
                        "state_change", c["id"], "A", _ts(c["occurred_at"]), _ts(c["ingested_at"]),
                        [c["account_id"], c["actor_id"]],
                        {"field": c["field"], "old": c["old_value"], "new": c["new_value"], "auth": c["auth_method"]})


def ev_beneficiary(b, holder: str, bank: str) -> EvidenceItem:
    return EvidenceItem("BENEFICIARY", f"Payee {b['counterparty_account']} ({holder}, {bank}) added to "
                        f"{b['account_id']} at {b['added_at']:%d %b %H:%M:%S}", "Digital channel", "beneficiary",
                        b["id"], "A", _ts(b["added_at"]), None, [b["account_id"], b["counterparty_account"]],
                        {"payee": b["counterparty_account"], "holder": holder, "session": b["session_id"]})


def ev_txn(t, holder_to: str) -> EvidenceItem:
    system = "ATM switch" if t["to_account"] == "X-ATM" else "Payments switch" if t["channel"] in (
        "IMPS", "UPI", "NEFT", "RTGS") else "CBS"
    return EvidenceItem("TXN", f"{rupees(t['amount'])} {t['channel']} {t['from_account']} → {t['to_account']} "
                        f"({holder_to}) at {t['occurred_at']:%d %b %H:%M:%S}", system, "txn", t["id"], "A",
                        _ts(t["occurred_at"]), _ts(t["ingested_at"]), [t["from_account"], t["to_account"]],
                        {"amount": float(t["amount"]), "channel": t["channel"], "narration": t["narration"]})


def ev_account_opening(a, aid: str) -> EvidenceItem:
    return EvidenceItem("ACCOUNT_OPENING", f"{aid} opened {a['opened_at']:%d %b %Y} by {a['opened_by']}; KYC approved by "
                        f"{a['kyc_approved_by']} (mode {a['opening_mode']})", "CBS", "account", aid, "A",
                        _ts(a["opened_at"]), None, [aid, a["opened_by"], a["kyc_approved_by"]],
                        {"opened_by": a["opened_by"], "approver": a["kyc_approved_by"], "mode": a["opening_mode"]})


def ev_model(kind: str, summary: str, ref: str, t, entities: list[str], facts: dict,
             rebut: bool = False) -> EvidenceItem:
    return EvidenceItem(kind, summary, "SUTRA models", kind.lower(), ref, "C", _ts(t), None, entities, facts,
                        supports=[] if rebut else ["claim"], rebuts=["claim"] if rebut else [])


def ev_er(link: dict, t) -> EvidenceItem:
    f = link["fields"]
    return EvidenceItem("ENTITY_MATCH", f"{link['customer_id']}'s registered address matches {link['employee_id']}'s HR "
                        f"record (address {f['address']}; surname {f['surname']}; phone {f['phone']}) · score {link['score']}",
                        "SUTRA entity resolution", "relationship", f"{link['employee_id']}~{link['customer_id']}", "C",
                        _ts(t), None, [link["employee_id"], link["customer_id"]], link)


def build_chain_evidence(ctx: BriefContext, d: ChainDraft) -> EvidenceBook:
    ix, f = ctx.ix, ctx.f
    book = EvidenceBook()
    ent = f.entitlement.set_index("id")
    ae = f.access_event.set_index("id")
    sc = f.state_change.set_index("id")
    ben = f.beneficiary.set_index("id")
    tx = f.txn.set_index("id")

    for link in d.links:
        for ref in link.refs:
            if ref in ent.index:
                book.add(ev_entitlement(ent.loc[ref].to_dict() | {"id": ref}), link.code)
            elif ref in ix.sess.index:
                book.add(ev_session(ix.sess.loc[ref], ref), link.code)
            elif ref in ae.index:
                row = ae.loc[ref].to_dict() | {"id": ref}
                acct = ix.acc.loc[row["account_id"]] if row["account_id"] in ix.acc.index else None
                book.add(ev_access(row, acct), link.code)
            elif ref in sc.index:
                book.add(ev_state_change(sc.loc[ref].to_dict() | {"id": ref}), link.code)
            elif ref in ben.index:
                b = ben.loc[ref].to_dict() | {"id": ref}
                cp = b["counterparty_account"]
                bank = ix.acc.at[cp, "bank_name"] if cp in ix.acc.index else ""
                book.add(ev_beneficiary(b, ix.holder(cp), bank), link.code)
            elif ref in tx.index:
                t = tx.loc[ref].to_dict() | {"id": ref}
                book.add(ev_txn(t, ix.holder(t["to_account"])), link.code)
            elif ref in ix.acc.index and d.kind == "MULE_FACTORY":
                book.add(ev_account_opening(ix.acc.loc[ref], ref), link.code)
        if link.alibi and link.event_type in ("ACCESS", "STATE_CHANGE", "SESSION"):
            aid = next((r for r in link.refs if r in ae.index), link.event_id)
            if link.event_type != "SESSION":
                book.add(ev_alibi(aid, link.alibi, link.t), link.code)
            r = ev_roster(d.employee_id or "", link.alibi, link.t)
            if r is not None:
                book.add(r, link.code)
    return book
