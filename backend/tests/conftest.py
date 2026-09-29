"""Shared fixtures.

Two kinds of test live here:

* In-memory tests generate the canonical Kestrel-Sim world (seed 42) and run the whole
  pipeline without a database — the scenario twins, Alibi and the lattice are checked this way.
* API tests need a seeded Postgres (`make demo`). Each one runs inside a transaction that is
  rolled back afterwards, so proposals, unmask requests and audit entries never persist.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def world():
    from kestrel_sim import generate

    return generate(seed=42, size="demo")


@pytest.fixture(scope="session")
def frames(world):
    from app.loom.frames import frames_from_world

    return frames_from_world(world)


@pytest.fixture(scope="session")
def result(frames):
    from app.pipeline import compute

    return compute(frames, log=False)


@pytest.fixture(scope="session")
def evaluation(world, result):
    from app.lab.evaluate import evaluate_scenarios

    return evaluate_scenarios(result, world.labels)


@pytest.fixture(scope="session")
def labels(world) -> dict[str, dict]:
    return {lab["key"]: lab for lab in world.labels}


# ── database-backed ────────────────────────────────────────────────────────


def _db_ready() -> bool:
    try:
        from sqlalchemy import text

        from app.core.db import engine

        with engine.connect() as c:
            return bool(c.execute(text("SELECT count(*) FROM alert")).scalar())
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_ready() -> bool:
    return _db_ready()


@pytest.fixture()
def db(db_ready):
    """A session bound to an outer transaction that is always rolled back."""
    if not db_ready:
        pytest.skip("needs a seeded Postgres — run `make demo`")
    from sqlalchemy.orm import Session

    from app.core.db import engine

    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture()
def client(db) -> Iterator:
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def as_user(db):
    """Headers for a demo persona, minted directly (no login round-trip, no rate limit)."""
    from app.core.security import issue_tokens
    from app.loom.models import AppUser

    def headers(user_id: str) -> dict[str, str]:
        user = db.get(AppUser, user_id)
        assert user is not None, f"demo user {user_id} is not seeded"
        return {"Authorization": f"Bearer {issue_tokens(user)['access_token']}"}

    return headers
