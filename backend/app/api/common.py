"""Shared helpers for API routers: serialisation, pseudonymisation, lookups."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.loom.models import (
    Account,
    Alert,
    Chain,
    ChainLink,
    Employee,
    Evidence,
    ScenarioRun,
    UnmaskRequest,
)

PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "WATCH": 3, "EXPLAINED": 4}
TYPOLOGY_LABEL = {
    "INSIDER_ATO": "Insider-enabled takeover", "EXTERNAL_ATO": "Account takeover",
    "CIRCULAR_FLOW": "Circular flow", "STRUCTURING": "Cash structuring", "MULE_FACTORY": "Mule factory",
}


def iso(v) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else v


def rupees(paise) -> float:
    return round(float(paise or 0) / 100.0, 2)


def unmasked(db: Session, employee_id: str) -> bool:
    now = datetime.now(UTC)
    row = db.execute(select(UnmaskRequest).where(
        UnmaskRequest.employee_id == employee_id, UnmaskRequest.status == "APPROVED",
        UnmaskRequest.expires_at > now)).scalars().first()
    return row is not None


def employee_card(db: Session, emp: Employee | None) -> dict | None:
    if emp is None:
        return None
    reveal = unmasked(db, emp.id)
    return {"id": emp.id, "pseudonym": emp.pseudonym, "role": emp.role, "branch_id": emp.branch_id,
            "name": emp.full_name if reveal else None, "unmasked": reveal}


def latest_run(db: Session) -> ScenarioRun | None:
    return db.execute(select(ScenarioRun).order_by(ScenarioRun.started_at.desc()).limit(1)).scalars().first()


def link_dict(lk: ChainLink) -> dict:
    return {"id": lk.id, "seq": lk.seq, "code": lk.code, "event_type": lk.event_type, "event_id": lk.event_id,
            "t": iso(lk.t), "title": lk.title, "detail": lk.detail, "lane": lk.lane,
            "amount": rupees(lk.amount_paise) if lk.amount_paise is not None else None,
            "evidence_codes": lk.evidence_codes or [], "alibi": lk.alibi}


def evidence_dict(e: Evidence) -> dict:
    return {"code": e.code, "kind": e.kind, "summary": e.summary, "source_system": e.source_system,
            "source_table": e.source_table, "source_ref": e.source_ref, "reliability": e.reliability,
            "credibility": e.credibility, "observed_at": iso(e.observed_at), "ingested_at": iso(e.ingested_at),
            "entities": e.entities or [], "facts": e.facts or {}, "supports": e.supports or [],
            "rebuts": e.rebuts or [], "sha256": e.sha256}


def alert_summary(a: Alert, c: Chain) -> dict:
    arg = a.argument or {}
    return {
        "id": a.id, "chain_id": c.id, "typology": a.typology, "typology_label": TYPOLOGY_LABEL.get(a.typology, a.typology),
        "claim": a.claim, "summary": arg.get("summary"), "priority": a.priority, "state": a.state,
        "lattice_rule": a.lattice_rule, "assignee": a.assignee, "created_at": iso(a.created_at),
        "amount_at_risk": rupees(c.amount_at_risk_paise), "latency_s": c.latency_s,
        "first_t": iso(c.first_t), "last_t": iso(c.last_t), "employee_id": c.employee_id,
        "account_id": c.account_id, "classifier_p": c.classifier_p, "recoverable": a.recoverable,
        "dims": [{"key": d["key"], "label": d["label"], "level": d["level"]} for d in (a.dims or [])],
        "lanes": sorted({lk.lane for lk in []}),
        "entity_refs": c.entity_refs or [],
    }


def load_alert(db: Session, alert_id: str) -> tuple[Alert, Chain]:
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404, f"Alert {alert_id} not found")
    return a, db.get(Chain, a.chain_id)


def chain_links(db: Session, chain_id: str) -> list[ChainLink]:
    return db.execute(select(ChainLink).where(ChainLink.chain_id == chain_id).order_by(ChainLink.seq)).scalars().all()


def alert_full(db: Session, alert_id: str) -> dict:
    a, c = load_alert(db, alert_id)
    links = chain_links(db, c.id)
    ev = db.execute(select(Evidence).where(Evidence.alert_id == a.id).order_by(Evidence.observed_at)).scalars().all()
    emp = db.get(Employee, c.employee_id) if c.employee_id else None
    acct = db.get(Account, c.account_id) if c.account_id else None
    out = alert_summary(a, c)
    out["lanes"] = sorted({lk.lane for lk in links})
    out.update({
        "dims": a.dims, "argument": a.argument, "links": [link_dict(lk) for lk in links],
        "evidence": [evidence_dict(e) for e in ev], "features": c.features, "contributions": c.contributions,
        "employee": employee_card(db, emp),
        "account": {"id": acct.id, "holder_name": acct.holder_name, "status": acct.status, "kind": acct.kind,
                    "balance": rupees(acct.balance_paise)} if acct else None,
    })
    first_money = next((lk for lk in links if lk.code in ("E5", "F5")), None)
    enabling = next((lk for lk in links if lk.code == "E0"), None)
    out["headline"] = {
        "access_to_money_s": c.latency_s,
        "enabling_privilege_lead_s": (first_money.t - enabling.t).total_seconds() if first_money and enabling else None,
    }
    return out


def case_id_for(alert_id: str) -> str:
    return "CASE-" + alert_id.replace("AL-", "")


def sql_scalar(db: Session, q: str, **params) -> Any:
    return db.execute(text(q), params).scalar()
