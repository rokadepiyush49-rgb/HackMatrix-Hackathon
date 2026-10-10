"""Account Aggregator: request a customer's consent, fetch the consented statement, revoke it.

The synthetic provider is a labelled demo and answers only in demo mode. Every response carries the data
source (SYNTHETIC_DEMO, SANDBOX or LIVE) so nothing simulated can be mistaken for a live bank feed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import Principal, require
from app.integrations.aa import service
from app.integrations.aa.providers import AAError

router = APIRouter(prefix="/aa", tags=["account-aggregator"])
HTTP = {"not_found": 404, "conflict": 409, "unsupported": 409, "config": 503, "auth": 502, "network": 502,
        "provider": 502, "malformed": 502, "bad_request": 422}


def _guard() -> None:
    s = get_settings()
    if s.aa_provider == "synthetic" and not s.demo_mode:
        raise HTTPException(404, "Not found")


def _call(fn, *args):
    try:
        return fn(*args)
    except AAError as e:
        raise HTTPException(HTTP.get(e.kind, 502), str(e)) from e


@router.get("/status")
def aa_status(p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
    s = get_settings()
    configured = s.aa_provider == "synthetic" and s.demo_mode or bool(s.aa_setu_client_id and s.aa_setu_client_secret)
    return {"provider": s.aa_provider, "configured": configured,
            "data_source": {"synthetic": "SYNTHETIC_DEMO", "setu": "SANDBOX"}[s.aa_provider],
            "data_life_days": s.aa_data_life_days,
            "note": ("Synthetic demo FIP: generated statements, never real customer data." if s.aa_provider == "synthetic"
                     else "Setu FIU sandbox: mock FIP data. Real customer data needs a regulated, certified FIU.")}


class ConsentIn(BaseModel):
    customer_id: str = Field(..., max_length=16)
    alert_id: str | None = Field(None, max_length=24)
    months: int = Field(6, ge=1, le=24)
    purpose: str = Field("Source-of-funds review for an open investigation", min_length=10, max_length=200)


@router.post("/consents", status_code=201)
def create_consent(body: ConsentIn, db: Annotated[Session, Depends(get_db)],
                   p: Annotated[Principal, Depends(require("cases:investigate"))]) -> dict:
    _guard()
    out = _call(service.create, db, body.customer_id, body.months, body.purpose, p.id, body.alert_id)
    db.commit()
    return out


@router.get("/consents")
def list_consents(db: Annotated[Session, Depends(get_db)], p: Annotated[Principal, Depends(require("cases:read"))],
                  customer_id: str | None = None) -> list[dict]:
    _guard()
    q = "SELECT id FROM aa_consent" + (" WHERE customer_id = :c" if customer_id else "") + " ORDER BY created_at DESC LIMIT 50"
    ids = db.execute(text(q), {"c": customer_id}).scalars().all()
    return [service.get(db, i) for i in ids]


@router.post("/consents/{consent_id}/approve")
def approve(consent_id: str, db: Annotated[Session, Depends(get_db)],
            p: Annotated[Principal, Depends(require("cases:investigate"))]) -> dict:
    """Demo only: stands in for the customer approving in their AA app (synthetic provider)."""
    _guard()
    out = _call(service.approve_synthetic, db, consent_id, p.id)
    db.commit()
    return out


@router.post("/consents/{consent_id}/fetch")
def fetch(consent_id: str, db: Annotated[Session, Depends(get_db)],
          p: Annotated[Principal, Depends(require("cases:investigate"))]) -> dict:
    _guard()
    out = _call(service.fetch, db, consent_id, p.id)
    db.commit()
    return out


@router.post("/consents/{consent_id}/revoke")
def revoke(consent_id: str, db: Annotated[Session, Depends(get_db)],
           p: Annotated[Principal, Depends(require("cases:investigate"))]) -> dict:
    _guard()
    out = _call(service.revoke, db, consent_id, p.id)
    db.commit()
    return out


@router.get("/consents/{consent_id}/transactions")
def transactions(consent_id: str, db: Annotated[Session, Depends(get_db)],
                 p: Annotated[Principal, Depends(require("cases:read"))], limit: int = 200) -> dict:
    _guard()
    c = _call(service.get, db, consent_id)
    rows = db.execute(text("SELECT id, fip_id, masked_account, txn_id, txn_type, mode, amount_paise, occurred_at, "
                           "narration, data_source FROM aa_fi_txn WHERE consent_id = :i ORDER BY occurred_at "
                           "LIMIT :n"), {"i": consent_id, "n": min(max(limit, 1), 2000)}).mappings().all()
    return {"consent": c, "data_source": c["data_source"],
            "rows": [{**dict(r), "amount": r["amount_paise"] / 100, "occurred_at": r["occurred_at"].isoformat()}
                     for r in rows]}
