"""Predefined test scenarios for the mock bank — MOCK BANK, TEST ENVIRONMENT, NO REAL MONEY.

Each scenario does, through the bank's own functions, what a customer or member of staff would do,
on fixed synthetic accounts from the seed-42 world. It returns the bank's answer and states what
SUTRA should conclude once detection runs. `check()` runs them all, runs SUTRA once, compares each
scenario's outcome with its expectation, and undoes everything.

SUTRA has no "risk" field for the bank to fill in: it judges what the bank recorded. So the
expectations here are SUTRA's, not the bank's — a large payment by the real customer, for example,
is expected to raise nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.loom import bank


@dataclass(frozen=True)
class Expect:
    alert: str | None = None  # "P1", "P2", "P1|P2" … or None for "no queued alert"
    typology: str | None = None
    bank_code: str | None = None  # the bank must refuse with this code
    alibi: str | None = None  # "EXPLAINED" / "UNEXPLAINED" for every staff access
    signal: str | None = None  # a detector that must fire on the scenario's rows


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    what: str
    expect_text: str
    expect: Expect
    accounts: tuple[str, ...]
    run: Callable[[Connection], dict]


def _ok(kind: str, payload) -> dict:
    return {"status": "SUCCESS", kind: payload, "environment": bank.LABEL}


def _refusal(e: bank.BankError) -> dict:
    return {"status": "FAILED", "code": e.code, "message": str(e), "environment": bank.LABEL}


# ── the scenarios ───────────────────────────────────────────────────────────


def _normal(c: Connection) -> dict:
    bank.set_clock("18:05")
    payee = c.execute(text("SELECT counterparty_account FROM beneficiary WHERE account_id = 'A-3007' ORDER BY added_at LIMIT 1")).scalar()
    return _ok("transaction", bank.pay(c, "A-3007", payee, 500, "UPI"))


def _large(c: Connection) -> dict:
    bank.set_clock("12:30")
    payee = c.execute(text("SELECT counterparty_account FROM beneficiary WHERE account_id = 'A-6406' ORDER BY added_at LIMIT 1")).scalar()
    return _ok("transaction", bank.pay(c, "A-6406", payee, 5_00_000, "IMPS"))


def _insider(c: Connection) -> dict:
    bank.set_clock("21:20")
    officer, account, customer = "EMP-0258", "A-5661", "C-89006"
    sid = bank.staff_login(c, officer, "VPN")["session_id"]
    bank.grant_override(c, officer, "expired")
    bank.open_customer(c, officer, sid, customer)
    bank.open_account(c, officer, sid, account)
    bank.update_mobile(c, officer, sid, account, "9876543210", "OVERRIDE")
    bank.change_limit(c, officer, sid, account, 5_00_000, True)
    csid = bank.customer_login(c, customer, True)["session_id"]
    bank.reset_password(c, customer, csid)
    txns = []
    for mule in ("A-7731", "A-7768"):
        bank.add_payee(c, customer, csid, account, mule)
    for mule in ("A-7731", "A-7768"):
        txns.append(bank.transfer(c, customer, csid, account, mule, 4_00_000, "IMPS")["ref"])
    return _ok("transactions", [bank.get_transaction(c, t) for t in txns])


def _camp(c: Connection) -> dict:
    bank.set_clock("19:05")
    officer, account, customer = "EMP-0266", "A-1028", "C-79086"
    bank.roster_camp(c, officer, "17:30", "22:30")
    sid = bank.staff_login(c, officer, "BRANCH")["session_id"]
    bank.open_customer(c, officer, sid, customer)
    bank.raise_ticket(c, officer, account, "Pension camp: update registered mobile — customer present")
    bank.capture_ekyc(c, officer, account)
    bank.open_account(c, officer, sid, account)
    bank.update_mobile(c, officer, sid, account, "9123456780", "BIOMETRIC")
    return _ok("account", bank.account_json(c, account))


def _outsider(c: Connection) -> dict:
    bank.set_clock("23:02")
    account, customer = "A-8070", "C-35868"
    sid = bank.customer_login(c, customer, True, "Kolkata")["session_id"]
    bank.reset_password(c, customer, sid)
    targets = c.execute(text("""SELECT id FROM account WHERE kind = 'EXTERNAL' AND id ~ '^X-[0-9]{4}$'
        AND holder_name ~ '^[A-Z][a-z]+ [A-Z][a-z]+$' AND id NOT IN (SELECT counterparty_account FROM beneficiary WHERE account_id = :a)
        ORDER BY md5(id) LIMIT 2"""), {"a": account}).scalars().all()
    for t in targets:
        bank.add_payee(c, customer, sid, account, t)
    txns = [bank.transfer(c, customer, sid, account, t, amt, "IMPS")["ref"] for t, amt in zip(targets, (98_500, 97_000), strict=True)]
    return _ok("transactions", [bank.get_transaction(c, t) for t in txns])


def _rapid(c: Connection) -> dict:
    bank.set_clock("16:30")
    account, customer = "A-5636", "C-39423"
    senders = c.execute(text("""SELECT id FROM account WHERE kind = 'EXTERNAL' AND id ~ '^X-[0-9]{4}$'
        AND holder_name ~ '^[A-Z][a-z]+ [A-Z][a-z]+$' ORDER BY md5(id || 'in') LIMIT 3""")).scalars().all()
    for s in senders:
        bank.receive(c, account, s, 40_000)
    out = c.execute(text("""SELECT id FROM account WHERE kind = 'EXTERNAL' AND id ~ '^X-[0-9]{4}$' AND id <> ALL(:s)
        AND id NOT IN (SELECT counterparty_account FROM beneficiary WHERE account_id = :a) ORDER BY md5(id || 'out') LIMIT 1"""),
        {"s": senders, "a": account}).scalar()
    sid = bank.customer_login(c, customer, False)["session_id"]
    bank.add_payee(c, customer, sid, account, out)
    txns = [bank.transfer(c, customer, sid, account, out, 57_000, "IMPS")["ref"] for _ in range(2)]
    return _ok("transactions", [bank.get_transaction(c, t) for t in txns])


def _failed(c: Connection) -> dict:
    bank.set_clock("18:20")
    payee = c.execute(text("SELECT counterparty_account FROM beneficiary WHERE account_id = 'A-3007' ORDER BY added_at LIMIT 1")).scalar()
    return _ok("transaction", bank.pay(c, "A-3007", payee, 2_000, "IMPS", simulate_failure=True))


def _insufficient(c: Connection) -> dict:
    bank.set_clock("14:00")
    payee = c.execute(text("SELECT counterparty_account FROM beneficiary WHERE account_id = 'A-3341' ORDER BY added_at LIMIT 1")).scalar()
    return _ok("transaction", bank.pay(c, "A-3341", payee, 2_00_000, "IMPS"))


def _blocked(c: Connection) -> dict:
    bank.set_clock("15:00")
    if c.execute(text("SELECT status FROM account WHERE id = 'A-1832'")).scalar() != "BLOCKED":
        bank.set_blocked(c, "A-1832", True)
    payee = c.execute(text("SELECT counterparty_account FROM beneficiary WHERE account_id = 'A-1832' ORDER BY added_at LIMIT 1")).scalar()
    try:  # the block stays on record; the refused payment attempt leaves nothing
        with c.begin_nested():
            return _ok("transaction", bank.pay(c, "A-1832", payee, 1_000, "UPI"))
    except bank.BankError as e:
        return _refusal(e)


def _invalid(c: Connection) -> dict:
    bank.set_clock("15:30")
    return _ok("transaction", bank.pay(c, "A-3007", "A-0000", 1_000, "IMPS"))


SCENARIOS: dict[str, Scenario] = {s.key: s for s in [
    Scenario("normal", "Normal payment", "Anjali Khan pays ₹500 by UPI from her usual phone to someone she already pays.",
             "No alert. An ordinary payment.", Expect(alert=None), ("A-3007",), _normal),
    Scenario("large", "Large payment", "Milind Gupta's business pays ₹5,00,000 by IMPS from its usual device to an existing supplier.",
             "No alert. Size alone is not a reason: no staff privilege, no takeover.", Expect(alert=None), ("A-6406",), _large),
    Scenario("insider", "Insider takeover (fraud)",
             "EMP-0258 logs in over VPN at 21:20 with an old override nobody revoked, changes a dormant pensioner's mobile and limit; "
             "an accomplice signs in on a new phone, adds two mule payees and sends ₹4,00,000 to each.",
             "P1 insider-enabled takeover; Alibi finds no reason for the staff accesses.",
             Expect(alert="P1", typology="INSIDER_ATO", alibi="UNEXPLAINED"), ("A-5661",), _insider),
    Scenario("camp", "Legitimate camp update",
             "EMP-0266 is rostered on an evening camp, raises a ticket, captures the customer's biometric eKYC and changes the mobile. No money moves.",
             "No alert; Alibi explains every staff access.", Expect(alert=None, alibi="EXPLAINED"), ("A-1028",), _camp),
    Scenario("outsider", "Account takeover by an outsider",
             "Someone signs in to Vishal Nair's NetBanking on a new phone from Kolkata at 23:02, resets the password, adds two payees "
             "and sends ₹98,500 and ₹97,000, just under the ₹1,00,000 limit.",
             "A queued external account-takeover alert (no staff involved).",
             Expect(alert="P1|P2|P3", typology="EXTERNAL_ATO"), ("A-8070",), _outsider),
    Scenario("rapid", "Rapid in-and-out transactions",
             "Three ₹40,000 credits from other banks land in Sandeep Fernandes's account within minutes; ₹1,14,000 leaves to a new payee shortly after.",
             "A rapid pass-through signal (G2). One account passing money on is a signal, not yet a case.",
             Expect(alert=None, signal="G2"), ("A-5636",), _rapid),
    Scenario("failed", "Failed transaction", "A ₹2,000 IMPS payment times out at the receiving bank.",
             "The bank answers FAILED (SWITCH_FAILED). Nothing is recorded, so SUTRA has nothing to judge.",
             Expect(bank_code="SWITCH_FAILED"), ("A-3007",), _failed),
    Scenario("insufficient", "Insufficient balance", "Priya Yadav tries to send ₹2,00,000 with about ₹1.77 L in her account.",
             "The bank refuses with INSUFFICIENT_FUNDS. Nothing reaches SUTRA.", Expect(bank_code="INSUFFICIENT_FUNDS"), ("A-3341",), _insufficient),
    Scenario("blocked", "Blocked account", "The branch blocks Vijay Kulkarni's account; he then tries a ₹1,000 UPI payment.",
             "The bank refuses with ACCOUNT_BLOCKED. Only the block itself is recorded.", Expect(bank_code="ACCOUNT_BLOCKED"), ("A-1832",), _blocked),
    Scenario("invalid", "Invalid account", "A payment to an account number that does not exist (A-0000).",
             "The bank refuses with ACCOUNT_NOT_FOUND. Nothing reaches SUTRA.", Expect(bank_code="ACCOUNT_NOT_FOUND"), ("A-0000",), _invalid),
]}


def catalogue() -> list[dict]:
    return [{"key": s.key, "title": s.title, "what": s.what, "expect": s.expect_text} for s in SCENARIOS.values()]


def already_ran(c: Connection, s: Scenario) -> bool:
    return bool(c.execute(text("""SELECT 1 FROM feed_event WHERE strand = 'bank' AND (row->>'account_id' = ANY(:a)
        OR row->>'from_account' = ANY(:a) OR row->>'to_account' = ANY(:a)) LIMIT 1"""), {"a": list(s.accounts)}).first())


def run(c: Connection, key: str) -> tuple[dict, list[str]]:
    """Run one scenario. Returns the bank's answer and the refs of every row the bank recorded."""
    s = SCENARIOS.get(key)
    if s is None:
        raise bank.BankError(f"No scenario {key!r}. Try one of: {', '.join(SCENARIOS)}.", "NOT_FOUND")
    if s.expect.bank_code is None and already_ran(c, s):
        raise bank.BankError(f"“{s.title}” has already run on {', '.join(s.accounts)}. Reset the test data first.", "SCENARIO_ALREADY_RUN")
    before = c.execute(text("SELECT coalesce(max(seq), 0) FROM feed_event")).scalar()
    try:
        with c.begin_nested():  # a refused attempt is rolled back whole, as the bank would
            out = s.run(c)
    except bank.BankError as e:
        out = _refusal(e)
        if e.code != s.expect.bank_code:
            raise
    refs = c.execute(text("SELECT ref FROM feed_event WHERE strand = 'bank' AND seq > :s ORDER BY seq"), {"s": before}).scalars().all()
    return {"scenario": s.key, "title": s.title, "bankResponse": out, "recorded": len(refs), "expectInSutra": s.expect_text}, list(refs)


# ── the integration check: every scenario, one SUTRA run, compare, undo ─────


def outcome(c: Connection, refs: list[str]) -> dict:
    """What SUTRA concluded about these rows after a detection run."""
    if not refs:
        return {"alerts": [], "signals": [], "alibi": []}
    alerts = c.execute(text("""
        SELECT DISTINCT a.id, a.priority, a.typology FROM alert a JOIN chain ch ON ch.id = a.chain_id
        WHERE a.priority IN ('P1', 'P2', 'P3') AND (
              ch.id IN (SELECT chain_id FROM chain_link WHERE event_id = ANY(:r))
           OR a.id IN (SELECT alert_id FROM evidence WHERE source_ref = ANY(:r)))"""), {"r": refs}).all()
    signals = c.execute(text("SELECT DISTINCT detector FROM signal WHERE event_refs && CAST(:r AS varchar[])"), {"r": refs}).scalars().all()
    alibi = c.execute(text("SELECT verdict FROM explanation WHERE access_event_id = ANY(:r)"), {"r": refs}).scalars().all()
    return {"alerts": [{"id": a.id, "priority": a.priority, "typology": a.typology} for a in alerts],
            "signals": sorted(signals), "alibi": alibi}


def verdict(s: Scenario, response: dict, o: dict) -> tuple[bool, str]:
    e = s.expect
    if e.bank_code:
        code = response.get("bankResponse", {}).get("code")
        ok = code == e.bank_code and not o["alerts"]
        return ok, f"bank said {code}; SUTRA alerts: {len(o['alerts'])}"
    got = o["alerts"]
    parts = []
    ok = True
    if e.alert is None:
        ok &= not got
        parts.append("no queued alert" if not got else f"unexpected {got[0]['priority']} {got[0]['typology']}")
    else:
        match = [a for a in got if a["priority"] in e.alert.split("|") and (not e.typology or a["typology"] == e.typology)]
        ok &= bool(match)
        parts.append(f"{match[0]['priority']} {match[0]['typology']} ({match[0]['id']})" if match
                     else f"expected {e.alert} {e.typology}, got {[(a['priority'], a['typology']) for a in got] or 'nothing'}")
    if e.alibi:
        ok &= bool(o["alibi"]) and all(v == e.alibi for v in o["alibi"])
        parts.append(f"Alibi {sorted(set(o['alibi'])) or '—'}")
    if e.signal:
        ok &= e.signal in o["signals"]
        parts.append(f"signals {', '.join(o['signals']) or '—'}")
    return ok, "; ".join(parts)
