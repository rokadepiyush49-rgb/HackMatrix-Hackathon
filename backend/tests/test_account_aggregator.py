"""Account Aggregator: consent gates every fetch, ReBIT DEPOSIT data is validated and stripped of identity
fields, re-fetching is idempotent, revocation purges, the data source is always labelled, and consented
statements answer the council's source-of-funds request. No network: Setu is exercised with a fake."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import text

from app.integrations.aa import service
from app.integrations.aa.normalize import normalise
from app.integrations.aa.providers import AAError, SetuSandboxProvider, SyntheticAAProvider

API = "/api/v1"


def _tx(**kw) -> dict:
    t = {"txnId": "T1", "type": "CREDIT", "mode": "UPI", "amount": 1250.5, "currentBalance": "10250.50",
         "transactionTimestamp": "2026-09-01T10:00:00+05:30", "valueDate": "2026-09-01",
         "narration": "UPI/RENT", "reference": "R1"}
    return {**t, **kw}


def _payload(txs: list[dict]) -> dict:
    return {"Payload": [{"fipID": "TEST-FIP", "data": [{"maskedAccNumber": "XXXXXX1234", "decryptedFI": {"account": {
        "maskedAccNumber": "XXXXXX1234", "type": "deposit",
        "profile": {"holders": {"holder": [{"name": "Real Name", "pan": "ABCDE1234F", "mobile": "9876543210"}]}},
        "summary": {"currentBalance": "10250.50", "type": "SAVINGS", "status": "ACTIVE"},
        "transactions": {"startDate": "2026-09-01", "endDate": "2026-09-30", "transaction": txs}}}}]}]}


# ── normalisation (no database) ────────────────────────────────────────────


def test_rebit_deposit_rows_are_normalised_and_identity_fields_dropped():
    rows, summaries, rejected = normalise(_payload([_tx(), _tx(txnId="T2", type="DEBIT", mode="ATM", amount=500)]))
    assert not rejected and [r.txn_id for r in rows] == ["T1", "T2"]
    assert rows[0].amount_paise == 125050 and rows[0].balance_paise == 1025050
    assert rows[0].masked_account == "XXXXXX1234" and summaries[0]["type"] == "SAVINGS"
    blob = json.dumps([r.as_dict() for r in rows] + summaries)
    assert "Real Name" not in blob and "ABCDE1234F" not in blob and "9876543210" not in blob


@pytest.mark.parametrize("bad, reason", [
    ({"txnId": ""}, "txnId"), ({"type": "REFUND"}, "CREDIT or DEBIT"), ({"mode": "NEFT"}, "transaction mode"),
    ({"amount": -5}, "positive"), ({"amount": "NaN"}, "finite"),
    ({"transactionTimestamp": "2026-09-01T10:00:00"}, "time zone"),
])
def test_invalid_rows_are_rejected_with_a_reason(bad, reason):
    rows, _, rejected = normalise(_payload([_tx(), _tx(**{"txnId": "BAD", **bad})]))
    assert len(rows) == 1 and len(rejected) == 1 and reason in rejected[0]["reason"]


def test_full_account_numbers_in_narration_are_masked():
    (row,), _, _ = normalise(_payload([_tx(narration="NEFT FROM 123456789012 SALARY")]))
    assert "123456789012" not in row.narration and "9012" in row.narration


def test_synthetic_statements_are_deterministic_and_labelled():
    p = SyntheticAAProvider()
    a = p.fetch("C1", date(2026, 4, 1), date(2026, 9, 30), "C-12345")
    b = p.fetch("C1", date(2026, 4, 1), date(2026, 9, 30), "C-12345")
    assert a == b and p.data_source == "SYNTHETIC_DEMO"
    rows, _, rejected = normalise(a)
    assert rows and not rejected and "fictional" in json.dumps(a)


# ── Setu sandbox adapter (fake transport) ──────────────────────────────────


def test_setu_consent_request_shape_and_errors():
    calls = []

    def fake(url, body, headers, timeout):
        calls.append((url, json.loads(body) if body else None, headers))
        if url.endswith("/consents"):
            return 201, {}, json.dumps({"id": "cid-1", "url": "https://fiu-sandbox.example/consents/webview/cid-1",
                                        "status": "PENDING"}).encode()
        return 401, {}, json.dumps({"errorCode": "Unauthorized", "errorMsg": "bad creds"}).encode()

    p = SetuSandboxProvider("https://fiu-sandbox.example", "id-1", "secret-xyz", "pi-1", transport=fake)
    assert "secret-xyz" not in repr(p)
    out = p.create_consent("9999999999@setu", date(2026, 4, 1), date(2026, 9, 30), "Source-of-funds review")
    assert out == {"id": "cid-1", "status": "PENDING", "url": "https://fiu-sandbox.example/consents/webview/cid-1"}
    url, body, headers = calls[0]
    assert url == "https://fiu-sandbox.example/consents" and headers["x-client-id"] == "id-1"
    assert body["Detail"]["fiTypes"] == ["DEPOSIT"] and body["Detail"]["consentMode"] == "VIEW"
    assert body["Detail"]["FIDataRange"]["from"].startswith("2026-04-01")
    with pytest.raises(AAError) as e:
        p.consent_status("cid-1")
    assert e.value.kind == "auth" and "secret-xyz" not in str(e.value)
    with pytest.raises(AAError):
        SetuSandboxProvider("", "", "", "")


# ── end to end on the database ─────────────────────────────────────────────


@pytest.fixture()
def structuring(db):
    row = db.execute(text("""
        SELECT a.id, acc.customer_id FROM alert a JOIN chain c ON c.id = a.chain_id
        JOIN account acc ON acc.id = c.account_id
        WHERE a.typology = 'STRUCTURING' AND acc.customer_id IS NOT NULL ORDER BY a.id LIMIT 1""")).first()
    if row is None:
        pytest.skip("needs a detected structuring alert")
    return row.id, row.customer_id


def test_consent_gates_fetch_and_refetch_is_idempotent(db, structuring):
    _, customer = structuring
    c = service.create(db, customer, 6, "Source-of-funds review for an open investigation", "ananya")
    assert c["status"] == "PENDING" and c["data_source"] == "SYNTHETIC_DEMO"
    with pytest.raises(AAError) as e:
        service.fetch(db, c["id"], "ananya")
    assert e.value.kind == "conflict", "nothing is fetched before the customer approves"
    service.approve_synthetic(db, c["id"], "ananya")
    first = service.fetch(db, c["id"], "ananya")
    again = service.fetch(db, c["id"], "ananya")
    assert first["outcomes"]["NEW"] > 0 and not first["rejected"]
    assert again["outcomes"] == {"NEW": 0, "DUPLICATE": first["outcomes"]["NEW"], "CONFLICT": 0}
    actions = db.execute(text("SELECT action FROM audit_log WHERE target = :t ORDER BY id"), {"t": c["id"]}).scalars().all()
    assert actions[:3] == ["aa.consent.create", "aa.consent.approve_synthetic", "aa.fetch"]


def test_revocation_purges_the_statement(db, structuring):
    _, customer = structuring
    c = service.create(db, customer, 3, "Source-of-funds review for an open investigation", "ananya")
    service.approve_synthetic(db, c["id"], "ananya")
    service.fetch(db, c["id"], "ananya")
    out = service.revoke(db, c["id"], "ananya")
    assert out["status"] == "REVOKED" and out["purged_rows"] > 0 and out["rows"] == 0
    with pytest.raises(AAError):
        service.fetch(db, c["id"], "ananya")


def test_consented_statement_answers_the_councils_source_of_funds_request(db, structuring):
    from app.api.workbench import _council_inputs
    from app.council.engine import Council

    alert_id, customer = structuring
    detail, m, look = _council_inputs(db, alert_id)
    before = Council(detail, m, look).run()
    sof_before = next(r for r in before["requests"] if r["record"].startswith("Source-of-funds"))
    assert sof_before["status"] == "NOT_FOUND" and "request consent" in sof_before["result"]

    c = service.create(db, customer, 6, "Source-of-funds review for an open investigation", "ananya", alert_id)
    service.approve_synthetic(db, c["id"], "ananya")
    service.fetch(db, c["id"], "ananya")
    detail, m, look = _council_inputs(db, alert_id)
    after = Council(detail, m, look).run()
    sof = next(r for r in after["requests"] if r["record"].startswith("Source-of-funds"))
    assert sof["status"] == "RETRIEVED" and sof["evidence"] and sof["system"] == "Account Aggregator"
    aa = [e for e in detail["evidence"] if e["kind"] == "AA_STATEMENT"]
    assert aa and all(e["summary"].startswith("[synthetic demo data]") for e in aa)
    assert all(e["facts"]["data_source"] == "SYNTHETIC_DEMO" for e in aa)


def test_api_labels_the_source_and_hides_the_synthetic_provider_outside_demo_mode(client, as_user, structuring,
                                                                                  monkeypatch):
    from app.core.config import get_settings

    _, customer = structuring
    h = as_user("ananya")
    assert client.get(f"{API}/aa/status", headers=h).json()["data_source"] == "SYNTHETIC_DEMO"
    r = client.post(f"{API}/aa/consents", headers=h, json={"customer_id": customer})
    assert r.status_code == 201 and r.json()["data_source"] == "SYNTHETIC_DEMO"
    assert client.post(f"{API}/aa/consents/{r.json()['id']}/fetch", headers=h).status_code == 409
    assert client.post(f"{API}/aa/consents", headers=as_user("rohit"), json={"customer_id": customer}).status_code == 403
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.get(f"{API}/aa/consents", headers=h).status_code == 404
