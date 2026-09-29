"""PII tokenisation and the audit hash chain."""

from datetime import UTC, datetime

from app.core.audit import GENESIS, _digest
from app.core.pii import mask_tail, tokenise


def test_tokenise_is_deterministic_and_not_reversible():
    a = tokenise("+91 98765 43210", "phone")
    assert a == tokenise(" +91 98765 43210 ", "phone"), "whitespace must not change the token"
    assert "98765" not in a and a.startswith("pho_")
    assert tokenise("+91 98765 43210", "phone") != tokenise("+91 98765 43211", "phone")


def test_tokenise_is_domain_separated():
    assert tokenise("ABCDE1234F", "pan") != tokenise("ABCDE1234F", "phone")


def test_tokenise_empty():
    assert tokenise(None, "phone") is None and tokenise("", "phone") is None


def test_mask_tail():
    assert mask_tail("9876543210") == "••••••3210"
    assert mask_tail(None) == "—"


def test_audit_digest_commits_to_every_field():
    at = datetime(2026, 9, 21, 16, 30, tzinfo=UTC)
    base = _digest(GENESIS, at, "ananya", "case.view", "CASE-1", {"x": 1})
    assert base == _digest(GENESIS, at, "ananya", "case.view", "CASE-1", {"x": 1})
    variants = [
        _digest("f" * 64, at, "ananya", "case.view", "CASE-1", {"x": 1}),
        _digest(GENESIS, at.replace(minute=31), "ananya", "case.view", "CASE-1", {"x": 1}),
        _digest(GENESIS, at, "rohit", "case.view", "CASE-1", {"x": 1}),
        _digest(GENESIS, at, "ananya", "case.review", "CASE-1", {"x": 1}),
        _digest(GENESIS, at, "ananya", "case.view", "CASE-2", {"x": 1}),
        _digest(GENESIS, at, "ananya", "case.view", "CASE-1", {"x": 2}),
    ]
    assert base not in variants and len(set(variants)) == len(variants)


def test_audit_digest_is_timezone_independent():
    from zoneinfo import ZoneInfo

    utc = datetime(2026, 9, 21, 16, 30, tzinfo=UTC)
    ist = utc.astimezone(ZoneInfo("Asia/Kolkata"))
    assert _digest(GENESIS, utc, "a", "b", None, {}) == _digest(GENESIS, ist, "a", "b", None, {})
