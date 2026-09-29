"""Bulk-load a Kestrel-Sim world into Loom.

PII is tokenised here, at the ingest boundary: raw phone and KYC numbers never reach
the database. Rows are streamed with PostgreSQL COPY.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from psycopg.types.json import Jsonb
from sqlalchemy import text

from app.core import audit
from app.core.config import get_settings
from app.core.db import Base, engine, session_scope
from app.core.pii import mask_tail, tokenise
from app.core.security import hash_password
from app.loom.models import AppUser, ScenarioLabel

# Load order respects foreign keys.
TABLE_ORDER = ["branch", "permission", "employee", "entitlement", "roster", "customer", "account",
               "device", "session", "access_event", "state_change", "beneficiary", "txn",
               "work_item", "relationship"]

DEMO_USERS = [
    ("ananya", "Ananya Rao", "L2_INVESTIGATOR", "L2 Fraud Investigator · FRMU"),
    ("rohit", "Rohit Menon", "L1_ANALYST", "L1 Analyst · FRMU"),
    ("suresh", "Suresh Iyer", "VIGILANCE", "Chief Vigilance Officer"),
    ("farah", "Farah Khan", "PRINCIPAL_OFFICER", "Principal Officer (PMLA)"),
    ("karthik", "Karthik Nair", "INSIDER_RISK", "Insider-Risk Lead · SOC"),
    ("meera", "Meera Joshi", "TEAM_LEAD", "Team Lead · FRMU"),
    ("audit", "Internal Audit", "AUDITOR", "Internal Audit (read-only)"),
    ("admin", "Platform Admin", "ADMIN", "Platform Administrator"),
]


def _mask_phone(raw: str | None) -> str | None:
    return None if not raw else f"+91 ••••• {mask_tail(raw, 4)[-4:]}"


def _clean(table: str, row: dict) -> dict:
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if table == "employee":
        out["phone_tok"] = tokenise(row.get("_raw_phone"), "phone")
    elif table == "customer":
        out["phone_tok"] = tokenise(row.get("_raw_phone"), "phone")
        out["kyc_tok"] = tokenise(row.get("_raw_kyc"), "kyc")
    elif table == "account":
        out["registered_mobile_tok"] = tokenise(row.get("_raw_mobile"), "phone")
    elif table == "state_change" and row["field"] == "REGISTERED_MOBILE":
        out["old_value"] = _mask_phone(row["old_value"])
        out["new_value"] = _mask_phone(row["new_value"])
    return out


def _adapt(v):
    if isinstance(v, dict):
        return Jsonb(v)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return Jsonb(v)
    return v


def truncate_all() -> None:
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def load_world(world, log=print) -> dict[str, int]:
    counts: dict[str, int] = {}
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for table in TABLE_ORDER:
            rows = [_clean(table, r) for r in world.tables.get(table, [])]
            if not rows:
                continue
            if table == "employee":
                for r in rows:
                    r["declared_relations"] = Jsonb(r["declared_relations"])
            cols = list(rows[0].keys())
            t0 = time.perf_counter()
            with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row([_adapt(r[c]) for c in cols])
            counts[table] = len(rows)
            log(f"  {table:<14} {len(rows):>8,}  ({time.perf_counter() - t0:.1f}s)")
        raw.commit()
    finally:
        raw.close()

    with session_scope() as db:
        for lab in world.labels:
            extra = {k: v for k, v in lab.items() if k not in {
                "key", "scenario", "variant", "title", "typology", "description",
                "differing_fact", "expected", "entities", "events"}}
            db.add(ScenarioLabel(key=lab["key"], scenario=lab["scenario"], variant=lab["variant"],
                                 title=lab["title"], typology=lab["typology"],
                                 description=lab["description"], differing_fact=lab["differing_fact"],
                                 expected=lab["expected"], entities=lab["entities"],
                                 events=lab["events"], extra=extra))
        counts["scenario_label"] = len(world.labels)
    return counts


def seed_users() -> None:
    pwd = hash_password(get_settings().demo_password)
    with session_scope() as db:
        for uid, name, role, title in DEMO_USERS:
            db.merge(AppUser(id=uid, display_name=name, role=role, title=title, password_hash=pwd,
                             branch_scope=[]))
        audit.append(db, "system", "seed.users", payload={"count": len(DEMO_USERS),
                                                           "at": datetime.now(UTC).isoformat()})
