"""The live feed: ingest held-back source rows in order, and undo them.

Ingesting an event does what a change-data-capture connector would: insert the source row as-is
and apply the master-data change it implies, in one transaction per event. A transfer moves the
two balances; a mobile-number or limit change updates the account. Reset reverses every ingested
event, newest first, so the demo can be run again from the same starting point.

Three scopes share the table: the simulator's held-back **evening** (strands attack, camp, routine),
**yours** — rows composed from a person's choices at the console (app.loom.compose) — and **bank**,
rows written by the Kestrel Bank mock as someone uses it (app.loom.bank; ingested the moment they
happen). Each can be undone on its own; "yours" and "bank" rows are deleted when undone, since they
were never part of the held-back feed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, func, select, text
from sqlalchemy.orm import Session

from app.loom.models import FeedEvent

# Only these tables can be written by the feed, and only these account columns changed by it.
TABLES = frozenset({"device", "session", "work_item", "access_event", "state_change", "beneficiary", "txn",
                    "entitlement", "roster"})
SCOPES = {"evening": "strand NOT IN ('yours', 'bank')", "yours": "strand = 'yours'", "bank": "strand = 'bank'",
          "all": "TRUE"}
LIVE_STRANDS = ("yours", "bank")  # rows created during a session rather than held back by the simulator
EFFECT_COLUMNS = frozenset({"registered_mobile_tok", "daily_limit_paise", "status"})


def status(db: Session) -> dict:
    """Counts for tonight's evening, plus how much composed input is staged or in."""
    evening = FeedEvent.strand.notin_(LIVE_STRANDS)
    total, ingested, first_t, last_t = db.execute(select(
        func.count(), func.count(FeedEvent.ingested_at), func.min(FeedEvent.t), func.max(FeedEvent.t)).where(evening)).one()
    nxt = db.execute(select(FeedEvent.t).where(evening, FeedEvent.ingested_at.is_(None))
                     .order_by(FeedEvent.seq).limit(1)).scalar()
    y_total, y_in = db.execute(select(func.count(), func.count(FeedEvent.ingested_at)).where(FeedEvent.strand == "yours")).one()
    b_total, b_in = db.execute(select(func.count(), func.count(FeedEvent.ingested_at)).where(FeedEvent.strand == "bank")).one()
    return {"total": total, "ingested": ingested, "pending": total - ingested,
            "feed_start": first_t.isoformat() if first_t else None,
            "feed_end": last_t.isoformat() if last_t else None, "next_t": nxt.isoformat() if nxt else None,
            "yours": {"total": y_total, "ingested": y_in}, "bank": {"total": b_total, "ingested": b_in}}


@dataclass(frozen=True)
class Item:
    seq: int
    t: datetime
    source_table: str
    ref: str
    system: str
    summary: str
    row: dict
    effect: dict | None

    def public(self) -> dict:
        """What the UI may see while a run is in progress: no ground truth, no raw row."""
        return {"seq": self.seq, "t": self.t.isoformat(), "table": self.source_table, "ref": self.ref,
                "system": self.system, "summary": self.summary}


def pending(db: Session, scope: str = "evening") -> list[Item]:
    which = {"evening": FeedEvent.strand.notin_(LIVE_STRANDS), "yours": FeedEvent.strand == "yours",
             "bank": FeedEvent.strand == "bank"}[scope]
    rows = db.execute(select(FeedEvent).where(which, FeedEvent.ingested_at.is_(None))
                      .order_by(FeedEvent.t, FeedEvent.seq)).scalars()
    return [Item(r.seq, r.t, r.source_table, r.ref, r.system, r.summary, r.row, r.effect) for r in rows]


def ingested_refs(conn: Connection, scope: str = "all") -> dict[str, str]:
    """ref → source table for every ingested row in the scope."""
    return dict(conn.execute(text(f"SELECT ref, source_table FROM feed_event WHERE ingested_at IS NOT NULL "
                                  f"AND {SCOPES[scope]}")).all())


def _move_money(conn: Connection, row: dict, sign: int) -> None:
    amount = int(row["amount_paise"]) * sign
    for account, delta in ((row["from_account"], -amount), (row["to_account"], amount)):
        conn.execute(text("UPDATE account SET balance_paise = balance_paise + :d WHERE id = :a AND kind <> 'EXTERNAL'"),
                     {"d": delta, "a": account})


def _set(conn: Connection, effect: dict, which: str) -> None:
    column = effect["column"]
    if column not in EFFECT_COLUMNS:
        raise ValueError(f"feed effect on unexpected column {column!r}")
    conn.execute(text(f"UPDATE account SET {column} = :v WHERE id = :a"), {"v": effect[which], "a": effect["account_id"]})


def ingest(conn: Connection, ev: Item) -> None:
    """Insert one held-back row and apply its effects. Call inside a transaction."""
    table = ev.source_table
    if table not in TABLES:
        raise ValueError(f"feed row for unexpected table {table!r}")
    conn.execute(text(f"INSERT INTO {table} SELECT * FROM jsonb_populate_record(NULL::{table}, CAST(:row AS jsonb))"),
                 {"row": json.dumps(ev.row)})
    if table == "txn":
        _move_money(conn, ev.row, +1)
    if ev.effect:
        _set(conn, ev.effect, "new")
    conn.execute(text("UPDATE feed_event SET ingested_at = :now WHERE seq = :seq"),
                 {"now": datetime.now(UTC), "seq": ev.seq})


def reset(conn: Connection, scope: str = "all") -> int:
    """Undo every ingested event in the scope, newest first; drop composed rows. Returns how many were undone."""
    rows = conn.execute(text(f"SELECT seq, source_table, ref, row, effect FROM feed_event "
                             f"WHERE ingested_at IS NOT NULL AND {SCOPES[scope]} ORDER BY seq DESC")).all()
    for _seq, table, ref, row, effect in rows:
        if table not in TABLES:
            raise ValueError(f"feed row for unexpected table {table!r}")
        if table == "txn":
            _move_money(conn, row, -1)
        if effect:
            _set(conn, effect, "old")
        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": ref})
    conn.execute(text(f"UPDATE feed_event SET ingested_at = NULL WHERE ingested_at IS NOT NULL AND {SCOPES[scope]}"))
    if scope in ("all", "yours", "bank"):
        conn.execute(text(f"DELETE FROM feed_event WHERE strand IN ('yours', 'bank') AND {SCOPES[scope]}"))
    return len(rows)
