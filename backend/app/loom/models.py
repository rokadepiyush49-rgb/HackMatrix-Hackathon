"""Loom — SUTRA's temporal evidence graph, stored relationally.

Conventions (see docs/adr/003):
- Events carry `occurred_at` (valid time) and `ingested_at` (system time).
- Things with a lifespan carry explicit validity intervals.
- IDs are human-readable strings (EMP-0417, A-5520, TX-…) because investigators read them.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

TS = DateTime(timezone=True)


# ── Organisation & staff ──────────────────────────────────────────────────────


class Branch(Base):
    __tablename__ = "branch"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    pseudonym: Mapped[str] = mapped_column(String(80))
    full_name: Mapped[str] = mapped_column(String(120))  # masked unless an unmask is approved
    branch_id: Mapped[str] = mapped_column(ForeignKey("branch.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    manager_id: Mapped[str | None] = mapped_column(String(16), index=True)
    hire_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    address_norm: Mapped[str] = mapped_column(Text)
    pincode: Mapped[str] = mapped_column(String(8))
    phone_tok: Mapped[str | None] = mapped_column(String(40))
    declared_relations: Mapped[list] = mapped_column(JSONB, default=list)


class Permission(Base):
    __tablename__ = "permission"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    sensitivity: Mapped[str] = mapped_column(String(8))


class Entitlement(Base):
    __tablename__ = "entitlement"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id"))
    permission_code: Mapped[str] = mapped_column(ForeignKey("permission.code"))
    granted_by: Mapped[str | None] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    request_ref: Mapped[str | None] = mapped_column(String(24))
    valid_from: Mapped[datetime] = mapped_column(TS)
    intended_expiry: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (Index("ix_entitlement_emp_from", "employee_id", "valid_from"),)


class Roster(Base):
    __tablename__ = "roster"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id"))
    shift_start: Mapped[datetime] = mapped_column(TS)
    shift_end: Mapped[datetime] = mapped_column(TS)
    duty_type: Mapped[str] = mapped_column(String(16))  # REGULAR | CAMP | OVERTIME
    __table_args__ = (Index("ix_roster_emp_start", "employee_id", "shift_start"),)


# ── Customers, accounts, devices, sessions ────────────────────────────────────


class Customer(Base):
    __tablename__ = "customer"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    name_norm: Mapped[str] = mapped_column(String(120))
    dob: Mapped[date | None] = mapped_column(Date)
    segment: Mapped[str] = mapped_column(String(16), index=True)
    address_norm: Mapped[str] = mapped_column(Text)
    pincode: Mapped[str] = mapped_column(String(8), index=True)
    phone_tok: Mapped[str | None] = mapped_column(String(40), index=True)
    kyc_tok: Mapped[str | None] = mapped_column(String(40))
    rm_employee_id: Mapped[str | None] = mapped_column(String(16), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branch.id"))
    created_at: Mapped[datetime] = mapped_column(TS)


class Account(Base):
    __tablename__ = "account"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # SAVINGS | CURRENT | EXTERNAL
    holder_name: Mapped[str] = mapped_column(String(120))
    bank_name: Mapped[str] = mapped_column(String(80), default="Kestrel UCB")
    branch_id: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    status_since: Mapped[datetime | None] = mapped_column(TS)
    opened_at: Mapped[datetime | None] = mapped_column(TS)
    opened_by: Mapped[str | None] = mapped_column(String(16))
    kyc_approved_by: Mapped[str | None] = mapped_column(String(16))
    opening_mode: Mapped[str | None] = mapped_column(String(20))
    daily_limit_paise: Mapped[int] = mapped_column(BigInteger, default=10_000_000)
    balance_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    registered_mobile_tok: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_account_kyc_opened", "kyc_approved_by", "opened_at"),)


class Device(Base):
    __tablename__ = "device"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    first_seen: Mapped[datetime] = mapped_column(TS)


class Session(Base):
    __tablename__ = "session"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(10))  # EMPLOYEE | CUSTOMER
    actor_id: Mapped[str] = mapped_column(String(16))
    device_id: Mapped[str | None] = mapped_column(String(16), index=True)
    ip: Mapped[str | None] = mapped_column(String(40))
    geo_city: Mapped[str | None] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(TS)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (Index("ix_session_actor_start", "actor_id", "started_at"),)


class AccessEvent(Base):
    __tablename__ = "access_event"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(16), index=True)
    employee_id: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(24))
    account_id: Mapped[str | None] = mapped_column(String(16))
    customer_id: Mapped[str | None] = mapped_column(String(16))
    fields: Mapped[list] = mapped_column(ARRAY(String), default=list)
    override_used: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(TS)
    ingested_at: Mapped[datetime] = mapped_column(TS)
    __table_args__ = (
        Index("ix_access_emp_t", "employee_id", "occurred_at"),
        Index("ix_access_acct_t", "account_id", "occurred_at"),
    )


class StateChange(Base):
    __tablename__ = "state_change"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(16))
    field: Mapped[str] = mapped_column(String(24))
    old_value: Mapped[str | None] = mapped_column(String(80))
    new_value: Mapped[str | None] = mapped_column(String(80))
    actor_type: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[str] = mapped_column(String(16))
    auth_method: Mapped[str] = mapped_column(String(24))
    session_id: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(TS)
    ingested_at: Mapped[datetime] = mapped_column(TS)
    __table_args__ = (Index("ix_state_acct_t", "account_id", "occurred_at"),)


class Beneficiary(Base):
    __tablename__ = "beneficiary"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(16))
    counterparty_account: Mapped[str] = mapped_column(String(16))
    counterparty_name: Mapped[str] = mapped_column(String(120))
    session_id: Mapped[str | None] = mapped_column(String(16))
    added_at: Mapped[datetime] = mapped_column(TS)
    __table_args__ = (Index("ix_benef_acct_t", "account_id", "added_at"),)


class Txn(Base):
    __tablename__ = "txn"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    from_account: Mapped[str] = mapped_column(String(16))
    to_account: Mapped[str] = mapped_column(String(16))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(20))
    narration: Mapped[str | None] = mapped_column(String(120))
    branch_id: Mapped[str | None] = mapped_column(String(16))
    session_id: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(TS)
    ingested_at: Mapped[datetime] = mapped_column(TS)
    __table_args__ = (
        Index("ix_txn_from_t", "from_account", "occurred_at"),
        Index("ix_txn_to_t", "to_account", "occurred_at"),
        Index("ix_txn_t_brin", "occurred_at", postgresql_using="brin"),
    )


class WorkItem(Base):
    __tablename__ = "work_item"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))  # TICKET | QUEUE | CALL | TOKEN | EKYC
    ref: Mapped[str] = mapped_column(String(24))
    customer_id: Mapped[str | None] = mapped_column(String(16), index=True)
    account_id: Mapped[str | None] = mapped_column(String(16), index=True)
    employee_id: Mapped[str | None] = mapped_column(String(16))
    branch_id: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS)
    closed_at: Mapped[datetime | None] = mapped_column(TS)


class Relationship(Base):
    __tablename__ = "relationship"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    src_type: Mapped[str] = mapped_column(String(12))
    src_id: Mapped[str] = mapped_column(String(16), index=True)
    dst_type: Mapped[str] = mapped_column(String(12))
    dst_id: Mapped[str] = mapped_column(String(16), index=True)
    rel_type: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(12))  # DECLARED | ER | DERIVED
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    valid_from: Mapped[datetime | None] = mapped_column(TS)


# ── Reasoning layer: signals → chains → alerts → evidence → cases ─────────────


class Signal(Base):
    __tablename__ = "signal"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    detector: Mapped[str] = mapped_column(String(8), index=True)
    family: Mapped[str] = mapped_column(String(8))
    version: Mapped[str] = mapped_column(String(12))
    entity_refs: Mapped[list] = mapped_column(ARRAY(String), default=list)
    event_refs: Mapped[list] = mapped_column(ARRAY(String), default=list)
    window_start: Mapped[datetime] = mapped_column(TS)
    window_end: Mapped[datetime] = mapped_column(TS)
    strength: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_signal_entities", "entity_refs", postgresql_using="gin"),)


class Explanation(Base):
    __tablename__ = "explanation"
    access_event_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(16), index=True)
    verdict: Mapped[str] = mapped_column(String(12), index=True)
    purpose_ok: Mapped[bool] = mapped_column(Boolean)
    timing_ok: Mapped[bool] = mapped_column(Boolean)
    matches: Mapped[list] = mapped_column(JSONB, default=list)
    checked: Mapped[list] = mapped_column(JSONB, default=list)
    occurred_at: Mapped[datetime] = mapped_column(TS)


class EmployeeBaseline(Base):
    __tablename__ = "employee_baseline"
    employee_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    peer_group: Mapped[str] = mapped_column(String(48))
    sessions_90d: Mapped[int] = mapped_column(Integer)
    after20_sessions: Mapped[int] = mapped_column(Integer)
    peer_after20_share: Mapped[float] = mapped_column(Float)
    hour_rates: Mapped[list] = mapped_column(JSONB)  # 168 personal (shrunk) rates
    peer_hour_rates: Mapped[list] = mapped_column(JSONB)
    alibi_coverage: Mapped[float] = mapped_column(Float, default=1.0)
    accounts_approved_60d: Mapped[int] = mapped_column(Integer, default=0)
    approvals_baseline_60d: Mapped[float] = mapped_column(Float, default=0.0)


class Chain(Base):
    __tablename__ = "chain"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    root_ref: Mapped[str] = mapped_column(String(24))
    employee_id: Mapped[str | None] = mapped_column(String(16), index=True)
    account_id: Mapped[str | None] = mapped_column(String(16))
    first_t: Mapped[datetime] = mapped_column(TS)
    last_t: Mapped[datetime] = mapped_column(TS)
    latency_s: Mapped[int | None] = mapped_column(Integer)
    amount_at_risk_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    classifier_p: Mapped[float | None] = mapped_column(Float)
    contributions: Mapped[list] = mapped_column(JSONB, default=list)
    features: Mapped[dict] = mapped_column(JSONB, default=dict)
    entity_refs: Mapped[list] = mapped_column(ARRAY(String), default=list)


class ChainLink(Base):
    __tablename__ = "chain_link"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    chain_id: Mapped[str] = mapped_column(ForeignKey("chain.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(24))
    t: Mapped[datetime] = mapped_column(TS)
    title: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text)
    lane: Mapped[str] = mapped_column(String(8))  # IAM | SOC | FRAUD | AML
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    evidence_codes: Mapped[list] = mapped_column(ARRAY(String), default=list)
    alibi: Mapped[dict | None] = mapped_column(JSONB)


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    chain_id: Mapped[str] = mapped_column(ForeignKey("chain.id", ondelete="CASCADE"), index=True)
    typology: Mapped[str] = mapped_column(String(40))
    claim: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), index=True)
    lattice_rule: Mapped[str] = mapped_column(Text)
    dims: Mapped[list] = mapped_column(JSONB)
    argument: Mapped[dict] = mapped_column(JSONB)
    recoverable: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(20), index=True, default="OPEN")
    assignee: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TS)
    scenario_tag: Mapped[str | None] = mapped_column(String(40))


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # {alert_id}:{code}
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str] = mapped_column(Text)
    source_system: Mapped[str] = mapped_column(String(40))
    source_table: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[str] = mapped_column(String(40))
    reliability: Mapped[str] = mapped_column(String(1))
    credibility: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(TS)
    ingested_at: Mapped[datetime] = mapped_column(TS)
    entities: Mapped[list] = mapped_column(ARRAY(String), default=list)
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    supports: Mapped[list] = mapped_column(ARRAY(String), default=list)
    rebuts: Mapped[list] = mapped_column(ARRAY(String), default=list)
    sha256: Mapped[str] = mapped_column(String(64))


class Case(Base):
    __tablename__ = "case_file"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), index=True)
    priority: Mapped[str] = mapped_column(String(10))
    assignee: Mapped[str | None] = mapped_column(String(32))
    reviewer: Mapped[str | None] = mapped_column(String(32))
    sla_due_at: Mapped[datetime | None] = mapped_column(TS)
    decision: Mapped[str | None] = mapped_column(String(24))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    subject_response: Mapped[str | None] = mapped_column(Text)
    recommended_controls: Mapped[list] = mapped_column(JSONB, default=list)
    opened_at: Mapped[datetime] = mapped_column(TS)
    closed_at: Mapped[datetime | None] = mapped_column(TS)


class CaseNote(Base):
    __tablename__ = "case_note"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("case_file.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(ARRAY(String), default=list)
    created_at: Mapped[datetime] = mapped_column(TS)


class EvidencePack(Base):
    __tablename__ = "evidence_pack"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("case_file.id", ondelete="CASCADE"), index=True)
    manifest: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TS)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[str | None] = mapped_column(String(32))


class ModelPrediction(Base):
    __tablename__ = "model_prediction"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[str] = mapped_column(String(16))
    entity_ref: Mapped[str] = mapped_column(String(24), index=True)
    p: Mapped[float] = mapped_column(Float)
    contributions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(TS)


class ScenarioRun(Base):
    __tablename__ = "scenario_run"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    results: Mapped[dict] = mapped_column(JSONB, default=dict)


# ── Platform: users, unmasking, audit ─────────────────────────────────────────


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(80))
    branch_scope: Mapped[list] = mapped_column(ARRAY(String), default=list)


class UnmaskRequest(Base):
    __tablename__ = "unmask_request"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(16), index=True)
    case_id: Mapped[str | None] = mapped_column(String(24))
    requested_by: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))  # PENDING | APPROVED | REJECTED
    approved_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TS)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    expires_at: Mapped[datetime | None] = mapped_column(TS)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(TS, index=True)
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class ScenarioLabel(Base):
    """Ground truth from Kestrel-Sim: what was injected and what SUTRA should conclude."""

    __tablename__ = "scenario_label"
    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    scenario: Mapped[str] = mapped_column(String(4), index=True)
    variant: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(120))
    typology: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text)
    differing_fact: Mapped[str | None] = mapped_column(Text)
    expected: Mapped[dict] = mapped_column(JSONB, default=dict)
    entities: Mapped[list] = mapped_column(ARRAY(String), default=list)
    events: Mapped[list] = mapped_column(ARRAY(String), default=list)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
