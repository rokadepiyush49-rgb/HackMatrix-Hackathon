"""Production plumbing: storage, configuration guards, health checks, request IDs."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.storage import LocalStorage

STRONG = "x" * 48


@pytest.fixture(autouse=True)
def _no_sutra_env(monkeypatch):
    """CI exports strong secrets; the configuration-guard tests must see only their own arguments."""
    for name in ("SUTRA_ENV", "SUTRA_JWT_SECRET", "SUTRA_PII_HMAC_KEY", "SUTRA_DEMO_MODE",
                 "SUTRA_STORAGE_BACKEND", "SUTRA_S3_BUCKET", "SUTRA_EVIDENCE_LOCK_MODE"):
        monkeypatch.delenv(name, raising=False)


def cfg(**kw) -> Settings:
    """Settings from arguments only — never the developer's .env or the process environment."""
    return Settings(_env_file=None, **kw)


# ── storage ────────────────────────────────────────────────────────────────


def test_local_storage_round_trip(tmp_path):
    s = LocalStorage(tmp_path)
    s.put("PACK-1/pack.json", b'{"a":1}', "application/json")
    assert s.exists("PACK-1/pack.json")
    assert s.get("PACK-1/pack.json") == b'{"a":1}'
    assert not s.exists("PACK-1/missing.pdf")


def test_local_storage_refuses_path_traversal(tmp_path):
    s = LocalStorage(tmp_path / "packs")
    with pytest.raises(ValueError):
        s.put("../../etc/passwd", b"x", "text/plain")


# ── configuration guard ────────────────────────────────────────────────────


def test_dev_defaults_are_allowed():
    assert cfg(env="dev").env == "dev"


def test_prod_refuses_default_secrets_and_demo_mode():
    with pytest.raises(ValueError) as e:
        cfg(env="prod")
    msg = str(e.value)
    assert "SUTRA_JWT_SECRET" in msg and "SUTRA_PII_HMAC_KEY" in msg and "SUTRA_DEMO_MODE" in msg


def test_prod_requires_write_once_evidence():
    with pytest.raises(ValueError, match="s3"):
        cfg(env="prod", jwt_secret=STRONG, pii_hmac_key=STRONG, demo_mode=False, storage_backend="local")
    with pytest.raises(ValueError, match="COMPLIANCE"):
        cfg(env="prod", jwt_secret=STRONG, pii_hmac_key=STRONG, demo_mode=False, storage_backend="s3",
                 s3_bucket="b", evidence_lock_mode="GOVERNANCE")


def test_prod_accepts_a_safe_configuration():
    s = cfg(env="prod", jwt_secret=STRONG, pii_hmac_key=STRONG, demo_mode=False, storage_backend="s3",
                 s3_bucket="evidence", evidence_lock_mode="COMPLIANCE")
    assert s.env == "prod"


# ── HTTP surface ───────────────────────────────────────────────────────────


def test_liveness_and_request_id(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and len(r.headers["x-request-id"]) == 32
    echoed = client.get("/health/live", headers={"X-Request-ID": "trace-abc-12345"})
    assert echoed.headers["x-request-id"] == "trace-abc-12345"
    unsafe = client.get("/health/live", headers={"X-Request-ID": "<script>"})
    assert unsafe.headers["x-request-id"] != "<script>", "untrusted IDs are replaced, never echoed"


def test_readiness_checks_dependencies(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"] == {"database": "ok", "models": "ok"}


def test_evidence_pack_is_written_once_and_verifies(client, as_user, tmp_path, monkeypatch):
    from app.core import storage

    monkeypatch.setattr(storage, "get_storage", lambda: LocalStorage(tmp_path))
    import app.api.packs as packs

    monkeypatch.setattr(packs, "get_storage", lambda: LocalStorage(tmp_path))
    ananya = as_user("ananya")
    alert = next(a["id"] for a in client.get("/api/v1/alerts", headers=ananya).json() if a["typology"] == "INSIDER_ATO")
    case = client.post("/api/v1/cases", json={"alert_id": alert}, headers=ananya).json()
    pack = client.post(f"/api/v1/cases/{case['id']}/packs", headers=ananya)
    assert pack.status_code == 200, pack.text
    pid = pack.json()["id"]
    assert {p.name for p in (tmp_path / pid).iterdir()} == {"pack.json", "pack.pdf", "evidence.csv"}

    v = client.get(f"/api/v1/packs/{pid}/verify", headers=ananya).json()
    assert v["ok"] is True

    pdf = client.get(f"/api/v1/packs/{pid}/download?format=pdf", headers=ananya)
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")

    # Tampering with a stored file is detected.
    (tmp_path / pid / "evidence.csv").write_bytes(b"edited")
    assert client.get(f"/api/v1/packs/{pid}/verify", headers=ananya).json()["ok"] is False


# ── cloud integrations (skipped when the `cloud` extra isn't installed) ────


def test_s3_writes_are_object_locked_and_kms_encrypted():
    pytest.importorskip("boto3")
    from botocore.stub import ANY, Stubber

    from app.core.storage import S3Storage

    s3 = S3Storage("evidence-bucket", "packs/", "arn:aws:kms:ap-south-1:111122223333:key/abc", 1825,
                   "COMPLIANCE", "ap-south-1")
    with Stubber(s3.client) as stub:
        stub.add_response("put_object", {}, {
            "Bucket": "evidence-bucket", "Key": "packs/PACK-1/pack.pdf", "Body": b"%PDF", "ContentType": "application/pdf",
            "ChecksumAlgorithm": "SHA256", "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "arn:aws:kms:ap-south-1:111122223333:key/abc",
            "ObjectLockMode": "COMPLIANCE", "ObjectLockRetainUntilDate": ANY,
        })
        s3.put("PACK-1/pack.pdf", b"%PDF", "application/pdf")
        stub.assert_no_pending_responses()


def test_tracing_switches_on_only_with_an_endpoint(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    from fastapi import FastAPI

    from app.core.db import engine
    from app.core.observability import configure_tracing

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert configure_tracing(FastAPI(), engine) is False
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    assert configure_tracing(FastAPI(), engine) is True
