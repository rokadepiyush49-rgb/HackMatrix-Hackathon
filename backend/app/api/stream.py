"""Live replay: the evening of 21 Sep streamed at 60× over Server-Sent Events.

This is explicitly a *replay* of stored, time-ordered events (docs/adr/006) — it makes the
Command Center feel live in a demo without pretending to be a real-time feed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import CurrentUser
from app.loom.models import Alert, Chain, ChainLink, Signal

router = APIRouter(tags=["stream"])


def _events(start: datetime, end: datetime) -> list[dict]:
    with SessionLocal() as db:
        out = []
        for s in db.execute(select(Signal).where(Signal.window_end >= start, Signal.window_end <= end,
                                                 Signal.detector.notin_(["G3", "R6"]))).scalars():
            out.append({"type": "signal", "t": s.window_end.isoformat(), "detector": s.detector, "summary": s.summary,
                        "entities": s.entity_refs[:4]})
        rows = db.execute(select(ChainLink, Alert).join(Chain, Chain.id == ChainLink.chain_id)
                          .join(Alert, Alert.chain_id == Chain.id)
                          .where(ChainLink.t >= start, ChainLink.t <= end, Alert.priority.in_(["P1", "P2", "P3"]))).all()
        for lk, a in rows:
            out.append({"type": "link", "t": lk.t.isoformat(), "alert_id": a.id, "priority": a.priority,
                        "code": lk.code, "title": lk.title, "detail": lk.detail, "lane": lk.lane})
        for a, c in db.execute(select(Alert, Chain).join(Chain, Chain.id == Alert.chain_id)
                               .where(Alert.created_at >= start, Alert.created_at <= end,
                                      Alert.priority.in_(["P1", "P2", "P3"]))).all():
            out.append({"type": "alert", "t": a.created_at.isoformat(), "alert_id": a.id, "priority": a.priority,
                        "claim": a.claim, "amount": (c.amount_at_risk_paise or 0) / 100})
        return sorted(out, key=lambda e: e["t"])


@router.get("/stream/replay")
async def replay(p: CurrentUser, start: datetime = datetime.fromisoformat("2026-09-21T21:30:00+05:30"),
                 end: datetime = datetime.fromisoformat("2026-09-22T00:15:00+05:30"), speed: float = 60.0):
    events = await asyncio.to_thread(_events, start, end)

    async def gen():
        yield f"event: start\ndata: {json.dumps({'start': start.isoformat(), 'end': end.isoformat(), 'speed': speed, 'n': len(events)})}\n\n"
        prev = start
        for e in events:
            t = datetime.fromisoformat(e["t"])
            await asyncio.sleep(min(max((t - prev).total_seconds() / speed, 0), 6))
            prev = t
            yield f"event: {e['type']}\ndata: {json.dumps(e)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
