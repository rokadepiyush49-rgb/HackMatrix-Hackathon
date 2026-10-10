"""Kestrel Bank — a working mock of the bank's own systems, for testing SUTRA by hand (demo mode only).

A person signs in to the staff core-banking console or to customer NetBanking and does what a real
user would: search a customer, open an account, change the registered mobile, raise a limit, take
over on a new phone, add payees, send money. Each action writes the rows the bank's systems would
record — the VPN or SSO session, the core-banking access audit, state changes, tickets and eKYC, the
device registry, payees and transfers — and they reach Loom at once, the way a change-data-capture
feed would deliver them (strand "bank", reversible like the rest of the live feed).

SUTRA is not consulted here. The bank enforces only what a bank of this kind would: permissions
(including a temporary override nobody revoked), balances and daily limits. Whether any of it is
suspicious is for the detection run to decide.

The bank runs on its own clock, set within 22 Sep 2026 so new activity sits at the end of the
synthetic 90-day window that every baseline was learned from.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from sqlalchemy import Connection, text

from app.core.pii import tokenise
from app.loom import feed
from app.loom.compose import Ids, describe, source_system

DAY_START = datetime.fromisoformat("2026-09-22T00:00:00+05:30")
DAY_END = datetime.fromisoformat("2026-09-22T23:59:00+05:30")
OVERRIDE = "MOBILE_UPDATE_OVERRIDE"


LABEL = "MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY"


class BankError(ValueError):
    """What the bank's own screens would say, with a machine-readable code (INSUFFICIENT_FUNDS, …)."""

    def __init__(self, message: str, code: str = "REJECTED"):
        super().__init__(message)
        self.code = code


# ── the bank's clock ────────────────────────────────────────────────────────

# Bank time runs at wall-clock speed, and every action also moves it on by the time that action takes
# (an OTP, a form, a transfer), so what a person clicks through in two minutes reads like a real
# evening, and two actions never share a timestamp.
_clock = {"bank": datetime.fromisoformat("2026-09-22T20:45:00+05:30"), "real": time.time()}
STEP = {"login": 20, "search": 35, "view": 50, "ticket": 90, "ekyc": 120, "mobile": 150, "limit": 110, "grant": 5,
        "roster": 5, "customer_login": 240, "password": 45, "payee": 75, "transfer": 95}


def _resume() -> None:
    """After an API restart, carry on from the bank's latest record instead of rewinding the clock."""
    if _clock.get("resumed"):
        return
    _clock["resumed"] = True
    from app.core.db import engine

    try:
        with engine.connect() as c:
            last = c.execute(text("SELECT max(t) FROM feed_event WHERE strand = 'bank'")).scalar()
    except Exception:  # noqa: BLE001 — no database yet: keep the default evening
        return
    if last and last > _clock["bank"]:
        _clock.update(bank=last + timedelta(seconds=30), real=time.time())


def now() -> datetime:
    _resume()
    t = _clock["bank"] + timedelta(seconds=time.time() - _clock["real"])
    return t.replace(microsecond=0)


def clock() -> dict:
    t = now()
    return {"now": t.isoformat(), "day": "2026-09-22", "open": t <= DAY_END}


def set_clock(hhmm: str) -> dict:
    t = datetime.fromisoformat(f"2026-09-22T{hhmm}:00+05:30")
    _clock.update(bank=t, real=time.time(), resumed=True)
    return clock()


def advance(minutes: int) -> dict:
    _clock.update(bank=now() + timedelta(minutes=minutes), real=time.time())
    return clock()


def _tick(action: str) -> datetime:
    t = now() + timedelta(seconds=STEP.get(action, 30))
    if t > DAY_END:
        raise BankError("The bank day (22 Sep) has ended. Set the bank clock back to keep testing.", "BANK_DAY_OVER")
    _clock.update(bank=t, real=time.time())
    return t


def inr(paise: int) -> str:
    """₹ with Indian digit grouping: 500000 rupees → ₹5,00,000."""
    r = str(int(round(paise / 100)))
    head, tail = r[:-3], r[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join([g for g in [head, *groups] if g] + [tail]) if head or groups else f"₹{tail}"


def _lag(t: datetime, s: int = 12) -> str:
    return (t + timedelta(seconds=s)).isoformat()


# ── writing a record ────────────────────────────────────────────────────────


def _record(conn: Connection, table: str, row: dict, t: datetime, effect: dict | None = None) -> dict:
    """Hand one row to SUTRA's ingest: logged as a feed row (strand "bank") and applied straight away."""
    accounts = [a for a in (row.get("from_account"), row.get("to_account"), row.get("counterparty_account")) if a]
    holders = dict(conn.execute(text("SELECT id, holder_name FROM account WHERE id = ANY(:a)"), {"a": accounts}).all())
    seq = conn.execute(text("SELECT coalesce(max(seq), 0) + 1 FROM feed_event")).scalar()
    item = feed.Item(seq, t, table, row["id"], source_system(table, row), describe(table, row, holders), row, effect)
    conn.execute(text("INSERT INTO feed_event (seq, t, source_table, ref, system, summary, row, effect, strand) "
                      "VALUES (:seq, :t, :table, :ref, :system, :summary, CAST(:row AS jsonb), CAST(:effect AS jsonb), 'bank')"),
                 {"seq": seq, "t": t, "table": table, "ref": row["id"], "system": item.system, "summary": item.summary,
                  "row": json.dumps(row), "effect": json.dumps(effect) if effect else None})
    feed.ingest(conn, item)
    return item.public()


# ── who is who ──────────────────────────────────────────────────────────────


def staff_directory(conn: Connection) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text("""
        SELECT e.id, e.pseudonym, e.role, e.branch_id, b.name AS branch, b.city
        FROM employee e JOIN branch b ON b.id = e.branch_id
        WHERE e.role IN ('OPS_OFFICER', 'BRANCH_MANAGER') AND e.status = 'ACTIVE' ORDER BY e.branch_id, e.role, e.id"""))]


def _employee(conn: Connection, employee_id: str):
    emp = conn.execute(text("SELECT e.*, b.city, b.name AS branch FROM employee e JOIN branch b ON b.id = e.branch_id "
                            "WHERE e.id = :e"), {"e": employee_id}).first()
    if emp is None:
        raise BankError(f"No employee {employee_id}.", "NOT_FOUND")
    return emp


def permissions(conn: Connection, employee_id: str, at: datetime) -> list[dict]:
    """Every grant in force at `at`. A temporary grant stays in force until someone revokes it."""
    rows = conn.execute(text("""
        SELECT en.permission_code, p.name, en.valid_from, en.intended_expiry, en.request_ref, en.reason
        FROM entitlement en JOIN permission p ON p.code = en.permission_code
        WHERE en.employee_id = :e AND en.valid_from <= :t AND en.revoked_at IS NULL ORDER BY en.permission_code"""),
        {"e": employee_id, "t": at}).all()
    return [{"code": r.permission_code, "name": r.name, "temporary": r.intended_expiry is not None,
             "since": r.valid_from.isoformat(), "intended_expiry": r.intended_expiry.isoformat() if r.intended_expiry else None,
             "past_expiry": bool(r.intended_expiry and r.intended_expiry < at), "request_ref": r.request_ref, "reason": r.reason}
            for r in rows]


def _has(conn: Connection, employee_id: str, code: str, at: datetime) -> dict | None:
    return next((p for p in permissions(conn, employee_id, at) if p["code"] == code), None)


def _device_for(conn: Connection, actor: str, channel: str) -> str | None:
    return conn.execute(text("SELECT device_id FROM session WHERE actor_id = :a AND channel = :c AND device_id IS NOT NULL "
                             "ORDER BY started_at DESC LIMIT 1"), {"a": actor, "c": channel}).scalar()


# ── staff console ───────────────────────────────────────────────────────────


def staff_login(conn: Connection, employee_id: str, channel: str) -> dict:
    t = _tick("login")
    emp = _employee(conn, employee_id)
    device = (_device_for(conn, emp.id, "VPN") or f"LAP-{emp.id[-4:]}") if channel == "VPN" else _device_for(conn, emp.id, "BRANCH")
    ids = Ids(conn)
    sid = ids.take("session", "S", 6)
    rec = _record(conn, "session", {"id": sid, "actor_type": "EMPLOYEE", "actor_id": emp.id, "device_id": device,
                                    "ip": "49.36.88.17" if channel == "VPN" else "10.14.2.31", "geo_city": emp.city,
                                    "channel": channel, "started_at": t.isoformat(),
                                    "ended_at": (t + timedelta(minutes=45)).isoformat()}, t)
    return {"session_id": sid, "device": device, "record": rec}


def staff_overview(conn: Connection, employee_id: str) -> dict:
    t = now()
    emp = _employee(conn, employee_id)
    roster = [dict(r._mapping) for r in conn.execute(text("""
        SELECT duty_type, shift_start, shift_end FROM roster WHERE employee_id = :e
        AND shift_start < :end AND shift_end > :start ORDER BY shift_start"""),
        {"e": employee_id, "start": DAY_START, "end": DAY_END})]
    on_duty = any(r["shift_start"] <= t <= r["shift_end"] for r in roster)
    return {"employee": {"id": emp.id, "pseudonym": emp.pseudonym, "role": emp.role, "branch_id": emp.branch_id,
                         "branch": emp.branch, "city": emp.city},
            "permissions": permissions(conn, employee_id, t),
            "roster": [{"duty": r["duty_type"], "start": r["shift_start"].isoformat(), "end": r["shift_end"].isoformat()}
                       for r in roster],
            "on_duty": on_duty, "clock": clock()}


def grant_override(conn: Connection, employee_id: str, mode: str) -> dict:
    """Branch manager's setup action: a temporary mobile-update override, current or long past its expiry."""
    t = _tick("grant")
    emp = _employee(conn, employee_id)
    granted = t.replace(hour=11, minute=5, second=0) - (timedelta(days=6) if mode == "expired" else timedelta(0))
    if granted > t:
        granted = t - timedelta(minutes=5)
    row = {"id": Ids(conn).take("entitlement", "ENT", 5), "employee_id": emp.id, "permission_code": OVERRIDE,
           "granted_by": emp.manager_id, "reason": "Pension camp — bulk mobile updates for senior citizens",
           "request_ref": f"REQ-{4000 + int(t.timestamp()) % 5000}", "valid_from": granted.isoformat(),
           "intended_expiry": (granted + timedelta(days=2)).replace(hour=23, minute=59).isoformat(), "revoked_at": None}
    return _record(conn, "entitlement", row, granted)


def roster_camp(conn: Connection, employee_id: str, start: str, end: str) -> dict:
    _tick("roster")
    _employee(conn, employee_id)
    s = datetime.fromisoformat(f"2026-09-22T{start}:00+05:30")
    e = datetime.fromisoformat(f"2026-09-22T{end}:00+05:30")
    if e <= s:
        raise BankError("The shift must end after it starts.", "INVALID_REQUEST")
    row = {"id": Ids(conn).take("roster", "RS", 6), "employee_id": employee_id, "shift_start": s.isoformat(),
           "shift_end": e.isoformat(), "duty_type": "CAMP"}
    return _record(conn, "roster", row, s)


def search(conn: Connection, q: str) -> list[dict]:
    q = q.strip()
    if len(q) < 2:
        return []
    rows = conn.execute(text("""
        SELECT DISTINCT ON (c.id) c.id, c.full_name, c.segment, c.branch_id, a.id AS account_id, a.status, a.kind
        FROM customer c JOIN account a ON a.customer_id = c.id
        WHERE c.id ILIKE :p OR a.id ILIKE :p OR c.full_name ILIKE :w
        ORDER BY c.id, (a.status = 'INOPERATIVE') DESC LIMIT 12"""), {"p": f"{q}%", "w": f"%{q}%"}).all()
    return [dict(r._mapping) for r in rows]


def _access(conn: Connection, employee_id: str, sid: str, action: str, t: datetime, account_id: str | None,
            customer_id: str | None, fields: list[str], override: bool = False) -> dict:
    row = {"id": Ids(conn).take("access_event", "AE", 7), "session_id": sid, "employee_id": employee_id, "action": action,
           "account_id": account_id, "customer_id": customer_id, "fields": fields, "override_used": override,
           "occurred_at": t.isoformat(), "ingested_at": _lag(t)}
    return _record(conn, "access_event", row, t)


def open_customer(conn: Connection, employee_id: str, sid: str, customer_id: str) -> dict:
    t = _tick("search")
    c = conn.execute(text("SELECT id, full_name, segment, branch_id, created_at FROM customer WHERE id = :c"),
                     {"c": customer_id}).first()
    if c is None:
        raise BankError(f"No customer {customer_id}.", "CUSTOMER_NOT_FOUND")
    rec = _access(conn, employee_id, sid, "CUST_SEARCH", t, None, c.id, [])
    accounts = [dict(r._mapping) for r in conn.execute(text(
        "SELECT id, kind, status, branch_id, balance_paise / 100 AS balance FROM account WHERE customer_id = :c ORDER BY opened_at"),
        {"c": c.id})]
    return {"customer": {"id": c.id, "name": c.full_name, "segment": c.segment, "branch_id": c.branch_id,
                         "since": c.created_at.isoformat()}, "accounts": accounts, "record": rec}


def _mobile_on_file(conn: Connection, account_id: str) -> str:
    return conn.execute(text("SELECT new_value FROM state_change WHERE account_id = :a AND field = 'REGISTERED_MOBILE' "
                             "ORDER BY occurred_at DESC LIMIT 1"), {"a": account_id}).scalar() or "on file (masked)"


def account_view(conn: Connection, account_id: str) -> dict:
    a = conn.execute(text("SELECT a.*, c.full_name, c.segment FROM account a JOIN customer c ON c.id = a.customer_id "
                          "WHERE a.id = :a"), {"a": account_id}).first()
    if a is None:
        raise BankError(f"No customer account {account_id}.", "ACCOUNT_NOT_FOUND")
    last = conn.execute(text("SELECT max(occurred_at) FROM txn WHERE from_account = :a OR to_account = :a"), {"a": a.id}).scalar()
    txns = conn.execute(text("""
        SELECT id, occurred_at AS at, from_account, to_account, amount_paise, channel, narration FROM txn
        WHERE from_account = :a OR to_account = :a ORDER BY occurred_at DESC LIMIT 8"""), {"a": a.id}).all()
    payees = conn.execute(text("SELECT counterparty_account, counterparty_name, added_at FROM beneficiary WHERE account_id = :a "
                               "ORDER BY added_at DESC"), {"a": a.id}).all()
    return {"id": a.id, "customer_id": a.customer_id, "holder": a.full_name, "segment": a.segment, "kind": a.kind,
            "status": a.status, "status_since": a.status_since.isoformat() if a.status_since else None,
            "branch_id": a.branch_id, "balance": a.balance_paise / 100, "daily_limit": a.daily_limit_paise / 100,
            "mobile": _mobile_on_file(conn, a.id), "last_activity": last.isoformat() if last else None,
            "transactions": [{"id": r.id, "t": r.at.isoformat(), "from": r.from_account, "to": r.to_account,
                              "amount": r.amount_paise / 100, "channel": r.channel, "narration": r.narration} for r in txns],
            "payees": [{"account": p.counterparty_account, "name": p.counterparty_name, "since": p.added_at.isoformat()}
                       for p in payees]}


def open_account(conn: Connection, employee_id: str, sid: str, account_id: str) -> dict:
    t = _tick("view")
    view = account_view(conn, account_id)
    rec = _access(conn, employee_id, sid, "ACCT_VIEW", t, view["id"], view["customer_id"], ["balance", "registered_mobile", "nominee"])
    return {**view, "record": rec}


def raise_ticket(conn: Connection, employee_id: str, account_id: str, note: str) -> dict:
    t = _tick("ticket")
    emp = _employee(conn, employee_id)
    view = account_view(conn, account_id)
    row = {"id": Ids(conn).take("work_item", "WI", 6), "kind": "TICKET", "ref": f"SR-{7000 + int(t.timestamp()) % 3000}",
           "customer_id": view["customer_id"], "account_id": view["id"], "employee_id": emp.id, "branch_id": emp.branch_id,
           "text": note.strip()[:200] or "Customer request", "created_at": t.isoformat(),
           "closed_at": (t + timedelta(minutes=30)).isoformat()}
    return _record(conn, "work_item", row, t)


def capture_ekyc(conn: Connection, employee_id: str, account_id: str) -> dict:
    t = _tick("ekyc")
    emp = _employee(conn, employee_id)
    view = account_view(conn, account_id)
    row = {"id": Ids(conn).take("work_item", "WI", 6), "kind": "EKYC", "ref": f"EKYC-{100000 + int(t.timestamp()) % 900000}",
           "customer_id": view["customer_id"], "account_id": view["id"], "employee_id": emp.id, "branch_id": emp.branch_id,
           "text": "Aadhaar biometric eKYC — success", "created_at": t.isoformat(),
           "closed_at": (t + timedelta(minutes=2)).isoformat()}
    return _record(conn, "work_item", row, t)


def _recent_ekyc(conn: Connection, account_id: str, t: datetime) -> bool:
    return bool(conn.execute(text("SELECT 1 FROM work_item WHERE account_id = :a AND kind = 'EKYC' "
                                  "AND created_at BETWEEN :s AND :t LIMIT 1"),
                             {"a": account_id, "s": t - timedelta(minutes=20), "t": t}).first())


def update_mobile(conn: Connection, employee_id: str, sid: str, account_id: str, new_mobile: str, auth: str) -> list[dict]:
    t = _tick("mobile")
    digits = "".join(ch for ch in new_mobile if ch.isdigit())[-10:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise BankError("Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9.", "INVALID_REQUEST")
    if not _has(conn, employee_id, "MOBILE_UPDATE", t) and not _has(conn, employee_id, OVERRIDE, t):
        raise BankError("Your role cannot change a registered mobile.", "NOT_PERMITTED")
    if auth == "OVERRIDE" and not _has(conn, employee_id, OVERRIDE, t):
        raise BankError("You hold no override. A branch manager has to grant one first.", "NOT_PERMITTED")
    if auth == "BIOMETRIC" and not _recent_ekyc(conn, account_id, t):
        raise BankError("No biometric eKYC for this customer in the last 20 minutes. Capture one first.", "NOT_PERMITTED")
    acct = conn.execute(text("SELECT id, customer_id, registered_mobile_tok FROM account WHERE id = :a"), {"a": account_id}).first()
    if acct is None:
        raise BankError(f"No customer account {account_id}.", "ACCOUNT_NOT_FOUND")
    raw = f"+91{digits}"
    override = auth == "OVERRIDE"
    recs = [_access(conn, employee_id, sid, "MOBILE_UPDATE", t, acct.id, acct.customer_id, ["registered_mobile"], override)]
    row = {"id": Ids(conn).take("state_change", "SC", 6), "account_id": acct.id, "field": "REGISTERED_MOBILE",
           "old_value": _mobile_on_file(conn, acct.id), "new_value": f"+91 ••••• {digits[-4:]}", "actor_type": "EMPLOYEE",
           "actor_id": employee_id, "auth_method": auth, "session_id": sid, "occurred_at": t.isoformat(), "ingested_at": _lag(t)}
    recs.append(_record(conn, "state_change", row, t, {"account_id": acct.id, "column": "registered_mobile_tok",
                                                       "old": acct.registered_mobile_tok, "new": tokenise(raw, "phone")}))
    return recs


def change_limit(conn: Connection, employee_id: str, sid: str, account_id: str, limit: int, use_override: bool) -> list[dict]:
    t = _tick("limit")
    if not 10_000 <= limit <= 50_00_000:
        raise BankError("Set a transaction limit between ₹10,000 and ₹50,00,000.", "INVALID_REQUEST")
    if not _has(conn, employee_id, "LIMIT_CHANGE", t):
        raise BankError("Your role cannot change transfer limits.", "NOT_PERMITTED")
    if use_override and not _has(conn, employee_id, OVERRIDE, t):
        raise BankError("You hold no override. A branch manager has to grant one first.", "NOT_PERMITTED")
    acct = conn.execute(text("SELECT id, customer_id, daily_limit_paise FROM account WHERE id = :a"), {"a": account_id}).first()
    if acct is None:
        raise BankError(f"No customer account {account_id}.", "ACCOUNT_NOT_FOUND")
    recs = [_access(conn, employee_id, sid, "LIMIT_CHANGE", t, acct.id, acct.customer_id, ["txn_limit"], use_override)]
    row = {"id": Ids(conn).take("state_change", "SC", 6), "account_id": acct.id, "field": "TXN_LIMIT",
           "old_value": str(acct.daily_limit_paise), "new_value": str(limit * 100), "actor_type": "EMPLOYEE",
           "actor_id": employee_id, "auth_method": "OVERRIDE" if use_override else "MAKER_ONLY", "session_id": sid,
           "occurred_at": t.isoformat(), "ingested_at": _lag(t)}
    recs.append(_record(conn, "state_change", row, t, {"account_id": acct.id, "column": "daily_limit_paise",
                                                       "old": acct.daily_limit_paise, "new": limit * 100}))
    return recs


# ── customer NetBanking ─────────────────────────────────────────────────────


def customer_directory(conn: Connection, q: str = "") -> list[dict]:
    """Who you can sign in as. Dormant accounts and the 21 Sep ring's accounts first, then a search."""
    q = q.strip()
    rows = conn.execute(text("""
        SELECT c.id, c.full_name, c.segment, a.id AS account_id, a.status, a.balance_paise / 100 AS balance,
               coalesce((SELECT sc.new_value FROM state_change sc WHERE sc.account_id = a.id AND sc.field = 'REGISTERED_MOBILE'
                         ORDER BY sc.occurred_at DESC LIMIT 1), 'on file (masked)') AS mobile
        FROM customer c JOIN account a ON a.customer_id = c.id
        WHERE a.kind <> 'EXTERNAL' AND (
              (:q = '' AND (a.status = 'INOPERATIVE' OR a.id IN ('A-7731', 'A-7768', 'A-6604')))
           OR (:q <> '' AND (c.id ILIKE :p OR a.id ILIKE :p OR c.full_name ILIKE :w)))
        ORDER BY (a.id IN ('A-7731', 'A-7768', 'A-6604')), a.balance_paise DESC LIMIT 15"""),
        {"q": q, "p": f"{q}%", "w": f"%{q}%"}).all()
    return [dict(r._mapping) for r in rows]


def customer_login(conn: Connection, customer_id: str, new_device: bool, city: str | None = None) -> dict:
    t = _tick("customer_login")
    c = conn.execute(text("SELECT c.id, c.full_name, b.city FROM customer c JOIN branch b ON b.id = c.branch_id WHERE c.id = :c"),
                     {"c": customer_id}).first()
    if c is None:
        raise BankError(f"No customer {customer_id}.", "CUSTOMER_NOT_FOUND")
    ids = Ids(conn)
    recs = []
    if new_device:
        dev = f"D-{(int(t.timestamp()) * 2654435761) % 0xEFFF + 0x1000:04X}"
        while conn.execute(text("SELECT 1 FROM device WHERE id = :d UNION SELECT 1 FROM feed_event WHERE ref = :d"), {"d": dev}).first():
            dev = f"D-{(int(dev[2:], 16) + 7) % 0xEFFF + 0x1000:04X}"
        recs.append(_record(conn, "device", {"id": dev, "fingerprint": f"{abs(hash((dev, t.isoformat()))):016x}"[:16],
                                             "kind": "ANDROID", "first_seen": t.isoformat()}, t))
        channel = "NETBANKING"
    else:
        dev = conn.execute(text("SELECT device_id FROM session WHERE actor_id = :c AND device_id IS NOT NULL "
                                "ORDER BY started_at DESC LIMIT 1"), {"c": c.id}).scalar()
        channel = "MOBILE"
    sid = ids.take("session", "S", 6)
    recs.append(_record(conn, "session", {"id": sid, "actor_type": "CUSTOMER", "actor_id": c.id, "device_id": dev,
                                          "ip": "106.51.7.42" if new_device else "49.36.120.9", "geo_city": city or c.city,
                                          "channel": channel, "started_at": t.isoformat(),
                                          "ended_at": (t + timedelta(minutes=40)).isoformat()}, t))
    acct = conn.execute(text("SELECT id FROM account WHERE customer_id = :c ORDER BY opened_at LIMIT 1"), {"c": c.id}).scalar()
    return {"session_id": sid, "device": dev, "new_device": new_device, "otp_to": _mobile_on_file(conn, acct) if acct else "—",
            "records": recs}


def customer_overview(conn: Connection, customer_id: str) -> dict:
    t = now()
    c = conn.execute(text("SELECT id, full_name, segment FROM customer WHERE id = :c"), {"c": customer_id}).first()
    if c is None:
        raise BankError(f"No customer {customer_id}.", "CUSTOMER_NOT_FOUND")
    accounts = []
    for (aid,) in conn.execute(text("SELECT id FROM account WHERE customer_id = :c ORDER BY opened_at"), {"c": c.id}).all():
        view = account_view(conn, aid)
        spent = conn.execute(text("SELECT coalesce(sum(amount_paise), 0) FROM txn WHERE from_account = :a "
                                  "AND occurred_at >= :d AND occurred_at <= :t"), {"a": aid, "d": DAY_START, "t": t}).scalar()
        accounts.append({**view, "spent_today": spent / 100})
    return {"customer": {"id": c.id, "name": c.full_name, "segment": c.segment}, "accounts": accounts, "clock": clock()}


def reset_password(conn: Connection, customer_id: str, sid: str) -> dict:
    t = _tick("password")
    acct = conn.execute(text("SELECT id FROM account WHERE customer_id = :c ORDER BY opened_at LIMIT 1"), {"c": customer_id}).scalar()
    changed = conn.execute(text("SELECT 1 FROM state_change WHERE account_id = :a AND field = 'REGISTERED_MOBILE' "
                                "AND occurred_at >= :s"), {"a": acct, "s": t - timedelta(hours=24)}).first()
    row = {"id": Ids(conn).take("state_change", "SC", 6), "account_id": acct, "field": "PASSWORD", "old_value": "—",
           "new_value": "reset", "actor_type": "CUSTOMER", "actor_id": customer_id,
           "auth_method": "OTP_NEW_NUMBER" if changed else "OTP", "session_id": sid,
           "occurred_at": t.isoformat(), "ingested_at": _lag(t)}
    return _record(conn, "state_change", row, t)


def payee_directory(conn: Connection, q: str = "") -> list[dict]:
    q = q.strip()
    rows = conn.execute(text("""
        SELECT id, holder_name, kind, bank_name FROM account
        WHERE (:q = '' AND (id IN ('A-7731', 'A-7768') OR (kind = 'EXTERNAL' AND id ~ '^X-[0-9]{4}$')))
           OR (:q <> '' AND (id ILIKE :p OR holder_name ILIKE :w))
        ORDER BY (id IN ('A-7731', 'A-7768')) DESC, md5(id) LIMIT 10"""), {"q": q, "p": f"{q}%", "w": f"%{q}%"}).all()
    return [{"account": r.id, "name": r.holder_name, "bank": r.bank_name, "internal": r.kind != "EXTERNAL"} for r in rows]


def add_payee(conn: Connection, customer_id: str, sid: str, account_id: str, counterparty: str) -> dict:
    t = _tick("payee")
    own = conn.execute(text("SELECT 1 FROM account WHERE id = :a AND customer_id = :c"), {"a": account_id, "c": customer_id}).first()
    if not own:
        raise BankError("That is not your account.", "NOT_YOUR_ACCOUNT")
    cp = conn.execute(text("SELECT id, holder_name FROM account WHERE id = :a"), {"a": counterparty.strip().upper()}).first()
    if cp is None:
        raise BankError(f"No account {counterparty} at any bank we can reach.", "ACCOUNT_NOT_FOUND")
    if cp.id == account_id:
        raise BankError("You cannot add your own account as a payee.", "INVALID_REQUEST")
    if conn.execute(text("SELECT 1 FROM beneficiary WHERE account_id = :a AND counterparty_account = :c"),
                    {"a": account_id, "c": cp.id}).first():
        raise BankError(f"{cp.holder_name} is already a payee.", "DUPLICATE_PAYEE")
    row = {"id": Ids(conn).take("beneficiary", "BN", 6), "account_id": account_id, "counterparty_account": cp.id,
           "counterparty_name": cp.holder_name, "session_id": sid, "added_at": t.isoformat()}
    return _record(conn, "beneficiary", row, t)


def transfer(conn: Connection, customer_id: str, sid: str, account_id: str, to: str, amount: int, channel: str) -> dict:
    t = _tick("transfer")
    a = conn.execute(text("SELECT id, balance_paise, daily_limit_paise, status FROM account WHERE id = :a AND customer_id = :c"),
                     {"a": account_id, "c": customer_id}).first()
    if a is None:
        raise BankError("That is not your account.", "NOT_YOUR_ACCOUNT")
    if a.status == "BLOCKED":
        raise BankError(f"{a.id} is blocked. No money can leave it until the branch unblocks it.", "ACCOUNT_BLOCKED")
    dest = conn.execute(text("SELECT status FROM account WHERE id = :a"), {"a": to}).first()
    if dest is None:
        raise BankError(f"No account {to} at any bank we can reach.", "ACCOUNT_NOT_FOUND")
    if dest.status == "BLOCKED":
        raise BankError(f"{to} is blocked and cannot receive money.", "ACCOUNT_BLOCKED")
    if amount < 1 or amount > 25_00_000:
        raise BankError("Enter an amount between ₹1 and ₹25,00,000.", "INVALID_REQUEST")
    if not conn.execute(text("SELECT 1 FROM beneficiary WHERE account_id = :a AND counterparty_account = :c"),
                        {"a": a.id, "c": to}).first():
        raise BankError("Add this account as a payee before sending money to it.", "PAYEE_NOT_REGISTERED")
    paise = amount * 100
    if paise > a.balance_paise:
        raise BankError(f"Insufficient balance: {inr(a.balance_paise)} available.", "INSUFFICIENT_FUNDS")
    # The limit is per transaction, as in the core banking system the scenarios model (control C7).
    if paise > a.daily_limit_paise:
        raise BankError(f"This is above the account's transaction limit of {inr(a.daily_limit_paise)}. "
                        "Only the branch can change the limit.", "LIMIT_EXCEEDED")
    row = {"id": Ids(conn).take("txn", "TX", 7), "from_account": a.id, "to_account": to, "amount_paise": paise,
           "channel": channel, "kind": "TRANSFER", "narration": f"{channel} transfer", "branch_id": None,
           "session_id": sid, "occurred_at": t.isoformat(), "ingested_at": _lag(t, 3)}
    return _record(conn, "txn", row, t)


def activity(conn: Connection, limit: int = 40) -> list[dict]:
    """What the bank's systems have recorded so far (newest first) — the same rows SUTRA ingests."""
    rows = conn.execute(text("SELECT seq, t AS at, source_table, ref, system, summary FROM feed_event WHERE strand = 'bank' "
                             "ORDER BY seq DESC LIMIT :n"), {"n": limit}).all()
    return [{"seq": r.seq, "t": r.at.isoformat(), "table": r.source_table, "ref": r.ref, "system": r.system,
             "summary": r.summary} for r in rows]


# ── account status, inbound money, and the plain JSON views ─────────────────


def set_blocked(conn: Connection, account_id: str, blocked: bool) -> dict:
    """The branch blocks (or unblocks) an account in core banking. Recorded like any other state change."""
    t = _tick("limit")
    a = conn.execute(text("SELECT id, status, branch_id, status_since FROM account WHERE id = :a AND kind <> 'EXTERNAL'"),
                     {"a": account_id}).first()
    if a is None:
        raise BankError(f"No customer account {account_id}.", "ACCOUNT_NOT_FOUND")
    if blocked == (a.status == "BLOCKED"):
        raise BankError(f"{a.id} is already {'blocked' if blocked else 'not blocked'}.", "INVALID_REQUEST")
    before = a.status
    if blocked:
        after = "BLOCKED"
    else:  # back to what it was before the block
        after = conn.execute(text("SELECT old_value FROM state_change WHERE account_id = :a AND field = 'STATUS' "
                                  "AND new_value = 'BLOCKED' ORDER BY occurred_at DESC LIMIT 1"), {"a": a.id}).scalar() or "ACTIVE"
    manager = conn.execute(text("SELECT id FROM employee WHERE branch_id = :b AND role = 'BRANCH_MANAGER' LIMIT 1"),
                           {"b": a.branch_id}).scalar()
    row = {"id": Ids(conn).take("state_change", "SC", 6), "account_id": a.id, "field": "STATUS", "old_value": before,
           "new_value": after, "actor_type": "EMPLOYEE", "actor_id": manager or "SYSTEM", "auth_method": "MAKER_CHECKER",
           "session_id": None, "occurred_at": t.isoformat(), "ingested_at": _lag(t)}
    return _record(conn, "state_change", row, t, {"account_id": a.id, "column": "status", "old": before, "new": after})


def receive(conn: Connection, account_id: str, from_account: str, amount: int, channel: str = "IMPS") -> dict:
    """Money arriving from another bank through the payment switch."""
    t = _tick("payee")
    a = conn.execute(text("SELECT id, status FROM account WHERE id = :a AND kind <> 'EXTERNAL'"), {"a": account_id}).first()
    if a is None:
        raise BankError(f"No customer account {account_id}.", "ACCOUNT_NOT_FOUND")
    if a.status == "BLOCKED":
        raise BankError(f"{a.id} is blocked and cannot receive money.", "ACCOUNT_BLOCKED")
    src = conn.execute(text("SELECT id FROM account WHERE id = :a AND kind = 'EXTERNAL'"), {"a": from_account}).first()
    if src is None:
        raise BankError(f"{from_account} is not an account at another bank.", "ACCOUNT_NOT_FOUND")
    if not 1 <= amount <= 25_00_000:
        raise BankError("Enter an amount between ₹1 and ₹25,00,000.", "INVALID_REQUEST")
    row = {"id": Ids(conn).take("txn", "TX", 7), "from_account": src.id, "to_account": a.id, "amount_paise": amount * 100,
           "channel": channel, "kind": "CREDIT", "narration": "Transfer received", "branch_id": None, "session_id": None,
           "occurred_at": t.isoformat(), "ingested_at": _lag(t, 3)}
    return _record(conn, "txn", row, t)


def account_json(conn: Connection, account_id: str) -> dict:
    a = conn.execute(text("""
        SELECT a.id, a.customer_id, a.kind, a.status, a.branch_id, a.balance_paise, a.daily_limit_paise, a.opening_mode,
               a.kyc_approved_by, c.full_name, c.segment
        FROM account a JOIN customer c ON c.id = a.customer_id WHERE a.id = :a"""), {"a": account_id}).first()
    if a is None:
        raise BankError(f"No customer account {account_id}.", "ACCOUNT_NOT_FOUND")
    return {"accountId": a.id, "accountNumber": f"XXXX{a.id[-4:]}", "customerId": a.customer_id, "name": a.full_name,
            "segment": a.segment, "type": a.kind, "balance": a.balance_paise / 100, "currency": "INR", "status": a.status,
            "transactionLimit": a.daily_limit_paise / 100, "branchId": a.branch_id,
            "kycStatus": "VERIFIED" if a.kyc_approved_by else "PENDING", "kycMode": a.opening_mode,
            "registeredMobile": _mobile_on_file(conn, a.id), "environment": LABEL}


def transaction_json(r) -> dict:
    return {"transactionId": r.id, "amount": r.amount_paise / 100, "currency": "INR", "status": "SUCCESS",
            "timestamp": r.occurred_at.isoformat() if hasattr(r.occurred_at, "isoformat") else r.occurred_at,
            "sender": r.from_account, "receiver": r.to_account, "channel": r.channel, "type": r.kind,
            "narration": r.narration, "environment": LABEL}


def transactions_json(conn: Connection, account_id: str, limit: int = 20) -> list[dict]:
    account_json(conn, account_id)  # 404 for unknown accounts
    rows = conn.execute(text("SELECT id, amount_paise, occurred_at, from_account, to_account, channel, kind, narration FROM txn "
                             "WHERE from_account = :a OR to_account = :a ORDER BY occurred_at DESC LIMIT :n"),
                        {"a": account_id, "n": limit}).all()
    return [transaction_json(r) for r in rows]


def get_transaction(conn: Connection, txn_id: str) -> dict:
    r = conn.execute(text("SELECT id, amount_paise, occurred_at, from_account, to_account, channel, kind, narration FROM txn "
                          "WHERE id = :t"), {"t": txn_id}).first()
    if r is None:
        raise BankError(f"No transaction {txn_id}.", "TRANSACTION_NOT_FOUND")
    return transaction_json(r)


def pay(conn: Connection, from_account: str, to: str, amount: int, channel: str = "IMPS", new_device: bool = False,
        register_payee: bool = False, simulate_failure: bool = False, city: str | None = None) -> dict:
    """A customer pays from NetBanking: signs in (usual or new phone), optionally adds the payee, sends the money.

    Any refusal — including `simulate_failure`, a timeout at the receiving bank — undoes the whole attempt,
    so a declined payment leaves nothing in the bank's records and nothing for SUTRA to see."""
    src = conn.execute(text("SELECT customer_id, status FROM account WHERE id = :a AND kind <> 'EXTERNAL'"), {"a": from_account}).first()
    if src is None:
        raise BankError(f"No customer account {from_account}.", "ACCOUNT_NOT_FOUND")
    if src.status == "BLOCKED":
        raise BankError(f"{from_account} is blocked. No money can leave it until the branch unblocks it.", "ACCOUNT_BLOCKED")
    owner = src.customer_id
    if not conn.execute(text("SELECT 1 FROM account WHERE id = :a"), {"a": to}).first():
        raise BankError(f"No account {to} at any bank we can reach.", "ACCOUNT_NOT_FOUND")
    sid = customer_login(conn, owner, new_device, city)["session_id"]
    if register_payee and not conn.execute(text("SELECT 1 FROM beneficiary WHERE account_id = :a AND counterparty_account = :c"),
                                      {"a": from_account, "c": to}).first():
        add_payee(conn, owner, sid, from_account, to)
    if simulate_failure:
        raise BankError(f"The {channel} switch did not get a reply from the receiving bank. Nothing was debited.", "SWITCH_FAILED")
    rec = transfer(conn, owner, sid, from_account, to, amount, channel)
    r = conn.execute(text("SELECT id, amount_paise, occurred_at, from_account, to_account, channel, kind, narration FROM txn "
                          "WHERE id = :t"), {"t": rec["ref"]}).first()
    return transaction_json(r)

