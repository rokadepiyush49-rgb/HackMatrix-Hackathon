"""Alerts (argued chains) and chains."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import PRIORITY_ORDER, alert_full, alert_summary, chain_links, link_dict
from app.core import audit
from app.core.db import get_db
from app.core.security import CurrentUser, Principal, require
from app.loom.models import Alert, Chain

router = APIRouter(tags=["alerts"])


@router.get("/alerts")
def list_alerts(p: CurrentUser, db: Annotated[Session, Depends(get_db)],
                priority: Annotated[list[str] | None, Query()] = None,
                typology: str | None = None, state: str | None = None, q: str | None = None,
                include_watch: bool = False) -> list[dict]:
    stmt = select(Alert, Chain).join(Chain, Chain.id == Alert.chain_id)
    if priority:
        stmt = stmt.where(Alert.priority.in_(priority))
    elif not include_watch:
        stmt = stmt.where(Alert.priority.in_(["P1", "P2", "P3"]))
    if typology:
        stmt = stmt.where(Alert.typology == typology)
    if state:
        stmt = stmt.where(Alert.state == state)
    rows = db.execute(stmt).all()
    out = [alert_summary(a, c) for a, c in rows]
    if q:
        ql = q.lower()
        out = [x for x in out if ql in x["claim"].lower() or ql in x["id"].lower()
               or any(ql in e.lower() for e in x["entity_refs"])]
    return sorted(out, key=lambda x: (PRIORITY_ORDER.get(x["priority"], 9), -x["amount_at_risk"]))


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    return alert_full(db, alert_id)


class AlertPatch(BaseModel):
    assignee: str | None = None
    state: str | None = None


@router.patch("/alerts/{alert_id}")
def patch_alert(alert_id: str, body: AlertPatch, db: Annotated[Session, Depends(get_db)],
                p: Annotated[Principal, Depends(require("cases:triage"))]) -> dict:
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(a, k, v)
    audit.append(db, p.id, "alert.update", alert_id, changes)
    db.commit()
    return {"id": a.id, **changes}


@router.get("/chains")
def list_chains(p: CurrentUser, db: Annotated[Session, Depends(get_db)], kind: str | None = None,
                priority: Annotated[list[str] | None, Query()] = None) -> list[dict]:
    stmt = select(Alert, Chain).join(Chain, Chain.id == Alert.chain_id)
    if kind:
        stmt = stmt.where(Chain.kind == kind)
    if priority:
        stmt = stmt.where(Alert.priority.in_(priority))
    rows = db.execute(stmt).all()
    out = []
    for a, c in rows:
        s = alert_summary(a, c)
        s["features"] = c.features
        s["n_links"] = len(chain_links(db, c.id))
        out.append(s)
    return sorted(out, key=lambda x: (PRIORITY_ORDER.get(x["priority"], 9), -x["amount_at_risk"]))


@router.get("/chains/{chain_id}")
def get_chain(chain_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    c = db.get(Chain, chain_id)
    if c is None:
        raise HTTPException(404, "Chain not found")
    a = db.execute(select(Alert).where(Alert.chain_id == chain_id)).scalars().first()
    return {"id": c.id, "kind": c.kind, "alert_id": a.id if a else None, "priority": a.priority if a else None,
            "features": c.features, "contributions": c.contributions, "classifier_p": c.classifier_p,
            "links": [link_dict(lk) for lk in chain_links(db, chain_id)]}
