"""Cases: investigation workflow with four-eyes decisions and a "who saw this" trail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.common import alert_full, alert_summary, case_id_for, iso
from app.core import audit
from app.core.db import get_db
from app.core.security import CurrentUser, Principal, require
from app.loom.models import Alert, AppUser, AuditLog, Case, CaseNote, Chain, EvidencePack

router = APIRouter(prefix="/cases", tags=["cases"])
SLA = {"P1": timedelta(hours=1), "P2": timedelta(hours=8), "P3": timedelta(hours=72)}
DECISIONS = {"ESCALATE": "CLOSED_ESCALATED", "BENIGN": "CLOSED_BENIGN", "UNPROVEN": "CLOSED_UNPROVEN"}


def _case_dict(db: Session, c: Case) -> dict:
    a = db.get(Alert, c.alert_id)
    ch = db.get(Chain, a.chain_id)
    names = {u.id: u.display_name for u in db.execute(select(AppUser)).scalars()}
    return {"id": c.id, "alert_id": c.alert_id, "title": c.title, "state": c.state, "priority": c.priority,
            "assignee": c.assignee, "assignee_name": names.get(c.assignee), "reviewer": c.reviewer,
            "reviewer_name": names.get(c.reviewer), "sla_due_at": iso(c.sla_due_at), "decision": c.decision,
            "decision_reason": c.decision_reason, "subject_response": c.subject_response,
            "recommended_controls": c.recommended_controls, "opened_at": iso(c.opened_at),
            "closed_at": iso(c.closed_at), "alert": alert_summary(a, ch)}


class OpenCase(BaseModel):
    alert_id: str


@router.post("")
def open_case(body: OpenCase, db: Annotated[Session, Depends(get_db)],
              p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
    a = db.get(Alert, body.alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    cid = case_id_for(a.id)
    c = db.get(Case, cid)
    if c is None:
        # Anyone who can read cases may view an open one; only triage/investigation roles may open it.
        if not {"cases:triage", "cases:investigate"} & p.capabilities:
            raise HTTPException(403, f"Your role ({p.role}) cannot open cases.")
        now = datetime.now(UTC)
        c = Case(id=cid, alert_id=a.id, title=a.claim, state="INVESTIGATING", priority=a.priority, assignee=p.id,
                 sla_due_at=now + SLA.get(a.priority, timedelta(days=7)), opened_at=now, recommended_controls=[])
        db.add(c)
        a.state = "INVESTIGATING"
        a.assignee = p.id
        audit.append(db, p.id, "case.open", cid, {"alert": a.id, "priority": a.priority})
        db.commit()
    return _case_dict(db, c)


@router.get("")
def list_cases(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    return [_case_dict(db, c) for c in db.execute(select(Case).order_by(Case.opened_at.desc())).scalars()]


@router.get("/{case_id}")
def get_case(case_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    recent = db.execute(select(AuditLog).where(AuditLog.actor == p.id, AuditLog.action == "case.view",
                                               AuditLog.target == case_id,
                                               AuditLog.at >= datetime.now(UTC) - timedelta(minutes=10))).first()
    if recent is None:
        audit.append(db, p.id, "case.view", case_id)
        db.commit()
    out = _case_dict(db, c)
    out["detail"] = alert_full(db, c.alert_id)
    out["notes"] = [{"id": n.id, "author": n.author, "body": n.body, "evidence_refs": n.evidence_refs,
                     "created_at": iso(n.created_at)}
                    for n in db.execute(select(CaseNote).where(CaseNote.case_id == case_id)
                                        .order_by(CaseNote.created_at)).scalars()]
    out["packs"] = [{"id": k.id, "sha256": k.sha256, "created_by": k.created_by, "created_at": iso(k.created_at),
                     "locked": k.locked} for k in db.execute(select(EvidencePack).where(EvidencePack.case_id == case_id)).scalars()]
    out["activity"] = activity(case_id, p, db)
    return out


@router.get("/{case_id}/activity")
def activity(case_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    c = db.get(Case, case_id)
    targets = [case_id] + ([c.alert_id] if c else [])
    names = {u.id: u.display_name for u in db.execute(select(AppUser)).scalars()}
    rows = db.execute(select(AuditLog).where(or_(AuditLog.target.in_(targets),
                                                 AuditLog.payload["case"].astext == case_id))
                      .order_by(AuditLog.at)).scalars().all()
    return [{"id": r.id, "at": iso(r.at), "actor": r.actor, "actor_name": names.get(r.actor, r.actor),
             "action": r.action, "payload": r.payload, "hash": r.hash[:12]} for r in rows]


class CasePatch(BaseModel):
    assignee: str | None = None
    reviewer: str | None = None
    subject_response: str | None = None
    recommended_controls: list[str] | None = None


@router.patch("/{case_id}")
def patch_case(case_id: str, body: CasePatch, db: Annotated[Session, Depends(get_db)],
               p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    changes = body.model_dump(exclude_none=True)
    if "assignee" in changes and "cases:assign" not in p.capabilities and changes["assignee"] != p.id:
        raise HTTPException(403, "Only a team lead can assign cases to others")
    for k, v in changes.items():
        setattr(c, k, v)
    audit.append(db, p.id, "case.update", case_id, changes)
    db.commit()
    return _case_dict(db, c)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[str] = []


@router.post("/{case_id}/notes")
def add_note(case_id: str, body: NoteIn, db: Annotated[Session, Depends(get_db)],
             p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    n = CaseNote(id=f"NOTE-{datetime.now(UTC):%H%M%S%f}", case_id=case_id, author=p.id, body=body.body,
                 evidence_refs=body.evidence_refs, created_at=datetime.now(UTC))
    db.add(n)
    audit.append(db, p.id, "case.note", case_id, {"evidence_refs": body.evidence_refs})
    db.commit()
    return {"id": n.id, "author": n.author, "body": n.body, "evidence_refs": n.evidence_refs, "created_at": iso(n.created_at)}


class Proposal(BaseModel):
    decision: str
    reason: str = Field(min_length=3)


@router.post("/{case_id}/propose")
def propose(case_id: str, body: Proposal, db: Annotated[Session, Depends(get_db)],
            p: Annotated[Principal, Depends(require("cases:propose"))]) -> dict:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    if p.id != c.assignee:
        # The four-eyes check in review() compares against the assignee, so only they may propose.
        raise HTTPException(403, "Only the assigned investigator can propose a decision")
    if body.decision not in DECISIONS:
        raise HTTPException(422, f"Decision must be one of {', '.join(DECISIONS)}")
    c.state, c.decision, c.decision_reason = "REVIEW", body.decision, body.reason
    audit.append(db, p.id, "case.propose", case_id, body.model_dump())
    db.commit()
    return _case_dict(db, c)


class Review(BaseModel):
    approve: bool
    note: str = ""


@router.post("/{case_id}/review")
def review(case_id: str, body: Review, db: Annotated[Session, Depends(get_db)],
           p: Annotated[Principal, Depends(require("cases:review"))]) -> dict:
    c = db.get(Case, case_id)
    if c is None:
        raise HTTPException(404, "Case not found")
    if c.state != "REVIEW":
        raise HTTPException(409, "This case has no decision waiting for review")
    if p.id == c.assignee:
        raise HTTPException(409, "Four-eyes rule: the reviewer must be a different person from the investigator")
    c.reviewer = p.id
    if body.approve:
        c.state = DECISIONS[c.decision]
        c.closed_at = datetime.now(UTC)
        a = db.get(Alert, c.alert_id)
        a.state = c.state
    else:
        c.state = "INVESTIGATING"
    audit.append(db, p.id, "case.review", case_id, {"approve": body.approve, "note": body.note, "decision": c.decision})
    db.commit()
    return _case_dict(db, c)
