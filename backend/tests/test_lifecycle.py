"""Model lifecycle (app.ml.registry): training writes candidates; only a validated candidate is promoted;
the approved model is archived first and can be rolled back; a missing, altered, unreadable or incompatible
artifact is refused and detection runs on rules. Ingest and detection never train.

Runs in a temporary artifacts directory, seeded from the approved models (needs `make train`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import joblib
import pytest

from app.core.config import REPO_ROOT, Settings, get_settings
from app.ml import models, registry

REAL = REPO_ROOT / "ml" / "artifacts"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    if not (REAL / "chain_classifier.joblib").exists():
        pytest.skip("model artifacts not built — run `make train`")
    monkeypatch.setattr(Settings, "artifacts_path", property(lambda self: tmp_path))
    models.reload()
    yield tmp_path
    models.reload()


def _art(name: str) -> dict:
    return joblib.load(REAL / f"{name}.joblib")


def _promote(name: str, art: dict):
    path = registry.save_candidate(name, art)
    v = registry.validate_candidate(name, art, registry.load(name).artifact)
    assert v.ok, [c for c in v.checks if not c["ok"]]
    return registry.promote(name, path, art, v, {"train_worlds": ["test"]})


def test_promotion_records_the_model_and_serves_it(store):
    art = _art("chain_classifier")
    assert registry.load("chain_classifier").status == "missing"
    entry = _promote("chain_classifier", art)
    assert (store / "chain_classifier.joblib").exists() and not list((store / "candidates").glob("*"))
    assert entry["sha256"] == registry._sha256(store / "chain_classifier.joblib")
    assert entry["feature_schema"] == registry.schema_sha(art["features"])
    assert {c["check"] for c in entry["validation"]} >= {"feature_schema", "smoke_prediction", "no_heldout_worlds"}
    assert registry.load("chain_classifier").status == "ok"
    assert models.score_chain({}) is not None
    assert not list(store.rglob("*.tmp")), "writes are atomic: no temporary files left behind"


def test_a_worse_candidate_is_not_promoted_and_the_approved_model_keeps_serving(store):
    art = _art("chain_classifier")
    _promote("chain_classifier", art)
    before = registry._sha256(store / "chain_classifier.joblib")
    worse = {**art, "metrics": {**art["metrics"], "pr_auc_oof": art["metrics"]["pr_auc_oof"] - 0.10}}
    path = registry.save_candidate("chain_classifier", worse)
    v = registry.validate_candidate("chain_classifier", worse, registry.load("chain_classifier").artifact)
    assert not v.ok and any(c["check"] == "no_regression:pr_auc_oof" and not c["ok"] for c in v.checks)
    with pytest.raises(ValueError):
        registry.promote("chain_classifier", path, worse, v)
    registry.reject("chain_classifier", path, v)
    assert registry._sha256(store / "chain_classifier.joblib") == before
    assert registry.read_registry()["chain_classifier"]["rejected"][-1]["failed"]


def test_feature_schema_and_heldout_leakage_are_gated(store):
    art = _art("mule_model")
    shuffled = {**art, "features": list(reversed(art["features"]))}
    assert not registry.validate_candidate("mule_model", shuffled, None).ok
    leaked = {**art, "train_seeds": [7, 8, 42]}
    v = registry.validate_candidate("mule_model", leaked, None)
    assert not v.ok and any(c["check"] == "no_heldout_worlds" and not c["ok"] for c in v.checks)


def test_rollback_restores_the_previous_model(store):
    art = _art("chain_classifier")
    first = _promote("chain_classifier", art)["sha256"]
    second_art = {**art, "version": "9.9", "trained_at": "later"}
    second = _promote("chain_classifier", second_art)["sha256"]
    assert first != second and registry.read_registry()["chain_classifier"]["history"]
    restored = registry.rollback("chain_classifier")
    assert restored["sha256"] == first == registry._sha256(store / "chain_classifier.joblib")
    assert registry.load("chain_classifier").artifact["version"] == art["version"]


def test_altered_unreadable_and_incompatible_artifacts_are_refused(store):
    art = _art("chain_classifier")
    _promote("chain_classifier", art)
    live = store / "chain_classifier.joblib"
    live.write_bytes(live.read_bytes()[:-50])  # truncated after promotion
    assert registry.load("chain_classifier").status == "altered"
    (store / "registry.json").unlink()
    assert registry.load("chain_classifier").status == "unreadable"
    joblib.dump({**art, "libraries": {**art["libraries"], "scikit-learn": "0.24.2"}}, live)
    r = registry.load("chain_classifier")
    assert r.status == "incompatible" and "scikit-learn" in r.detail
    models.reload()
    assert models.score_chain({}) is None, "a refused model means rules only, never a crash"


def test_readiness_reports_a_refused_model(store, client):
    live = store / "chain_classifier.joblib"
    live.write_bytes(b"not a model")
    models.reload()
    r = client.get("/health/ready")
    assert r.status_code == 503 and "chain_classifier: unreadable" in r.json()["checks"]["models"]


def test_ingest_and_detection_never_import_training():
    code = ("import sys; import app.pipeline, app.loom.feed, app.loom.replay, app.api.live, app.api.workbench; "
            "print('app.ml.train' in sys.modules)")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "backend"), str(REPO_ROOT / "data" / "kestrel_sim")])}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=REPO_ROOT, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "False", "the ingest/detect path must not even import the trainer"


def test_registry_file_is_valid_json_after_every_write(store):
    _promote("mule_model", _art("mule_model"))
    json.loads(Path(store / "registry.json").read_text())
    assert get_settings().artifacts_path == store
