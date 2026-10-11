"""Kestrel Bank, the mock bank: it enforces what a bank would, records every action as a source row,
and keeps its sessions apart from SUTRA's. Everything runs inside the rolled-back test transaction."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

API = "/api/v1"
ACCOUNT, CUSTOMER, OFFICER = "A-5661", "C-89006", "EMP-0258"


@pytest.fixture()
def conn(db):
    from app.loom import bank, feed

    c = db.connection()
    if not c.execute(text("SELECT 1 FROM account WHERE id = :a AND status = 'INOPERATIVE'"), {"a": ACCOUNT}).first():
        pytest.skip("needs the seed-42 demo world")
    feed.reset(c)
    bank.set_clock("21:20")
    return c


def _balance(c) -> int:
    return c.execute(text("SELECT balance_paise FROM account WHERE id = :a"), {"a": ACCOUNT}).scalar()


def test_the_bank_enforces_permissions_limits_and_payees(conn):
    from app.loom import bank, feed

    sid = bank.staff_login(conn, OFFICER, "VPN")["session_id"]
    with pytest.raises(bank.BankError, match="no override"):
        bank.update_mobile(conn, OFFICER, sid, ACCOUNT, "9876543210", "OVERRIDE")
    with pytest.raises(bank.BankError, match="eKYC"):
        bank.update_mobile(conn, OFFICER, sid, ACCOUNT, "9876543210", "BIOMETRIC")

    bank.grant_override(conn, OFFICER, "expired")
    grant = next(p for p in bank.permissions(conn, OFFICER, bank.now()) if p["code"] == "MOBILE_UPDATE_OVERRIDE")
    assert grant["past_expiry"], "a temporary grant nobody revoked is still in force — the weakness SUTRA's C1 targets"
    token_before = conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"), {"a": ACCOUNT}).scalar()
    bank.update_mobile(conn, OFFICER, sid, ACCOUNT, "9876543210", "OVERRIDE")
    assert conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"), {"a": ACCOUNT}).scalar() != token_before

    login = bank.customer_login(conn, CUSTOMER, True)
    assert login["otp_to"] == "+91 ••••• 3210", "the OTP now goes to the number the insider set"
    csid = login["session_id"]
    with pytest.raises(bank.BankError, match="payee"):
        bank.transfer(conn, CUSTOMER, csid, ACCOUNT, "A-7731", 50_000, "IMPS")
    bank.add_payee(conn, CUSTOMER, csid, ACCOUNT, "A-7731")
    with pytest.raises(bank.BankError, match="already a payee"):
        bank.add_payee(conn, CUSTOMER, csid, ACCOUNT, "A-7731")
    with pytest.raises(bank.BankError, match="transaction limit"):
        bank.transfer(conn, CUSTOMER, csid, ACCOUNT, "A-7731", 4_00_000, "IMPS")

    bank.change_limit(conn, OFFICER, sid, ACCOUNT, 5_00_000, True)
    before = _balance(conn)
    bank.transfer(conn, CUSTOMER, csid, ACCOUNT, "A-7731", 4_00_000, "IMPS")
    assert before - _balance(conn) == 4_00_000 * 100

    rows = conn.execute(text("SELECT t AS at, source_table AS tbl, row::text AS body FROM feed_event "
                             "WHERE strand = 'bank' ORDER BY seq")).all()
    acted = [r.at for r in rows if r.tbl != "entitlement"]  # the grant is backdated on purpose (16 Sep)
    assert acted == sorted(acted), "bank time never runs backwards"
    sessions = [r.at for r in rows if r.tbl == "session"]
    assert len(set(sessions)) == len(sessions) and len(set(acted)) > len(acted) // 2, "actions take time; they don't share a moment"
    assert not any(re.search(r"\+91[6-9][0-9]{9}", r.body) for r in rows), "typed phone numbers are tokenised, never stored"

    assert feed.reset(conn, "bank") == len(rows)
    assert _balance(conn) == before, "undo returns the money"
    assert conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"), {"a": ACCOUNT}).scalar() == token_before
    assert conn.execute(text("SELECT count(*) FROM feed_event WHERE strand = 'bank'")).scalar() == 0


def test_bank_sessions_are_separate_from_sutra(client, as_user, conn, monkeypatch):
    r = client.post(f"{API}/bank/staff/login", json={"employee_id": OFFICER, "channel": "BRANCH"})
    assert r.status_code == 200, r.text
    staff = {"X-Bank-Token": r.json()["token"]}
    me = client.get(f"{API}/bank/staff/me", headers=staff).json()
    assert me["employee"]["id"] == OFFICER and me["channel"] == "BRANCH"

    assert client.get(f"{API}/bank/staff/me").status_code == 401, "no bank session, no access"
    sutra_token = as_user("ananya")["Authorization"].split()[1]
    assert client.get(f"{API}/bank/staff/me", headers={"X-Bank-Token": sutra_token}).status_code == 401, \
        "a SUTRA session is not a bank session"
    cust = client.post(f"{API}/bank/customer/login", json={"customer_id": CUSTOMER, "new_device": False}).json()
    assert client.get(f"{API}/bank/staff/me", headers={"X-Bank-Token": cust["token"]}).status_code == 401, \
        "a customer session cannot use the staff console"
    refused = client.post(f"{API}/bank/staff/mobile", headers=staff,
                          json={"account_id": ACCOUNT, "new_mobile": "12345", "auth": "OTP_OLD_NUMBER"})
    assert refused.status_code == 422 and "10-digit" in refused.json()["detail"]

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.get(f"{API}/bank/clock").status_code == 404


def test_customer_login_records_where_it_came_from(client, conn):
    """The Fraud Simulator signs an outsider in from another city; the session row must say so."""
    away = client.post(f"{API}/bank/customer/login", json={"customer_id": CUSTOMER, "new_device": True, "city": "Kolkata"})
    assert away.status_code == 200, away.text
    home = client.post(f"{API}/bank/customer/login", json={"customer_id": CUSTOMER, "new_device": False}).json()
    city = dict(conn.execute(text("SELECT id, geo_city FROM session WHERE id = ANY(:s)"),
                             {"s": [away.json()["session_id"], home["session_id"]]}).all())
    assert city[away.json()["session_id"]] == "Kolkata"
    assert city[home["session_id"]] != "Kolkata", "without a city the customer signs in from home"


# ── the REST contract used by scripts and the test dashboard ───────────────


def test_rest_account_and_payment_contract(client, conn):
    acct = client.get(f"{API}/bank/accounts/A-3007").json()
    assert {"accountId", "accountNumber", "name", "balance", "currency", "status", "kycStatus", "environment"} <= set(acct)
    assert acct["accountNumber"] == "XXXX3007" and acct["currency"] == "INR" and "NO REAL MONEY" in acct["environment"]
    missing = client.get(f"{API}/bank/accounts/A-0000")
    assert missing.status_code == 404 and missing.json()["code"] == "ACCOUNT_NOT_FOUND"

    pay = {"fromAccount": "A-3007", "toAccount": "X-1510", "amount": 500, "channel": "UPI"}
    ok = client.post(f"{API}/bank/transactions", json=pay)
    assert ok.status_code == 200, ok.text
    t = ok.json()
    assert {"transactionId", "amount", "currency", "status", "timestamp", "sender", "receiver"} <= set(t)
    assert t["status"] == "SUCCESS" and t["amount"] == 500 and t["sender"] == "A-3007" and t["receiver"] == "X-1510"
    assert client.get(f"{API}/bank/transactions/{t['transactionId']}").json()["transactionId"] == t["transactionId"]

    def code(body, status):
        r = client.post(f"{API}/bank/transactions", json={**pay, **body})
        assert r.status_code == status, r.text
        return r.json()["code"]

    assert code({"toAccount": "X-1003"}, 422) == "PAYEE_NOT_REGISTERED"
    assert code({"amount": 1_50_000}, 422) == "LIMIT_EXCEEDED"
    assert code({"fromAccount": "A-3341", "toAccount": "X-3545", "amount": 2_00_000}, 422) == "INSUFFICIENT_FUNDS"
    rows = conn.execute(text("SELECT count(*) FROM feed_event WHERE strand = 'bank'")).scalar()
    assert code({"simulateFailure": True}, 502) == "SWITCH_FAILED"
    assert conn.execute(text("SELECT count(*) FROM feed_event WHERE strand = 'bank'")).scalar() == rows, \
        "a declined payment leaves nothing in the bank's records"
    assert client.post(f"{API}/bank/accounts/A-1832/block").json()["status"] == "BLOCKED"
    assert code({"fromAccount": "A-1832", "toAccount": "X-1209"}, 423) == "ACCOUNT_BLOCKED"


def test_scenarios_answer_as_documented(client, conn):
    from app.loom import bank_scenarios

    keys = [s["key"] for s in client.get(f"{API}/bank/test/scenarios").json()]
    assert keys == list(bank_scenarios.SCENARIOS)
    for key, code in (("insufficient", "INSUFFICIENT_FUNDS"), ("invalid", "ACCOUNT_NOT_FOUND"), ("failed", "SWITCH_FAILED")):
        out = client.post(f"{API}/bank/test/scenario/{key}").json()
        assert out["bankResponse"]["code"] == code and out["recorded"] == 0, key
    first = client.post(f"{API}/bank/test/scenario/normal").json()
    assert first["bankResponse"]["status"] == "SUCCESS" and first["recorded"] == 2
    again = client.post(f"{API}/bank/test/scenario/normal")
    assert again.status_code == 409 and again.json()["code"] == "SCENARIO_ALREADY_RUN"
