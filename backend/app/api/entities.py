"""Entity search and dossiers (employee, account, customer, device)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import alert_summary, employee_card, iso, rupees
from app.core.db import get_db
from app.core.security import CurrentUser
from app.loom.models import (
    AccessEvent,
    Account,
    Alert,
    Beneficiary,
    Branch,
    Chain,
    Customer,
    Device,
    Employee,
    EmployeeBaseline,
    Entitlement,
    Explanation,
    ModelPrediction,
    Relationship,
    Signal,
    StateChange,
    Txn,
)
from app.loom.models import (
    Session as Sess,
)

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("/search")
def search(p: CurrentUser, db: Annotated[Session, Depends(get_db)], q: str) -> list[dict]:
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    out = []
    for e in db.execute(select(Employee).where(or_(Employee.id.ilike(like), Employee.pseudonym.ilike(like))).limit(6)).scalars():
        out.append({"id": e.id, "kind": "employee", "label": e.id, "sub": e.pseudonym})
    for a in db.execute(select(Account).where(or_(Account.id.ilike(like), Account.holder_name.ilike(like))).limit(8)).scalars():
        out.append({"id": a.id, "kind": "account" if a.kind != "EXTERNAL" else "external", "label": a.id,
                    "sub": f"{a.holder_name} · {a.bank_name}"})
    for c in db.execute(select(Customer).where(Customer.id.ilike(like)).limit(4)).scalars():
        out.append({"id": c.id, "kind": "customer", "label": c.id, "sub": c.segment.title()})
    for d in db.execute(select(Device).where(Device.id.ilike(like)).limit(4)).scalars():
        out.append({"id": d.id, "kind": "device", "label": d.id, "sub": d.kind.title()})
    for a in db.execute(select(Alert).where(Alert.id.ilike(like)).limit(4)).scalars():
        out.append({"id": a.id, "kind": "alert", "label": a.id, "sub": a.claim[:60]})
    return out


def _related_alerts(db: Session, eid: str) -> list[dict]:
    rows = db.execute(select(Alert, Chain).join(Chain, Chain.id == Alert.chain_id)
                      .where(Chain.entity_refs.any(eid))).all()
    return [alert_summary(a, c) for a, c in rows]


def _signals(db: Session, eid: str) -> list[dict]:
    rows = db.execute(select(Signal).where(Signal.entity_refs.any(eid)).order_by(Signal.window_end.desc()).limit(30)).scalars()
    return [{"id": s.id, "detector": s.detector, "summary": s.summary, "t": iso(s.window_end)} for s in rows]


def _employee(db: Session, e: Employee) -> dict:
    now = db.execute(select(func.max(Txn.occurred_at))).scalar()
    ents = db.execute(select(Entitlement).where(Entitlement.employee_id == e.id).order_by(Entitlement.valid_from)).scalars().all()
    toxic = {"KYC_APPROVE", "CARD_ISSUE", "MOBILE_UPDATE_OVERRIDE"}
    held = {g.permission_code for g in ents if g.revoked_at is None}
    ent_rows = []
    for g in ents:
        flags = []
        if g.intended_expiry is not None and g.revoked_at is None and g.intended_expiry < now:
            flags.append("EXPIRED_BUT_ACTIVE")
        if g.permission_code in toxic and toxic.issubset(held):
            flags.append("TOXIC_COMBINATION")
        if g.reason == "Cross-training":
            flags.append("OUTSIDE_ROLE")
        ent_rows.append({"id": g.id, "permission": g.permission_code, "granted_by": g.granted_by, "reason": g.reason,
                         "request_ref": g.request_ref, "valid_from": iso(g.valid_from),
                         "intended_expiry": iso(g.intended_expiry), "revoked_at": iso(g.revoked_at), "flags": flags})
    base = db.get(EmployeeBaseline, e.id)
    verdicts = dict(db.execute(select(Explanation.verdict, func.count()).where(Explanation.employee_id == e.id)
                               .group_by(Explanation.verdict)).all())
    unexplained = db.execute(select(Explanation, AccessEvent).join(AccessEvent, AccessEvent.id == Explanation.access_event_id)
                             .where(Explanation.employee_id == e.id, Explanation.verdict != "EXPLAINED")
                             .order_by(Explanation.occurred_at.desc()).limit(12)).all()
    approved = db.execute(select(Account).where(Account.kyc_approved_by == e.id,
                                                Account.opened_at >= now - timedelta(days=60))
                          .order_by(Account.opened_at)).scalars().all()
    branch = db.get(Branch, e.branch_id)
    return {
        "kind": "employee", "id": e.id, "card": employee_card(db, e), "branch": branch.name if branch else e.branch_id,
        "hire_date": iso(e.hire_date), "tenure_years": round(((now.date() if now else e.hire_date) - e.hire_date).days / 365.25, 1),
        "entitlements": ent_rows,
        "baseline": {"hour_rates": base.hour_rates if base else [], "peer_hour_rates": base.peer_hour_rates if base else [],
                     "sessions_90d": base.sessions_90d if base else 0, "after20_sessions": base.after20_sessions if base else 0,
                     "peer_after20_share": base.peer_after20_share if base else 0,
                     "approvals_60d": base.accounts_approved_60d if base else 0,
                     "approvals_baseline_60d": base.approvals_baseline_60d if base else 0},
        "alibi": {"explained": verdicts.get("EXPLAINED", 0), "partial": verdicts.get("PARTIAL", 0),
                  "unexplained": verdicts.get("UNEXPLAINED", 0),
                  "coverage": round(verdicts.get("EXPLAINED", 0) / max(sum(verdicts.values()), 1), 4),
                  "recent": [{"access_id": x.access_event_id, "t": iso(x.occurred_at), "verdict": x.verdict,
                              "action": ae.action, "account_id": ae.account_id,
                              "reasons": sum(1 for c in x.checked if c["ok"])} for x, ae in unexplained]},
        "approved_accounts": [{"id": a.id, "opened_at": iso(a.opened_at), "mode": a.opening_mode,
                               "self_opened": a.opened_by == e.id} for a in approved],
        "relationships": [{"customer_id": r.dst_id, "type": r.rel_type, "confidence": r.confidence, "detail": r.detail}
                          for r in db.execute(select(Relationship).where(Relationship.src_id == e.id)).scalars()],
        "alerts": _related_alerts(db, e.id), "signals": _signals(db, e.id),
    }


def _account(db: Session, a: Account) -> dict:
    cust = db.get(Customer, a.customer_id) if a.customer_id else None
    sc = db.execute(select(StateChange).where(StateChange.account_id == a.id).order_by(StateChange.occurred_at)).scalars()
    payees = db.execute(select(Beneficiary).where(Beneficiary.account_id == a.id).order_by(Beneficiary.added_at)).scalars()
    tin = db.execute(select(func.coalesce(func.sum(Txn.amount_paise), 0), func.count()).where(Txn.to_account == a.id)).one()
    tout = db.execute(select(func.coalesce(func.sum(Txn.amount_paise), 0), func.count()).where(Txn.from_account == a.id)).one()
    top = db.execute(select(Txn.to_account, func.sum(Txn.amount_paise), func.count()).where(Txn.from_account == a.id)
                     .group_by(Txn.to_account).order_by(func.sum(Txn.amount_paise).desc()).limit(6)).all()
    recent = db.execute(select(Txn).where(or_(Txn.from_account == a.id, Txn.to_account == a.id))
                        .order_by(Txn.occurred_at.desc()).limit(20)).scalars()
    devices = []
    if cust:
        devices = [{"id": d, "sessions": n} for d, n in db.execute(
            select(Sess.device_id, func.count()).where(Sess.actor_id == cust.id, Sess.device_id.isnot(None))
            .group_by(Sess.device_id)).all()]
    mp = db.execute(select(ModelPrediction).where(ModelPrediction.entity_ref == a.id, ModelPrediction.model == "M6")).scalars().first()
    opener = db.get(Employee, a.opened_by) if a.opened_by else None
    approver = db.get(Employee, a.kyc_approved_by) if a.kyc_approved_by else None
    return {
        "kind": "account", "id": a.id, "holder_name": a.holder_name, "bank": a.bank_name, "type": a.kind,
        "status": a.status, "status_since": iso(a.status_since), "opened_at": iso(a.opened_at),
        "opening_mode": a.opening_mode, "opened_by": employee_card(db, opener), "kyc_approved_by": employee_card(db, approver),
        "balance": rupees(a.balance_paise), "limit": rupees(a.daily_limit_paise),
        "customer": {"id": cust.id, "segment": cust.segment, "branch_id": cust.branch_id, "rm": cust.rm_employee_id}
        if cust else None,
        "state_changes": [{"t": iso(x.occurred_at), "field": x.field, "old": x.old_value, "new": x.new_value,
                           "by": x.actor_id, "auth": x.auth_method} for x in sc],
        "payees": [{"t": iso(b.added_at), "account": b.counterparty_account, "name": b.counterparty_name} for b in payees],
        "flows": {"in": rupees(tin[0]), "in_count": tin[1], "out": rupees(tout[0]), "out_count": tout[1]},
        "top_counterparties": [{"account": t, "amount": rupees(s), "count": n} for t, s, n in top],
        "recent_txns": [{"id": x.id, "t": iso(x.occurred_at), "from": x.from_account, "to": x.to_account,
                         "amount": rupees(x.amount_paise), "channel": x.channel, "narration": x.narration} for x in recent],
        "devices": devices,
        "mule": {"p": mp.p, "contributions": mp.contributions} if mp else None,
        "alerts": _related_alerts(db, a.id), "signals": _signals(db, a.id),
    }


@router.get("/{entity_id}")
def dossier(entity_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    if entity_id.startswith("EMP-"):
        e = db.get(Employee, entity_id)
        if e:
            return _employee(db, e)
    elif entity_id.startswith(("A-", "X-")):
        a = db.get(Account, entity_id)
        if a:
            return _account(db, a)
    elif entity_id.startswith("C-"):
        c = db.get(Customer, entity_id)
        if c:
            accts = db.execute(select(Account).where(Account.customer_id == c.id)).scalars().all()
            return {"kind": "customer", "id": c.id, "segment": c.segment, "branch_id": c.branch_id,
                    "created_at": iso(c.created_at), "rm": c.rm_employee_id,
                    "accounts": [{"id": a.id, "status": a.status, "balance": rupees(a.balance_paise)} for a in accts],
                    "relationships": [{"employee_id": r.src_id, "type": r.rel_type, "detail": r.detail}
                                      for r in db.execute(select(Relationship).where(Relationship.dst_id == c.id)).scalars()],
                    "alerts": _related_alerts(db, c.id), "signals": _signals(db, c.id)}
    else:
        d = db.get(Device, entity_id)
        if d:
            users = db.execute(select(Sess.actor_id, Sess.actor_type, func.count(), func.min(Sess.started_at),
                                      func.max(Sess.started_at)).where(Sess.device_id == d.id)
                               .group_by(Sess.actor_id, Sess.actor_type)).all()
            return {"kind": "device", "id": d.id, "type": d.kind, "first_seen": iso(d.first_seen),
                    "users": [{"id": u, "type": t, "sessions": n, "first": iso(f), "last": iso(la)} for u, t, n, f, la in users],
                    "alerts": _related_alerts(db, d.id), "signals": _signals(db, d.id)}
    raise HTTPException(404, f"No entity {entity_id}")
