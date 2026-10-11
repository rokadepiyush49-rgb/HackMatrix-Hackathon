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

Delivery is at-least-once and in any order (FIN-04 Addition 1). Every arrival is recorded in
`feed_receipt` with its event time and arrival time, and classified:

  NEW        first arrival of the row: inserted, balances moved, master-data change resolved
  DUPLICATE  the same row (same ID, same content hash) is already in: nothing changes
  CONFLICT   same ID, different content: refused and kept on the receipt for review; nothing changes

A NEW arrival whose event time is behind the stream's watermark (the latest event time already in)
is marked late. Arrival order cannot change the result: balance moves are additive, and a
master-data change is applied only if no change to the same field with a later event time is
already in place (last writer wins by event time, then ID), so every order settles to the same Loom.
Detection recomputes over the whole window, so late rows are picked up by the next run.
"""

from __future__ import annotations

import hashlib
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


def content_hash(table: str, row: dict) -> str:
    """Identity of a delivery's content: the target table and the row, canonically serialised."""
    body = json.dumps({"table": table, "row": row}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _scope_of(strand: str) -> str:
    return strand if strand in LIVE_STRANDS else "evening"


@dataclass(frozen=True)
class Receipt:
    ref: str
    outcome: str  # NEW | DUPLICATE | CONFLICT
    late: bool
    late_by_s: int | None
    effect: str | None  # APPLIED | SUPERSEDED | None
    arrived_at: datetime
    reason: str | None = None

    def public(self) -> dict:
        return {"ref": self.ref, "outcome": self.outcome, "late": self.late, "late_by_s": self.late_by_s,
                "effect": self.effect, "arrived_at": self.arrived_at.isoformat(), "reason": self.reason}


def deliver(conn: Connection, ev: Item, arrived_at: datetime | None = None, run_id: str | None = None) -> Receipt:
    """Receive one delivery of a source row: ingest it once, absorb duplicates, refuse conflicts.

    Call inside a transaction. The staged row in `feed_event` is the source log of record: a delivery
    whose content differs from it is a CONFLICT and changes nothing.
    """
    table = ev.source_table
    if table not in TABLES:
        raise ValueError(f"feed row for unexpected table {table!r}")
    received = datetime.now(UTC)
    arrived = arrived_at or received
    h = content_hash(table, ev.row)
    staged = conn.execute(text("SELECT seq, t AS event_t, source_table, ref, row, strand, ingested_at FROM feed_event "
                               "WHERE seq = :seq FOR UPDATE"), {"seq": ev.seq}).first()
    late, late_by, effect, reason = False, None, None, None
    if staged is None or staged.ref != ev.ref or staged.source_table != table:
        outcome, reason = "CONFLICT", "no staged source row with this sequence number and ID"
    elif content_hash(staged.source_table, staged.row) != h:
        outcome, reason = "CONFLICT", "same ID, different content from the row of record"
    elif staged.ingested_at is not None:
        outcome = "DUPLICATE"
    else:
        scope = SCOPES[_scope_of(staged.strand)]
        watermark = conn.execute(text(f"SELECT max(t) FROM feed_event WHERE ingested_at IS NOT NULL AND {scope}")).scalar()
        inserted = conn.execute(text(f"INSERT INTO {table} SELECT * FROM jsonb_populate_record(NULL::{table}, "
                                     f"CAST(:row AS jsonb)) ON CONFLICT (id) DO NOTHING RETURNING id"),
                                {"row": json.dumps(ev.row)}).first()
        if inserted is None:
            outcome, reason = "CONFLICT", f"ID already present in {table} from another source"
        else:
            outcome = "NEW"
            if watermark is not None and staged.event_t < watermark:
                late, late_by = True, int((watermark - staged.event_t).total_seconds())
            if table == "txn":
                _move_money(conn, ev.row, +1)
            if ev.effect:
                effect = "APPLIED" if _effect_is_latest(conn, ev) else "SUPERSEDED"
                if effect == "APPLIED":
                    _set(conn, ev.effect, "new")
            conn.execute(text("UPDATE feed_event SET ingested_at = :now, content_sha256 = :h, arrived_at = :arr, "
                              "late_by_s = :late WHERE seq = :seq"),
                         {"now": received, "h": h, "arr": arrived, "late": late_by, "seq": ev.seq})
    conn.execute(text("INSERT INTO feed_receipt (seq, ref, source_table, event_t, arrived_at, received_at, outcome, late, "
                      "late_by_s, effect, content_sha256, run_id, detail) VALUES (:seq, :ref, :table, :t, :arr, :rec, "
                      ":outcome, :late, :late_by, :effect, :h, :run, CAST(:detail AS jsonb))"),
                 {"seq": ev.seq, "ref": ev.ref, "table": table, "t": ev.t, "arr": arrived, "rec": received,
                  "outcome": outcome, "late": late, "late_by": late_by, "effect": effect, "h": h, "run": run_id,
                  "detail": json.dumps({"reason": reason} if reason else {})})
    return Receipt(ev.ref, outcome, late, late_by, effect, arrived, reason)


def _effect_is_latest(conn: Connection, ev: Item) -> bool:
    """True unless a change to the same account field with a later event time (then ID) is already in."""
    e = ev.effect or {}
    newer = conn.execute(text("SELECT 1 FROM feed_event WHERE ingested_at IS NOT NULL AND seq <> :seq "
                              "AND effect->>'account_id' = :a AND effect->>'column' = :c "
                              "AND (t > :t OR (t = :t AND ref > :ref)) LIMIT 1"),
                         {"seq": ev.seq, "a": e.get("account_id"), "c": e.get("column"), "t": ev.t, "ref": ev.ref}).first()
    return newer is None


def ingest(conn: Connection, ev: Item) -> Receipt:
    """Deliver one row now (the original entry point: Live Ops, your input and the mock bank)."""
    return deliver(conn, ev)


def reset(conn: Connection, scope: str = "all") -> int:
    """Undo every ingested event in the scope; drop composed rows. Returns how many were undone.

    Undone newest-first by *event* time, so each field ends at the value it had before the earliest
    change, whatever order the changes arrived in. Balance moves are reversed exactly.
    """
    rows = conn.execute(text(f"SELECT seq, source_table, ref, row, effect FROM feed_event "
                             f"WHERE ingested_at IS NOT NULL AND {SCOPES[scope]} ORDER BY t DESC, ref DESC")).all()
    for _seq, table, ref, row, effect in rows:
        if table not in TABLES:
            raise ValueError(f"feed row for unexpected table {table!r}")
        if table == "txn":
            _move_money(conn, row, -1)
        if effect:
            _set(conn, effect, "old")
        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": ref})
    conn.execute(text(f"UPDATE feed_event SET ingested_at = NULL, content_sha256 = NULL, arrived_at = NULL, "
                      f"late_by_s = NULL WHERE ingested_at IS NOT NULL AND {SCOPES[scope]}"))
    if scope in ("all", "yours", "bank"):
        conn.execute(text(f"DELETE FROM feed_event WHERE strand IN ('yours', 'bank') AND {SCOPES[scope]}"))
    return len(rows)
