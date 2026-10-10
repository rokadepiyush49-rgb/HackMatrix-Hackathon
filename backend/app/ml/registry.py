"""Model lifecycle: candidate → validate → promote, with an archive to roll back to (docs/ml/MODEL_LIFECYCLE.md).

Training never replaces the model detection uses. `make train` writes each model as a *candidate*; the
candidate is validated against the gates below and against the model currently approved; only a
candidate that passes is promoted. Promotion archives the approved file first, then swaps the candidate in
with an atomic rename, so a reader sees the old model or the new one and never half a file. `rollback`
restores the last archived model. Ingesting events and running detection never train anything: they only
`load` the approved artifact.

  ml/artifacts/<name>.joblib            the approved model (the path detection and the image use)
  ml/artifacts/candidates/<name>-<ts>   candidates awaiting validation
  ml/artifacts/archive/<name>-<ts>      previously approved models
  ml/artifacts/registry.json            version, checksum, training data, metrics, libraries, validation

`load` checks the file against the registry's SHA-256 and the libraries it was built with. An unreadable,
altered or incompatible artifact is refused and logged; detection then runs on rules alone, as it does when
no model exists.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np

from app.core.config import get_settings

log = logging.getLogger("sutra.ml.registry")

# Absolute floors (grouped out-of-fold, synthetic) and the largest drop from the approved model we accept.
GATES = {
    "chain_classifier": {"floors": {"roc_auc_oof": 0.85, "pr_auc_oof": 0.70}, "ceil": {"brier_oof": 0.08},
                         "regression": {"pr_auc_oof": 0.03}, "min_positives": 15},
    "mule_model": {"floors": {"pr_auc_oof": 0.80, "precision_at_k": 0.75}, "ceil": {},
                   "regression": {"pr_auc_oof": 0.03}, "min_positives": 30},
    "case_prioritiser": {"floors": {"pr_auc_oof": 0.80}, "ceil": {"brier_oof": 0.10},
                         "regression": {"pr_auc_oof": 0.03}, "min_positives": 30},
}


def _features(name: str) -> list[str]:
    from app.ml.case_features import CASE_FEATURES
    from app.ml.features import CHAIN_FEATURES, MULE_FEATURES

    return {"chain_classifier": CHAIN_FEATURES, "mule_model": MULE_FEATURES, "case_prioritiser": CASE_FEATURES}[name]


def schema_sha(features: list[str]) -> str:
    return hashlib.sha256(json.dumps(list(features)).encode()).hexdigest()[:16]


def _root() -> Path:
    return get_settings().artifacts_path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_registry() -> dict:
    p = _root() / "registry.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        log.error("registry.unreadable path=%s", p)
        return {}


def _write_registry(reg: dict) -> None:
    _atomic_write_bytes(_root() / "registry.json", json.dumps(reg, indent=2, default=str).encode())


def save_candidate(name: str, art: dict) -> Path:
    """Write a trained model as a candidate (atomically). Nothing that serves predictions reads it."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = _root() / "candidates" / f"{name}-{stamp}.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        joblib.dump(art, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


@dataclass
class Validation:
    ok: bool
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        self.ok = self.ok and bool(ok)


def _probe(name: str, art: dict) -> np.ndarray:
    n = len(art["features"])
    X = np.zeros((2, n))
    X[1] = 1.0
    if name == "chain_classifier":
        d = art["lr"].decision_function(art["scaler"].transform(X))
        return art["platt"].predict_proba(d.reshape(-1, 1))[:, 1]
    if name == "mule_model":
        return art["model"].predict_proba(X)[:, 1]
    raw = art["model"].booster_.predict(X, raw_score=True)
    return art["calibrator"].predict_proba(raw.reshape(-1, 1))[:, 1]


def validate_candidate(name: str, art: dict, current: dict | None) -> Validation:
    """Gates a candidate must pass before it may serve predictions."""
    v = Validation(True)
    gates = GATES[name]
    expected = _features(name)
    v.add("feature_schema", list(art.get("features", [])) == list(expected),
          f"features match the inference code ({len(expected)} columns, schema {schema_sha(expected)})")
    m = art.get("metrics") or {}
    v.add("training_data", m.get("positives", 0) >= gates["min_positives"],
          f"{m.get('positives', 0)} positive examples (need ≥ {gates['min_positives']})")
    for k, floor in gates["floors"].items():
        v.add(f"floor:{k}", (m.get(k) or 0) >= floor, f"{k} {m.get(k)} ≥ {floor}")
    for k, ceil in gates["ceil"].items():
        v.add(f"ceiling:{k}", m.get(k) is not None and m[k] <= ceil, f"{k} {m.get(k)} ≤ {ceil}")
    if current is not None and current.get("metrics"):
        for k, tol in gates["regression"].items():
            old, new = current["metrics"].get(k), m.get(k)
            if old is not None and new is not None:
                v.add(f"no_regression:{k}", new >= old - tol, f"{k} {new} vs approved {old} (tolerance {tol})")
    try:
        p = _probe(name, art)
        v.add("smoke_prediction", bool(np.all(np.isfinite(p)) and np.all((p >= 0) & (p <= 1))),
              "predicts finite probabilities on probe rows")
    except Exception as e:  # a candidate that cannot predict is simply not promoted
        v.add("smoke_prediction", False, f"prediction failed ({type(e).__name__})")
    leak = {11, 42} & set(art.get("train_seeds", []))
    v.add("no_heldout_worlds", not leak, "trained only on training worlds" if not leak else f"held-out seeds {sorted(leak)} used")
    return v


def promote(name: str, candidate: Path, art: dict, validation: Validation, data: dict | None = None) -> dict:
    """Archive the approved model, swap the validated candidate in atomically, record it, reload."""
    if not validation.ok:
        raise ValueError(f"{name}: candidate failed validation — not promoted")
    root = _root()
    live = root / f"{name}.joblib"
    reg = read_registry()
    entry = reg.get(name, {})
    history = entry.get("history", [])
    if live.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        arch = root / "archive" / f"{name}-{stamp}.joblib"
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, arch)
        if entry.get("sha256"):
            history.append({k: entry.get(k) for k in ("version", "sha256", "trained_at", "metrics", "promoted_at")}
                           | {"archive": str(arch.relative_to(root))})
    os.replace(candidate, live)
    reg[name] = {
        "version": art.get("version"), "sha256": _sha256(live), "trained_at": art.get("trained_at"),
        "train_seeds": art.get("train_seeds"), "n_train": art.get("n_train"), "features": list(art.get("features", [])),
        "feature_schema": schema_sha(art.get("features", [])), "metrics": art.get("metrics"),
        "libraries": art.get("libraries"), "hyperparameters": _hyper(art), "data": data or {},
        "validation": validation.checks, "status": "approved", "promoted_at": datetime.now(UTC).isoformat(),
        "history": history[-10:],
    }
    _write_registry(reg)
    from app.ml.models import reload

    reload()
    log.info("model.promoted name=%s sha256=%s", name, reg[name]["sha256"][:12])
    return reg[name]


def _hyper(art: dict) -> dict:
    for key in ("model", "lr"):
        est = art.get(key)
        if est is not None and hasattr(est, "get_params"):
            return {k: v for k, v in est.get_params().items() if isinstance(v, int | float | str | bool) or v is None}
    return {}


def reject(name: str, candidate: Path, validation: Validation) -> None:
    """Keep the failed candidate for inspection and record why it was not promoted."""
    reg = read_registry()
    entry = reg.setdefault(name, {})
    entry.setdefault("rejected", []).append({"candidate": candidate.name, "at": datetime.now(UTC).isoformat(),
                                             "failed": [c for c in validation.checks if not c["ok"]]})
    entry["rejected"] = entry["rejected"][-10:]
    _write_registry(reg)
    log.warning("model.rejected name=%s failed=%s", name, [c["check"] for c in validation.checks if not c["ok"]])


def rollback(name: str) -> dict:
    """Restore the most recently archived model as the approved one."""
    root = _root()
    reg = read_registry()
    entry = reg.get(name) or {}
    history = entry.get("history") or []
    if not history:
        raise ValueError(f"{name}: nothing to roll back to")
    prev = history.pop()
    src = root / prev["archive"]
    if not src.exists() or _sha256(src) != prev["sha256"]:
        raise ValueError(f"{name}: archived model {prev['archive']} is missing or altered")
    tmp = root / f".{name}.rollback.tmp"
    shutil.copy2(src, tmp)
    os.replace(tmp, root / f"{name}.joblib")
    reg[name] = {**entry, **{k: prev.get(k) for k in ("version", "sha256", "trained_at", "metrics")},
                 "status": "approved", "promoted_at": datetime.now(UTC).isoformat(), "rolled_back_from": entry.get("sha256"),
                 "history": history}
    _write_registry(reg)
    from app.ml.models import reload

    reload()
    log.warning("model.rolled_back name=%s to=%s", name, prev["sha256"][:12])
    return reg[name]


@dataclass
class LoadResult:
    artifact: dict | None
    status: str  # ok | missing | unregistered | altered | unreadable | incompatible
    detail: str = ""


def _minor(v: str | None) -> str:
    return ".".join((v or "").split(".")[:2])


def load(name: str) -> LoadResult:
    """The approved artifact, or None with the reason it was refused."""
    import lightgbm
    import sklearn

    path = _root() / f"{name}.joblib"
    if not path.exists():
        return LoadResult(None, "missing", "no approved model — run `make train`")
    entry = read_registry().get(name)
    if entry and entry.get("sha256") and _sha256(path) != entry["sha256"]:
        log.error("model.refused name=%s reason=checksum", name)
        return LoadResult(None, "altered", "file does not match the registry's SHA-256")
    try:
        art = joblib.load(path)
    except Exception as e:  # corrupted or truncated file
        log.error("model.refused name=%s reason=unreadable type=%s", name, type(e).__name__)
        return LoadResult(None, "unreadable", f"cannot be read ({type(e).__name__})")
    if not isinstance(art, dict) or "features" not in art:
        return LoadResult(None, "unreadable", "not a SUTRA model artifact")
    built = art.get("libraries") or {}
    now = {"scikit-learn": sklearn.__version__, "lightgbm": lightgbm.__version__}
    bad = [f"{k} {built.get(k)} → {v}" for k, v in now.items() if built.get(k) and _minor(built[k]) != _minor(v)]
    if bad:
        log.error("model.refused name=%s reason=incompatible %s", name, bad)
        return LoadResult(None, "incompatible", "built with different library versions: " + "; ".join(bad))
    if list(art["features"]) != list(_features(name)):
        return LoadResult(None, "incompatible", "feature schema differs from the inference code")
    return LoadResult(art, "ok" if entry else "unregistered",
                      "" if entry else "approved file has no registry entry (built before the registry existed)")


def status() -> dict:
    """What serves predictions now, for readiness and the governance registry."""
    reg = read_registry()
    out = {}
    for name in GATES:
        r = load(name)
        e = reg.get(name, {})
        out[name] = {"status": r.status, "detail": r.detail, "version": e.get("version"), "sha256": e.get("sha256"),
                     "promoted_at": e.get("promoted_at"), "archived": len(e.get("history") or []),
                     "rejected": len(e.get("rejected") or [])}
    return out
