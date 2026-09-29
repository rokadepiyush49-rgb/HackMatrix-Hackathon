"""Append-only, hash-chained audit log.

Each row stores the hash of the previous row, so editing or deleting any row breaks
verification from that point on.
"""

import hashlib
from datetime import UTC, datetime

import orjson
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.loom.models import AuditLog

GENESIS = "0" * 64


def _digest(prev_hash: str, at: datetime, actor: str, action: str, target: str | None,
            payload: dict) -> str:
    body = orjson.dumps(
        {"prev": prev_hash, "at": at.astimezone(UTC).isoformat(), "actor": actor, "action": action,
         "target": target, "payload": payload},
        option=orjson.OPT_SORT_KEYS,
    )
    return hashlib.sha256(body).hexdigest()


def append(db: Session, actor: str, action: str, target: str | None = None,
           payload: dict | None = None) -> AuditLog:
    """Append one entry. Serialised with an advisory lock so the chain never forks."""
    payload = payload or {}
    db.execute(text("SELECT pg_advisory_xact_lock(424242)"))
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev = last.hash if last else GENESIS
    at = datetime.now(UTC)
    entry = AuditLog(at=at, actor=actor, action=action, target=target, payload=payload,
                     prev_hash=prev, hash=_digest(prev, at, actor, action, target, payload))
    db.add(entry)
    db.flush()
    return entry


def verify(db: Session) -> dict:
    """Walk the chain; report the first broken link, if any."""
    prev = GENESIS
    count = 0
    for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        expected = _digest(prev, row.at, row.actor, row.action, row.target, row.payload)
        if row.prev_hash != prev or row.hash != expected:
            return {"ok": False, "verified_through": count, "broken_at": row.id}
        prev = row.hash
        count += 1
    return {"ok": True, "verified_through": count, "head": prev}
