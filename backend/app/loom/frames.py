"""Load Loom tables into pandas for the detection pipeline.

At MVP scale the whole 90-day window fits comfortably in memory (see docs/adr/002).
All timestamps are converted to IST so hour-of-day logic reads naturally.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

from app.core.db import engine

IST = "Asia/Kolkata"

TABLES = ["branch", "employee", "entitlement", "roster", "customer", "account", "device",
          "session", "access_event", "state_change", "beneficiary", "txn", "work_item",
          "relationship"]

TIME_COLS = {
    "entitlement": ["valid_from", "intended_expiry", "revoked_at"],
    "roster": ["shift_start", "shift_end"],
    "customer": ["created_at"],
    "account": ["status_since", "opened_at"],
    "device": ["first_seen"],
    "session": ["started_at", "ended_at"],
    "access_event": ["occurred_at", "ingested_at"],
    "state_change": ["occurred_at", "ingested_at"],
    "beneficiary": ["added_at"],
    "txn": ["occurred_at", "ingested_at"],
    "work_item": ["created_at", "closed_at"],
    "relationship": ["valid_from"],
}


@dataclass
class Frames:
    branch: pd.DataFrame
    employee: pd.DataFrame
    entitlement: pd.DataFrame
    roster: pd.DataFrame
    customer: pd.DataFrame
    account: pd.DataFrame
    device: pd.DataFrame
    session: pd.DataFrame
    access_event: pd.DataFrame
    state_change: pd.DataFrame
    beneficiary: pd.DataFrame
    txn: pd.DataFrame
    work_item: pd.DataFrame
    relationship: pd.DataFrame

    @property
    def window_end(self) -> pd.Timestamp:
        return self.txn["occurred_at"].max()

    @property
    def window_start(self) -> pd.Timestamp:
        return self.txn["occurred_at"].min()


def load_frames() -> Frames:
    out = {}
    with engine.connect() as conn:
        for t in TABLES:
            df = pd.read_sql(text(f"SELECT * FROM {t}"), conn)
            for c in TIME_COLS.get(t, []):
                if c in df:
                    # pandas 3 reads microsecond resolution; normalise to ns so .value comparisons agree
                    df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(IST).dt.as_unit("ns")
            out[t] = df
    f = Frames(**out)
    f.txn["amount"] = f.txn["amount_paise"] / 100.0
    return f


def frames_from_world(world) -> Frames:
    """Build Frames directly from a generated world (no database) — used for model training."""
    from app.loom.load import _clean

    out = {}
    for t in TABLES:
        rows = [_clean(t, r) for r in world.tables.get(t, [])]
        df = pd.DataFrame(rows)
        for c in TIME_COLS.get(t, []):
            if c in df:
                df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(IST).dt.as_unit("ns")
        out[t] = df
    if out["relationship"].empty:
        out["relationship"] = pd.DataFrame(columns=["id", "src_type", "src_id", "dst_type", "dst_id",
                                                    "rel_type", "source", "confidence", "detail", "valid_from"])
    f = Frames(**out)
    f.txn["amount"] = f.txn["amount_paise"] / 100.0
    return f
