"""API contract, access control and the two-person rules. Every test is rolled back."""

from __future__ import annotations

import re

import pytest

API = "/api/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture()
def insider(client, as_user) -> str:
    alerts = client.get(f"{API}/alerts", headers=as_user("ananya")).json()
    return next(a["id"] for a in alerts if a["typology"] == "INSIDER_ATO")


def _walk_keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | set().union(*(_walk_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_walk_keys(v) for v in obj)) if obj else set()
    return set()


# ── auth ───────────────────────────────────────────────────────────────────


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_requests_without_a_token_are_rejected(client):
    assert client.get(f"{API}/alerts").status_code == 401


def test_login(client):
    from app.core.config import get_settings

    bad = client.post(f"{API}/auth/login", json={"username": "ananya", "password": "not-the-password"})
    assert bad.status_code == 401
    ok = client.post(f"{API}/auth/login", json={"username": "ananya", "password": get_settings().demo_password})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


# ── alerts are argued, graded and hashed ───────────────────────────────────


def test_queue_holds_only_argued_priorities(client, as_user):
    alerts = client.get(f"{API}/alerts", headers=as_user("rohit")).json()
    assert alerts and {a["priority"] for a in alerts} <= {"P1", "P2", "P3"}
    everything = client.get(f"{API}/chains", headers=as_user("rohit")).json()
    assert len(everything) > len(alerts), "watch-listed and explained chains stay visible in the explorer"


def test_alert_detail_is_evidence_backed(client, as_user, insider):
    a = client.get(f"{API}/alerts/{insider}", headers=as_user("ananya")).json()
    codes = {e["code"] for e in a["evidence"]}
    assert all(HEX64.match(e["sha256"]) for e in a["evidence"])
    assert all(e["reliability"] in "ABCD" and 1 <= e["credibility"] <= 4 for e in a["evidence"])
    for link in a["links"]:
        assert set(link["evidence_codes"]) <= codes, link["code"]
    assert {d["level"] for d in a["dims"]} <= {"NONE", "LOW", "ELEVATED", "HIGH"}
    assert a["argument"]["rebuttals"], "the defence column is never empty"
    assert "score" not in a and "risk_score" not in a


def test_staff_are_pseudonymous_by_default(client, as_user, insider):
    emp = client.get(f"{API}/alerts/{insider}", headers=as_user("ananya")).json()["employee"]
    assert emp["name"] is None and emp["unmasked"] is False and emp["pseudonym"]


# ── council ────────────────────────────────────────────────────────────────


def test_council_never_scores_and_keeps_dissent(client, as_user, insider):
    c = client.get(f"{API}/council/{insider}", headers=as_user("ananya")).json()
    keys = _walk_keys(c)
    assert not keys & {"confidence", "score", "risk_score", "probability"}
    assert c["consensus"]["human_review"] is True
    assert c["consensus"]["dissent"], "the defence position must be recorded, not merged"
    statuses = {cl["status"] for cl in c["claims"]}
    assert statuses <= {"SUPPORTED", "CONTESTED", "UNEXPLAINED", "MISSING", "CONTRADICTORY"}
    pool = {e["code"] for e in client.get(f"{API}/alerts/{insider}", headers=as_user("ananya")).json()["evidence"]}
    for cl in c["claims"]:
        assert set(cl["evidence"]) <= pool, f"claim {cl['id']} cites records the case does not hold"
    assert any(r["status"] == "NOT_INGESTED" for r in c["requests"]), "gaps are admitted, not invented"


# ── control lab ────────────────────────────────────────────────────────────


def test_expiring_the_override_breaks_the_chain_days_early(client, as_user, insider):
    m = client.get(f"{API}/mend/{insider}?controls=C1", headers=as_user("ananya")).json()
    assert m["result"]["breaks"] and m["result"]["broken_at"]["link"] == "E0"
    assert m["result"]["lead_time_s"] > 6 * 86400
    assert m["result"]["prevented"] == pytest.approx(m["amount_at_risk"])
    by_id = {c["id"]: c for c in m["controls"]}
    assert by_id["C8"]["applicable"] is False, "a mule-factory control does not apply to this chain"
    assert m["recommended"]["id"] == "C1"


# ── access control and four-eyes ───────────────────────────────────────────


def test_auditor_cannot_open_or_decide(client, as_user):
    alerts = client.get(f"{API}/alerts", headers=as_user("audit")).json()
    cases = {c["alert_id"] for c in client.get(f"{API}/cases", headers=as_user("audit")).json()}
    fresh = next((a["id"] for a in alerts if a["id"] not in cases), None)
    if fresh:
        assert client.post(f"{API}/cases", json={"alert_id": fresh}, headers=as_user("audit")).status_code == 403


def test_four_eyes_decision(client, as_user, insider):
    ananya, meera = as_user("ananya"), as_user("meera")
    case = client.post(f"{API}/cases", json={"alert_id": insider}, headers=ananya).json()
    if case["assignee"] != "ananya":
        pytest.skip("demo case is assigned to someone else in this database")
    cid = case["id"]
    # someone who is not the assignee cannot propose
    r = client.post(f"{API}/cases/{cid}/propose", json={"decision": "ESCALATE", "reason": "EV-103, EV-111"}, headers=meera)
    assert r.status_code == 403
    r = client.post(f"{API}/cases/{cid}/propose", json={"decision": "ESCALATE", "reason": "EV-103, EV-111"}, headers=ananya)
    assert r.status_code == 200 and r.json()["state"] == "REVIEW"
    # the investigator cannot approve their own proposal
    assert client.post(f"{API}/cases/{cid}/review", json={"approve": True}, headers=ananya).status_code == 403
    r = client.post(f"{API}/cases/{cid}/review", json={"approve": True}, headers=meera)
    assert r.status_code == 200 and r.json()["state"].startswith("CLOSED")
    assert r.json()["reviewer"] == "meera"


def test_two_person_unmask(client, as_user):
    suresh = as_user("suresh")
    r = client.post(f"{API}/governance/unmask", json={"employee_id": "EMP-0417", "reason": "Attribution for CASE review"}, headers=suresh)
    assert r.status_code == 200
    rid = r.json()["id"]
    # the requester can never approve their own request
    same = client.post(f"{API}/governance/unmask/{rid}/decide", json={"approve": True}, headers=suresh)
    assert same.status_code == 409
    # a role without approval rights cannot either
    assert client.post(f"{API}/governance/unmask/{rid}/decide", json={"approve": True}, headers=as_user("karthik")).status_code == 403
    ok = client.post(f"{API}/governance/unmask/{rid}/decide", json={"approve": True}, headers=as_user("farah"))
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED" and ok.json()["expires_at"]


def test_audit_chain_verifies_after_writes(client, as_user, insider):
    client.get(f"{API}/council/{insider}", headers=as_user("ananya"))
    a = client.get(f"{API}/governance/audit?limit=5", headers=as_user("audit")).json()
    assert a["verification"]["ok"] is True
    assert a["entries"][0]["action"] == "council.run"


def test_lab_report_matches_scenarios(client, as_user):
    rep = client.get(f"{API}/lab/report", headers=as_user("ananya")).json()
    assert rep["summary"]["passed"] == rep["summary"]["total"]
    assert rep["models"]["chain_classifier"]["train_seed"] != 42, "models are trained on an independent world"


def test_copilot_answers_are_cited(client, as_user, insider):
    r = client.post(f"{API}/copilot/ask", json={"alert_id": insider, "question": "Why is this suspicious?"}, headers=as_user("ananya"))
    assert r.status_code == 200
    body = r.json()
    assert body["sentences"], "the deterministic engine always answers from evidence"
    assert all(s["evidence"] for s in body["sentences"])
