"""Compose: turn a person's choices into source rows, built on the bank's current state.

The Live Ops "Your input" console lets a presenter, or a judge, act as a member of staff on the
evening of 22 Sep. They choose:

  • who logs in, when, and how;
  • what paperwork exists;
  • what changes on which account;
  • where the money goes.

This module writes the rows each bank system would have recorded for those actions — sessions,
the core-banking access audit, state changes, tickets, payees, transfers, and the mule ring's usual
reaction. The rows are tokenised the same way as everything else and staged as held-back feed rows
(strand "yours"). A live run then ingests and detects them.

Nothing here decides what is suspicious; that is left entirely to the pipeline. The same input
always produces the same rows, so a result can be shown twice.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import Connection, text

from app.core.pii import tokenise

DAY = date(2026, 9, 22)
IST_OFFSET = "+05:30"
# The 21 Sep mule ring: who the mules pass money to, and where it leaves the bank.
RING = {"A-7731": "A-6604", "A-7768": "A-6604"}
EXIT = "X-9901"
OFFSETS_S = [0, 136, 343, 520, 700]
EXTERNAL_PAYEES = ("OUTSIDE", "FAMILY")


class ComposeError(ValueError):
    """The choices don't describe something the bank could record (shown to the person as-is)."""


@dataclass
class Spec:
    employee_id: str
    account_id: str
    at: str = "21:20"  # HH:MM on 22 Sep, bank time
    channel: str = "VPN"  # VPN | BRANCH
    auth: str = "OVERRIDE"  # OVERRIDE | MAKER_ONLY | BIOMETRIC
    expired_grant: bool = True
    ticket: bool = False
    ekyc: bool = False
    rostered: bool = False
    change_mobile: bool = True
    raise_limit_to: int | None = 5_00_000  # rupees
    takeover: bool = True
    payees: list[str] = field(default_factory=lambda: ["A-7731", "A-7768"])
    amount: int = 4_00_000  # rupees per transfer
    delay_min: int = 38
    ring_reacts: bool = True


def _at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{DAY.isoformat()}T{hhmm}:00{IST_OFFSET}")


def _iso(t: datetime) -> str:
    return t.isoformat()


def _rupees(paise: int) -> str:
    r = paise / 100
    return f"₹{r / 1e5:.2f} L" if r >= 1e5 else f"₹{r:,.0f}"


def _mask(phone: str) -> str:
    return f"+91 ••••• {phone[-4:]}"


class Ids:
    """Next free ID per prefix, above everything in the table and in the held-back feed."""

    def __init__(self, conn: Connection):
        self.conn, self.next = conn, {}

    def take(self, table: str, prefix: str, width: int) -> str:
        if prefix not in self.next:
            pat = f"^{prefix}-([0-9]+)$"
            in_table = self.conn.execute(text(f"SELECT max(CAST(substring(id FROM :p) AS bigint)) FROM {table}"),
                                         {"p": pat}).scalar() or 0
            in_feed = self.conn.execute(text("SELECT max(CAST(substring(ref FROM :p) AS bigint)) FROM feed_event"),
                                        {"p": pat}).scalar() or 0
            self.next[prefix] = max(in_table, in_feed) + 1
        n = self.next[prefix]
        self.next[prefix] += 1
        return f"{prefix}-{n:0{width}d}"


def _taken_accounts(conn: Connection) -> set[str]:
    """Accounts already in a chain or in tonight's held-back feed — not offered as targets."""
    rows = conn.execute(text("""
        SELECT account_id FROM chain WHERE account_id IS NOT NULL
        UNION SELECT row->>'account_id' FROM feed_event WHERE row ? 'account_id'
        UNION SELECT row->>'from_account' FROM feed_event WHERE source_table = 'txn'
        UNION SELECT row->>'to_account' FROM feed_event WHERE source_table = 'txn'""")).scalars()
    return {r for r in rows if r} | set(RING) | set(RING.values())


def _laptop(conn: Connection, employee_id: str) -> str:
    known = conn.execute(text("SELECT device_id FROM session WHERE actor_id = :e AND channel = 'VPN' "
                              "AND device_id IS NOT NULL ORDER BY started_at DESC LIMIT 1"), {"e": employee_id}).scalar()
    return known or f"LAP-{employee_id[-4:]}"


def options(conn: Connection) -> dict:
    staff = [dict(r._mapping) for r in conn.execute(text("""
        SELECT e.id, e.pseudonym, e.branch_id, b.city,
               (SELECT device_id FROM session s WHERE s.actor_id = e.id AND s.channel = 'BRANCH'
                ORDER BY started_at DESC LIMIT 1) AS terminal
        FROM employee e JOIN branch b ON b.id = e.branch_id
        WHERE e.role = 'OPS_OFFICER' AND e.status = 'ACTIVE' ORDER BY e.branch_id, e.id"""))]
    taken = _taken_accounts(conn)
    accounts = [dict(r._mapping) for r in conn.execute(text("""
        SELECT a.id, a.holder_name AS holder, a.customer_id, cu.segment, a.status, a.branch_id,
               a.balance_paise / 100 AS balance, a.daily_limit_paise / 100 AS daily_limit,
               (SELECT count(*) FROM beneficiary bn WHERE bn.account_id = a.id) AS payees
        FROM account a JOIN customer cu ON cu.id = a.customer_id
        WHERE a.kind <> 'EXTERNAL' AND a.balance_paise >= 50000 * 100 AND a.id <> ALL(CAST(:taken AS text[]))
          AND (a.status = 'INOPERATIVE' OR cu.segment = 'PENSIONER')
        ORDER BY (a.status = 'INOPERATIVE') DESC, a.balance_paise DESC LIMIT 24"""), {"taken": sorted(taken)})]
    ring = {r.id: r.holder_name for r in conn.execute(text("SELECT id, holder_name FROM account WHERE id = ANY(:a)"),
                                                        {"a": list(RING)})}
    payees = [{"id": a, "label": f"{a} · {ring.get(a, '')}", "kind": "ring"} for a in RING if a in ring]
    payees += [{"id": "OUTSIDE", "label": "An account at another bank, never paid before", "kind": "outside"},
               {"id": "FAMILY", "label": "A payee this customer already pays", "kind": "known"}]
    # staff already in a case or in tonight's feed — still selectable, but not the default
    in_story = set(conn.execute(text("""
        SELECT ch.employee_id FROM chain ch JOIN alert a ON a.chain_id = ch.id
        WHERE ch.employee_id IS NOT NULL AND a.priority IN ('P1', 'P2', 'P3')
        UNION SELECT row->>'employee_id' FROM feed_event WHERE row ? 'employee_id'
        UNION SELECT row->>'actor_id' FROM feed_event WHERE source_table = 'session'""")).scalars())
    for s in staff:
        s["laptop"] = _laptop(conn, s["id"])
        s["in_story"] = s["id"] in in_story
    return {"day": DAY.isoformat(), "staff": staff, "accounts": accounts, "payees": payees}


def build(conn: Connection, spec: Spec) -> list[dict]:
    """Rows the bank's systems would have recorded, oldest first, each with its master-data effect."""
    rng = random.Random(hashlib.sha256(json.dumps(spec.__dict__, sort_keys=True).encode()).hexdigest())
    emp = conn.execute(text("SELECT e.id, e.branch_id, e.manager_id, e.role, b.city FROM employee e "
                            "JOIN branch b ON b.id = e.branch_id WHERE e.id = :e"), {"e": spec.employee_id}).first()
    if emp is None or emp.role != "OPS_OFFICER":
        raise ComposeError("Choose an operations officer — they hold the mobile-update permission.")
    acct = conn.execute(text("SELECT a.*, cu.segment FROM account a JOIN customer cu ON cu.id = a.customer_id "
                             "WHERE a.id = :a AND a.kind <> 'EXTERNAL'"), {"a": spec.account_id}).first()
    if acct is None:
        raise ComposeError(f"{spec.account_id} is not a customer account at this bank.")
    if acct.id in _taken_accounts(conn):
        mine = conn.execute(text("SELECT 1 FROM feed_event WHERE strand = 'yours' AND (row->>'account_id' = :a "
                                 "OR row->>'from_account' = :a) LIMIT 1"), {"a": acct.id}).first()
        raise ComposeError(f"{acct.id} already carries your earlier input — undo it first, or pick another account." if mine
                           else f"{acct.id} is already part of a case or of tonight's feed — pick another account.")
    if spec.channel not in ("VPN", "BRANCH") or spec.auth not in ("OVERRIDE", "MAKER_ONLY", "BIOMETRIC"):
        raise ComposeError("Unknown channel or authorisation.")
    if len(set(spec.payees)) != len(spec.payees) or len(spec.payees) > 4:
        raise ComposeError("Choose up to four different payees.")
    total = spec.amount * 100 * len(spec.payees)
    if total > acct.balance_paise:
        raise ComposeError(f"{acct.id} holds {_rupees(acct.balance_paise)}; {len(spec.payees)} × "
                           f"{_rupees(spec.amount * 100)} is more than that.")
    if spec.payees and spec.delay_min < 12:
        raise ComposeError("Leave at least 12 minutes between the login and the first transfer.")

    ids = Ids(conn)
    t0 = _at(spec.at)
    rows: list[dict] = []
    lag = lambda t: t + timedelta(seconds=rng.randint(4, 90))  # noqa: E731 — system time trails event time

    def add(table: str, t: datetime, row: dict, effect: dict | None = None) -> dict:
        rows.append({"table": table, "t": t, "row": row, "effect": effect})
        return row

    # What already existed: an old temporary grant, a roster, a ticket.
    if spec.expired_grant:
        g = (t0 - timedelta(days=6)).replace(hour=11, minute=5, second=0)
        add("entitlement", g, {"id": ids.take("entitlement", "ENT", 5), "employee_id": emp.id,
                               "permission_code": "MOBILE_UPDATE_OVERRIDE", "granted_by": emp.manager_id,
                               "reason": "Pension camp — bulk mobile updates for senior citizens",
                               "request_ref": f"REQ-{rng.randint(1000, 9999)}", "valid_from": _iso(g),
                               "intended_expiry": _iso((g + timedelta(days=2)).replace(hour=23, minute=59)),
                               "revoked_at": None})
    if spec.rostered:
        start = (t0 - timedelta(hours=2)).replace(minute=0, second=0)
        add("roster", start, {"id": ids.take("roster", "RS", 6), "employee_id": emp.id, "shift_start": _iso(start),
                              "shift_end": _iso(t0 + timedelta(hours=2)), "duty_type": "CAMP"})
    if spec.ticket:
        tk = t0 - timedelta(minutes=14)
        add("work_item", tk, {"id": ids.take("work_item", "WI", 6), "kind": "TICKET", "ref": f"SR-{rng.randint(7000, 7999)}",
                              "customer_id": acct.customer_id, "account_id": acct.id, "employee_id": emp.id,
                              "branch_id": emp.branch_id, "text": "Update registered mobile number — customer request",
                              "created_at": _iso(tk), "closed_at": _iso(tk + timedelta(minutes=30))})

    # The staff session and what it touched.
    device = _laptop(conn, emp.id) if spec.channel == "VPN" else (conn.execute(text(
        "SELECT device_id FROM session WHERE actor_id = :e AND channel = 'BRANCH' ORDER BY started_at DESC LIMIT 1"),
        {"e": emp.id}).scalar())
    sess = add("session", t0, {"id": ids.take("session", "S", 6), "actor_type": "EMPLOYEE", "actor_id": emp.id,
                               "device_id": device, "ip": f"49.36.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                               "geo_city": emp.city, "channel": spec.channel, "started_at": _iso(t0),
                               "ended_at": _iso(t0 + timedelta(minutes=12))})["id"]

    def access(action: str, t: datetime, fields: list[str], override: bool = False, customer_only: bool = False):
        add("access_event", t, {"id": ids.take("access_event", "AE", 7), "session_id": sess, "employee_id": emp.id,
                                "action": action, "account_id": None if customer_only else acct.id,
                                "customer_id": acct.customer_id, "fields": fields, "override_used": override,
                                "occurred_at": _iso(t), "ingested_at": _iso(lag(t))})

    access("CUST_SEARCH", t0 + timedelta(seconds=31), [], customer_only=True)
    access("ACCT_VIEW", t0 + timedelta(seconds=115), ["balance", "registered_mobile", "nominee"])
    override = spec.auth == "OVERRIDE"
    t_mob = t0 + timedelta(seconds=297)
    if spec.ekyc or spec.auth == "BIOMETRIC":
        ek = t_mob - timedelta(minutes=2)
        add("work_item", ek, {"id": ids.take("work_item", "WI", 6), "kind": "EKYC", "ref": f"EKYC-{rng.randint(100000, 999999)}",
                              "customer_id": acct.customer_id, "account_id": acct.id, "employee_id": emp.id,
                              "branch_id": emp.branch_id, "text": "Aadhaar biometric eKYC — success",
                              "created_at": _iso(ek), "closed_at": _iso(ek + timedelta(minutes=2))})
    if spec.change_mobile:
        access("MOBILE_UPDATE", t_mob, ["registered_mobile"], override)
        new_phone = f"+91{rng.choice('6789')}{rng.randint(100_000_000, 999_999_999)}"
        on_file = conn.execute(text("SELECT new_value FROM state_change WHERE account_id = :a AND field = 'REGISTERED_MOBILE' "
                                    "ORDER BY occurred_at DESC LIMIT 1"), {"a": acct.id}).scalar() or "number on file"
        add("state_change", t_mob, {"id": ids.take("state_change", "SC", 6), "account_id": acct.id,
                                    "field": "REGISTERED_MOBILE", "old_value": on_file, "new_value": _mask(new_phone),
                                    "actor_type": "EMPLOYEE", "actor_id": emp.id, "auth_method": spec.auth,
                                    "session_id": sess, "occurred_at": _iso(t_mob), "ingested_at": _iso(lag(t_mob))},
            {"account_id": acct.id, "column": "registered_mobile_tok", "old": acct.registered_mobile_tok,
             "new": tokenise(new_phone, "phone")})
    if spec.raise_limit_to:
        t_lim = t0 + timedelta(seconds=500)
        access("LIMIT_CHANGE", t_lim, ["txn_limit"], override)
        new_limit = spec.raise_limit_to * 100
        add("state_change", t_lim, {"id": ids.take("state_change", "SC", 6), "account_id": acct.id, "field": "TXN_LIMIT",
                                    "old_value": str(acct.daily_limit_paise), "new_value": str(new_limit),
                                    "actor_type": "EMPLOYEE", "actor_id": emp.id,
                                    "auth_method": "OVERRIDE" if override else "MAKER_ONLY", "session_id": sess,
                                    "occurred_at": _iso(t_lim), "ingested_at": _iso(lag(t_lim))},
            {"account_id": acct.id, "column": "daily_limit_paise", "old": acct.daily_limit_paise, "new": new_limit})

    # The customer side: an accomplice on a new phone, or the customer's own app.
    if not spec.payees:
        return sorted(rows, key=lambda r: r["t"])
    t_pay = t0 + timedelta(minutes=spec.delay_min)
    t_cust = t0 + min(timedelta(minutes=14, seconds=2), (t_pay - t0) * 0.4)
    if spec.takeover:
        dev = f"D-{rng.randint(0x1000, 0xFFFF):04X}"
        while conn.execute(text("SELECT 1 FROM device WHERE id = :d UNION SELECT 1 FROM feed_event WHERE ref = :d"),
                           {"d": dev}).first():
            dev = f"D-{rng.randint(0x1000, 0xFFFF):04X}"
        add("device", t_cust, {"id": dev, "fingerprint": f"{rng.getrandbits(64):016x}", "kind": "ANDROID",
                               "first_seen": _iso(t_cust)})
        channel = "NETBANKING"
    else:
        dev = conn.execute(text("SELECT device_id FROM session WHERE actor_id = :c ORDER BY started_at DESC LIMIT 1"),
                           {"c": acct.customer_id}).scalar()
        channel = "MOBILE"
    cs = add("session", t_cust, {"id": ids.take("session", "S", 6), "actor_type": "CUSTOMER", "actor_id": acct.customer_id,
                                 "device_id": dev, "ip": f"49.36.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                                 "geo_city": emp.city, "channel": channel, "started_at": _iso(t_cust),
                                 "ended_at": _iso(t_pay + timedelta(minutes=15))})["id"]
    if spec.takeover:
        t_pw = t_cust + timedelta(seconds=28)
        add("state_change", t_pw, {"id": ids.take("state_change", "SC", 6), "account_id": acct.id, "field": "PASSWORD",
                                   "old_value": "—", "new_value": "reset", "actor_type": "CUSTOMER",
                                   "actor_id": acct.customer_id, "auth_method": "OTP_NEW_NUMBER", "session_id": cs,
                                   "occurred_at": _iso(t_pw), "ingested_at": _iso(lag(t_pw))})

    known = [r[0] for r in conn.execute(text("SELECT counterparty_account FROM beneficiary WHERE account_id = :a "
                                             "ORDER BY added_at"), {"a": acct.id})]
    targets: list[str] = []
    for p in spec.payees:
        if p == "FAMILY":
            if not known:
                raise ComposeError(f"{acct.id} has no existing payees — choose another payee.")
            targets.append(known[0])
        elif p == "OUTSIDE":
            # an ordinary outside account: never paid by this customer, in no case, not in tonight's feed
            targets.append(conn.execute(text(
                "SELECT id FROM account WHERE kind = 'EXTERNAL' AND id ~ '^X-[0-9]{4}$' "
                "AND id <> ALL(CAST(:avoid AS text[])) AND id NOT IN (SELECT unnest(entity_refs) FROM chain) "
                "AND id NOT IN (SELECT to_account FROM txn WHERE from_account = :a) ORDER BY md5(id || :a) LIMIT 1"),
                {"avoid": sorted({*known, *_taken_accounts(conn), EXIT}), "a": acct.id}).scalar())
        elif p in RING:
            targets.append(p)
        else:
            raise ComposeError(f"Unknown payee {p}.")
    holders = dict(conn.execute(text("SELECT id, holder_name FROM account WHERE id = ANY(:a)"),
                                {"a": [*targets, *RING.values(), EXIT]}).all())
    step = min(timedelta(minutes=5, seconds=53), (t_pay - t_cust) * 0.4)
    for k, target in enumerate(targets):
        if target in known:
            continue
        tb = t_cust + step + timedelta(seconds=50 * k)
        add("beneficiary", tb, {"id": ids.take("beneficiary", "BN", 6), "account_id": acct.id,
                                "counterparty_account": target, "counterparty_name": holders.get(target, target),
                                "session_id": cs, "added_at": _iso(tb)})

    def txn(frm: str, to: str, paise: int, channel: str, kind: str, t: datetime, narration: str, session: str | None):
        add("txn", t, {"id": ids.take("txn", "TX", 7), "from_account": frm, "to_account": to, "amount_paise": paise,
                       "channel": channel, "kind": kind, "narration": narration, "branch_id": None,
                       "session_id": session, "occurred_at": _iso(t), "ingested_at": _iso(lag(t))})

    for k, target in enumerate(targets):
        txn(acct.id, target, spec.amount * 100, "IMPS", "TRANSFER", t_pay + timedelta(seconds=OFFSETS_S[k]),
            "IMPS transfer", cs)

    # The ring reacts the way it did on 21 Sep: forward ~96% to the consolidator, cash out the rest.
    forwarded = 0
    if spec.ring_reacts:
        for k, mule in enumerate(t for t in targets if t in RING):
            t_fwd = t_pay + timedelta(minutes=24 + 16 * k, seconds=8)
            cust = conn.execute(text("SELECT customer_id FROM account WHERE id = :m"), {"m": mule}).scalar()
            mdev = conn.execute(text("SELECT device_id FROM session WHERE actor_id = :c ORDER BY started_at DESC LIMIT 1"),
                                {"c": cust}).scalar()
            ms = add("session", t_fwd - timedelta(minutes=3), {
                "id": ids.take("session", "S", 6), "actor_type": "CUSTOMER", "actor_id": cust, "device_id": mdev,
                "ip": f"49.36.{rng.randint(0, 255)}.{rng.randint(1, 254)}", "geo_city": "Pune", "channel": "MOBILE",
                "started_at": _iso(t_fwd - timedelta(minutes=3)), "ended_at": _iso(t_fwd + timedelta(minutes=27))})["id"]
            fwd = int(spec.amount * (0.959 + 0.004 * k)) // 1000 * 1000
            forwarded += fwd
            txn(mule, RING[mule], fwd * 100, "IMPS", "TRANSFER", t_fwd, "Settlement", ms)
            txn(mule, "X-ATM", (spec.amount - fwd) * 100, "ATM", "ATM_WITHDRAWAL", t_fwd + timedelta(minutes=6, seconds=52),
                "ATM cash", None)
    if forwarded:
        exit_amt = max(50_000, forwarded // 2 // 10_000 * 10_000)
        txn("A-6604", EXIT, exit_amt * 100, "RTGS", "TRANSFER", t_pay + timedelta(minutes=66), "Purchase", None)
    return sorted(rows, key=lambda r: r["t"])


# ── wording shown in the input console (matches the held-back feed's) ──────


def source_system(table: str, row: dict) -> str:
    if table == "session":
        if row["actor_type"] == "EMPLOYEE":
            return "VPN gateway" if row["channel"] == "VPN" else "Branch SSO"
        return "Digital banking"
    if table == "txn":
        return "ATM switch" if row["channel"] == "ATM" else f"{row['channel']} switch"
    if table == "work_item":
        return {"TICKET": "Service desk", "EKYC": "UIDAI eKYC"}.get(row["kind"], "Workflow")
    return {"access_event": "CBS application audit", "state_change": "Core banking", "beneficiary": "Digital banking",
            "device": "Device registry", "entitlement": "IAM", "roster": "HRMS"}.get(table, table)


def describe(table: str, r: dict, holders: dict[str, str]) -> str:
    def party(a: str) -> str:
        return f"{a} · {holders[a]}" if a.startswith("X-") and a in holders and a != "X-ATM" else a

    if table == "session":
        if r["actor_type"] == "EMPLOYEE":
            return f"{r['channel']} login · {r['actor_id']} on {r['device_id'] or 'unknown device'} · {r['geo_city']}"
        return f"{r['channel'].title()} login · customer {r['actor_id']} · device {r['device_id'] or '—'}"
    if table == "access_event":
        target = r["account_id"] or r["customer_id"]
        fields = f" [{', '.join(r['fields'])}]" if r["fields"] else ""
        return f"{r['employee_id']} {r['action']} on {target}{fields}{' · OVERRIDE' if r['override_used'] else ''}"
    if table == "state_change":
        old, new = r["old_value"], r["new_value"]
        if r["field"] == "TXN_LIMIT":
            old, new = _rupees(int(old)), _rupees(int(new))
        return f"{r['account_id']} {r['field'].replace('_', ' ').lower()}: {old} → {new} · by {r['actor_id']} ({r['auth_method']})"
    if table == "beneficiary":
        return f"Payee added on {r['account_id']}: {r['counterparty_name']} ({r['counterparty_account']})"
    if table == "txn":
        if r["channel"] == "ATM":
            return f"ATM cash {_rupees(r['amount_paise'])} from {r['from_account']}"
        return (f"{r['channel']} {_rupees(r['amount_paise'])} · {party(r['from_account'])} → {party(r['to_account'])}"
                f" · {r['narration'] or r['kind']}")
    if table == "device":
        return f"New {r['kind'].lower()} device {r['id']} first seen"
    if table == "work_item":
        return f"{r['kind']} {r['ref']} · {r['text']}"
    if table == "entitlement":
        return (f"{r['permission_code']} granted to {r['employee_id']} ({r['request_ref']}) — meant to expire "
                f"{datetime.fromisoformat(r['intended_expiry']):%d %b %H:%M}")
    if table == "roster":
        return (f"{r['duty_type'].title()} shift rostered for {r['employee_id']}, "
                f"{datetime.fromisoformat(r['shift_start']):%H:%M}–{datetime.fromisoformat(r['shift_end']):%H:%M}")
    return f"{table} {r.get('id')}"


def stage(conn: Connection, rows: list[dict]) -> int:
    """Replace any unplayed input with these rows, as held-back feed rows (strand "yours")."""
    conn.execute(text("DELETE FROM feed_event WHERE strand = 'yours' AND ingested_at IS NULL"))
    seq = conn.execute(text("SELECT coalesce(max(seq), 0) FROM feed_event")).scalar()
    accounts = {a for r in rows for a in (r["row"].get("from_account"), r["row"].get("to_account"),
                                          r["row"].get("counterparty_account")) if a}
    holders = dict(conn.execute(text("SELECT id, holder_name FROM account WHERE id = ANY(:a)"), {"a": sorted(accounts)}).all())
    for i, r in enumerate(rows, start=1):
        conn.execute(text("INSERT INTO feed_event (seq, t, source_table, ref, system, summary, row, effect, strand) "
                          "VALUES (:seq, :t, :table, :ref, :system, :summary, CAST(:row AS jsonb), CAST(:effect AS jsonb), 'yours')"),
                     {"seq": seq + i, "t": r["t"], "table": r["table"], "ref": r["row"]["id"],
                      "system": source_system(r["table"], r["row"]), "summary": describe(r["table"], r["row"], holders),
                      "row": json.dumps(r["row"]), "effect": json.dumps(r["effect"]) if r["effect"] else None})
    return len(rows)


def preview(conn: Connection, rows: list[dict]) -> list[dict]:
    accounts = {a for r in rows for a in (r["row"].get("from_account"), r["row"].get("to_account"),
                                          r["row"].get("counterparty_account")) if a}
    holders = dict(conn.execute(text("SELECT id, holder_name FROM account WHERE id = ANY(:a)"), {"a": sorted(accounts)}).all())
    return [{"seq": i, "t": r["t"].isoformat(), "table": r["table"], "ref": r["row"]["id"],
             "system": source_system(r["table"], r["row"]), "summary": describe(r["table"], r["row"], holders)}
            for i, r in enumerate(rows, start=1)]
