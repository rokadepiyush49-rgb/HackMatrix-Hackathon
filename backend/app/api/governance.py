"""Governance: users & roles, detector/model/agent registry, unmask approvals, audit, data sources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import iso
from app.core import audit
from app.core.db import get_db
from app.core.security import ROLE_CAPABILITIES, CurrentUser, Principal, require
from app.council.engine import AGENTS, MODERATOR
from app.loom.models import (
    AccessEvent,
    AppUser,
    AuditLog,
    Employee,
    Entitlement,
    Roster,
    Signal,
    StateChange,
    Txn,
    UnmaskRequest,
    WorkItem,
)
from app.loom.models import (
    Session as Sess,
)
from app.ml.models import model_meta
from app.needle.registry import DETECTORS

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/users")
def users(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    return {"users": [{"id": u.id, "name": u.display_name, "role": u.role, "title": u.title,
                       "capabilities": sorted(ROLE_CAPABILITIES.get(u.role, set()))}
                      for u in db.execute(select(AppUser).order_by(AppUser.id)).scalars()],
            "roles": {r: sorted(c) for r, c in ROLE_CAPABILITIES.items()}}


@router.get("/registry")
def registry(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    counts = dict(db.execute(select(Signal.detector, func.count()).group_by(Signal.detector)).all())
    return {"detectors": [{"code": d.code, "name": d.name, "family": d.family, "version": d.version, "logic": d.logic,
                           "params": d.params, "owner": d.owner, "signals": counts.get(d.code, 0)}
                          for d in DETECTORS.values()],
            "models": model_meta(),
            "agents": AGENTS + [MODERATOR],
            "llm": {"role": "Language only — narratives, STR drafts, cited answers. Never creates, scores or closes alerts.",
                    "verifier": "cite-or-drop"}}


@router.get("/sources")
def sources(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    def last(model, col) -> str | None:
        return iso(db.execute(select(func.max(col))).scalar())

    return [
        {"system": "Core banking (CBS)", "table": "txn / state_change", "rows": db.execute(select(func.count()).select_from(Txn)).scalar(),
         "latest": last(Txn, Txn.occurred_at), "status": "LIVE"},
        {"system": "CBS app audit", "table": "access_event", "rows": db.execute(select(func.count()).select_from(AccessEvent)).scalar(),
         "latest": last(AccessEvent, AccessEvent.occurred_at), "status": "LIVE"},
        {"system": "IAM", "table": "entitlement", "rows": db.execute(select(func.count()).select_from(Entitlement)).scalar(),
         "latest": last(Entitlement, Entitlement.valid_from), "status": "LIVE"},
        {"system": "HRMS", "table": "roster", "rows": db.execute(select(func.count()).select_from(Roster)).scalar(),
         "latest": last(Roster, Roster.shift_end), "status": "LIVE"},
        {"system": "Service desk", "table": "work_item", "rows": db.execute(select(func.count()).select_from(WorkItem)).scalar(),
         "latest": last(WorkItem, WorkItem.created_at), "status": "LIVE"},
        {"system": "VPN / SSO / digital channel", "table": "session", "rows": db.execute(select(func.count()).select_from(Sess)).scalar(),
         "latest": last(Sess, Sess.started_at), "status": "LIVE"},
        {"system": "State-change audit", "table": "state_change", "rows": db.execute(select(func.count()).select_from(StateChange)).scalar(),
         "latest": last(StateChange, StateChange.occurred_at), "status": "LIVE"},
        {"system": "Endpoint telemetry (EDR)", "table": "—", "rows": 0, "latest": None, "status": "NOT_CONNECTED"},
        {"system": "Branch CCTV", "table": "—", "rows": 0, "latest": None, "status": "NOT_CONNECTED"},
        {"system": "DoT FRI / SIM-swap", "table": "—", "rows": 0, "latest": None, "status": "NOT_CONNECTED"},
    ]


@router.get("/audit")
def audit_log(p: Annotated[Principal, Depends(require("alerts:read"))], db: Annotated[Session, Depends(get_db)],
              limit: int = 100, target: str | None = None) -> dict:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    if target:
        stmt = select(AuditLog).where(AuditLog.target == target).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    names = {u.id: u.display_name for u in db.execute(select(AppUser)).scalars()}
    rows = db.execute(stmt).scalars().all()
    return {"entries": [{"id": r.id, "at": iso(r.at), "actor": r.actor, "actor_name": names.get(r.actor, r.actor),
                         "action": r.action, "target": r.target, "payload": r.payload, "prev_hash": r.prev_hash[:16],
                         "hash": r.hash[:16]} for r in rows],
            "verification": audit.verify(db)}


class UnmaskIn(BaseModel):
    employee_id: str
    reason: str = Field(min_length=10)
    case_id: str | None = None


@router.get("/unmask")
def unmask_list(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    return [{"id": u.id, "employee_id": u.employee_id, "case_id": u.case_id, "requested_by": u.requested_by,
             "reason": u.reason, "status": u.status, "approved_by": u.approved_by, "created_at": iso(u.created_at),
             "expires_at": iso(u.expires_at)}
            for u in db.execute(select(UnmaskRequest).order_by(UnmaskRequest.created_at.desc())).scalars()]


@router.post("/unmask")
def unmask_request(body: UnmaskIn, db: Annotated[Session, Depends(get_db)],
                   p: Annotated[Principal, Depends(require("unmask:request"))]) -> dict:
    if db.get(Employee, body.employee_id) is None:
        raise HTTPException(404, "Employee not found")
    u = UnmaskRequest(id=f"UNM-{datetime.now(UTC):%H%M%S%f}"[:22], employee_id=body.employee_id, case_id=body.case_id,
                      requested_by=p.id, reason=body.reason, status="PENDING", created_at=datetime.now(UTC))
    db.add(u)
    audit.append(db, p.id, "unmask.request", body.case_id or body.employee_id, {"employee": body.employee_id})
    db.commit()
    return {"id": u.id, "status": u.status}


class DecideIn(BaseModel):
    approve: bool


@router.post("/unmask/{request_id}/decide")
def unmask_decide(request_id: str, body: DecideIn, db: Annotated[Session, Depends(get_db)],
                  p: Annotated[Principal, Depends(require("unmask:approve"))]) -> dict:
    u = db.get(UnmaskRequest, request_id)
    if u is None:
        raise HTTPException(404, "Request not found")
    if u.requested_by == p.id:
        raise HTTPException(409, "Two-person rule: the approver must be a different person from the requester")
    u.status = "APPROVED" if body.approve else "REJECTED"
    u.approved_by, u.decided_at = p.id, datetime.now(UTC)
    u.expires_at = datetime.now(UTC) + timedelta(hours=4) if body.approve else None
    audit.append(db, p.id, "unmask." + u.status.lower(), u.case_id or u.employee_id, {"employee": u.employee_id,
                                                                                       "request": u.id})
    db.commit()
    return {"id": u.id, "status": u.status, "expires_at": iso(u.expires_at)}
