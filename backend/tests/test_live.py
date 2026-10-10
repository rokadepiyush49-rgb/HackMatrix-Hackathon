"""The live feed: what the simulator holds back, how ingest and reset move the bank's state, and
how alert identity survives a re-run. Database tests run inside the rolled-back test transaction."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import text

API = "/api/v1"


# ── generator (no database) ────────────────────────────────────────────────


def test_feed_is_the_evening_and_history_stays_before_it(world):
    from kestrel_sim.live import FEED_START, TIME_KEY

    feed = world.live_feed
    assert len(feed) > 200 and [e["seq"] for e in feed] == list(range(1, len(feed) + 1))
    assert all(e["t"] >= FEED_START for e in feed)
    assert [e["t"] for e in feed] == sorted(e["t"] for e in feed), "the feed replays in time order"
    held = {e["row"]["id"] for e in feed}
    for table in TIME_KEY:
        assert not held & {r["id"] for r in world.tables.get(table, [])}, f"{table} row both loaded and held back"
    strands = {s: sum(e["strand"] == s for e in feed) for s in ("attack", "camp", "routine")}
    assert strands["attack"] >= 20 and strands["camp"] >= 8 and strands["routine"] > 150


def test_feed_master_data_is_as_before_the_evening(world):
    meta = world.live_meta
    acct = world.accounts[meta["victim_account"]]
    changes = {e["effect"]["field"]: e["effect"] for e in world.live_feed
               if e["effect"] and e["effect"]["account_id"] == acct["id"]}
    assert acct["status"] == "INOPERATIVE"
    assert acct["_raw_mobile"] == changes["REGISTERED_MOBILE"]["old"] != changes["REGISTERED_MOBILE"]["new"]
    assert acct["daily_limit_paise"] == int(changes["TXN_LIMIT"]["old"]) < int(changes["TXN_LIMIT"]["new"])
    assert meta["insider"] not in ("EMP-0417", "EMP-0233", "EMP-0112"), "a different insider from the 21 Sep case"
    assert meta["camp_branch"] != meta["insider_branch"]


def test_training_world_has_no_feed():
    from kestrel_sim import generate

    assert generate(seed=7, size="tiny").live_feed == []


# ── stable identity ────────────────────────────────────────────────────────


def _brief(kind: str, root: str, first: str, last: str):
    draft = SimpleNamespace(kind=kind, root_ref=root, first_t=pd.Timestamp(first), last_t=pd.Timestamp(last))
    return SimpleNamespace(draft=draft)


def test_ids_on_an_empty_database_are_the_original_numbering():
    from app.pipeline import assign_ids

    briefs = [_brief("INSIDER_ATO", "AE-1", "2026-09-21 21:47", "2026-09-21 23:58"),
              _brief("CIRCULAR", "TX-9", "2026-09-08 10:00", "2026-09-09 12:00"),
              _brief("INSIDER_ATO", "AE-2", "2026-09-21 22:00", "2026-09-21 23:00")]
    assert assign_ids(briefs, {}) == [("CH-4401", "AL-0921-001"), ("CH-4402", "AL-0909-001"), ("CH-4403", "AL-0921-002")]


def test_known_chains_keep_their_ids_and_new_ones_continue_the_sequences():
    from app.pipeline import Known, assign_ids

    known = {("INSIDER_ATO", "AE-1"): Known("CH-4476", "AL-0921-001", True),
             ("MULE_FACTORY", "G4:EMP-0417"): Known("CH-4441", "AL-0922-002", False)}
    briefs = [_brief("MULE_FACTORY", "G4:EMP-0417", "2026-08-03", "2026-09-22 23:18"),
              _brief("INSIDER_ATO", "AE-1", "2026-09-12", "2026-09-21 23:58"),
              _brief("INSIDER_ATO", "AE-55755", "2026-09-16", "2026-09-22 22:36")]
    assert assign_ids(briefs, known) == [("CH-4441", "AL-0922-002"), ("CH-4476", "AL-0921-001"), ("CH-4477", "AL-0922-003")]


# ── ingest and reset (database, rolled back) ───────────────────────────────


def _balances(conn, accounts) -> dict[str, int]:
    rows = conn.execute(text("SELECT id, balance_paise FROM account WHERE id = ANY(:a)"), {"a": list(accounts)}).all()
    return dict(rows)


def test_ingest_applies_effects_and_reset_restores_the_bank(db):
    from app.loom import feed

    conn = db.connection()
    if not feed.status(db)["total"]:
        pytest.skip("database was seeded without a live feed — run `make seed`")
    feed.reset(conn)  # start from the held-back state, whatever the dev database was left in
    items = feed.pending(db)
    payout = next(i for i in items if i.source_table == "txn" and i.row["amount_paise"] >= 4_00_000_00)
    mobile = next(i for i in items if i.effect and i.effect["column"] == "registered_mobile_tok")
    upto = max(payout.seq, mobile.seq)
    accounts = {payout.row["from_account"], payout.row["to_account"]}
    before = _balances(conn, accounts)
    tok_before = conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"),
                              {"a": mobile.effect["account_id"]}).scalar()

    for item in items:
        if item.seq > upto:
            break
        feed.ingest(conn, item)

    after = _balances(conn, accounts)
    moved = sum(i.row["amount_paise"] for i in items if i.seq <= upto and i.source_table == "txn"
                and i.row["from_account"] == payout.row["from_account"])
    assert before[payout.row["from_account"]] - after[payout.row["from_account"]] == moved
    assert conn.execute(text("SELECT count(*) FROM txn WHERE id = :t"), {"t": payout.ref}).scalar() == 1
    assert conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"),
                        {"a": mobile.effect["account_id"]}).scalar() == mobile.effect["new"] != tok_before
    assert feed.status(db)["ingested"] == upto

    assert feed.reset(conn) == upto
    assert _balances(conn, accounts) == before
    assert conn.execute(text("SELECT count(*) FROM txn WHERE id = :t"), {"t": payout.ref}).scalar() == 0
    assert conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"),
                        {"a": mobile.effect["account_id"]}).scalar() == tok_before
    assert feed.status(db)["ingested"] == 0


def test_feed_rows_reach_the_database_tokenised(db):
    conn = db.connection()
    raw_phone = conn.execute(text("SELECT count(*) FROM feed_event WHERE row::text ~ '\\+91[6-9][0-9]{9}' "
                                  "OR effect::text ~ '\\+91[6-9][0-9]{9}'")).scalar()
    assert raw_phone == 0, "raw phone numbers must never be stored, not even in held-back rows"


# ── API ────────────────────────────────────────────────────────────────────


def test_status_and_feed_hide_ground_truth_until_the_evening_is_in(client, as_user, db):
    from app.loom import feed

    feed.reset(db.connection())
    h = as_user("ananya")
    st = client.get(f"{API}/live/status", headers=h).json()
    assert st["total"] > 200 and st["pending"] == st["total"]
    assert [s["key"] for s in st["stages"]][:3] == ["ingest", "loom", "alibi"]
    rows = client.get(f"{API}/live/feed?reveal=true", headers=h).json()
    assert rows and not any("strand" in r for r in rows), "no ground truth before the run"
    assert {"seq", "t", "system", "summary", "ref"} <= set(rows[0])
    assert "row" not in rows[0], "the UI never sees the raw source row"


def test_live_ops_exists_only_in_demo_mode(client, as_user, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.get(f"{API}/live/status", headers=as_user("ananya")).status_code == 404
    assert client.post(f"{API}/live/runs", json={}, headers=as_user("ananya")).status_code == 404


def test_starting_a_run_is_accepted_once(client, as_user, db, monkeypatch):
    """A real run writes outside the test transaction, so the worker is a stand-in that waits."""
    from app.api import live
    from app.loom import feed

    feed.reset(db.connection())
    gate, seen = threading.Event(), []

    def stand_in(run, speed, detect=True, scope="evening"):
        seen.append((run.id, speed))
        gate.wait(5)
        run.finished = True

    monkeypatch.setattr(live, "play_feed", stand_in)
    monkeypatch.setattr(live, "_active", None)
    h = as_user("ananya")
    try:
        r = client.post(f"{API}/live/runs", json={"speed": 600}, headers=h)
        assert r.status_code == 202
        assert client.post(f"{API}/live/runs", json={"speed": 600}, headers=h).status_code == 409, "one run at a time"
    finally:
        gate.set()
    for _ in range(50):
        if seen:
            break
        time.sleep(0.02)
    assert seen == [(r.json()["run_id"], 600.0)]


def test_run_events_replay_from_the_start(client, as_user, monkeypatch):
    from app.api import live

    run = live.Run(id="LIVE-TEST", kind="feed", actor="ananya", started_at=datetime.now().isoformat())
    run.emit("start", {"run": run.id})
    run.emit("event", {"seq": 1})
    run.emit("done", {"elapsed": 1.0})
    run.finished = True
    monkeypatch.setitem(live._runs, run.id, run)
    body = client.get(f"{API}/live/runs/{run.id}/events", headers=as_user("ananya")).text
    assert body.index("event: start") < body.index("event: event") < body.index("event: done") < body.index("event: end")
    resumed = client.get(f"{API}/live/runs/{run.id}/events", headers={**as_user("ananya"), "Last-Event-ID": "1"}).text
    assert "event: start" not in resumed and "event: done" in resumed


# ── your input (compose) ───────────────────────────────────────────────────

RAW_PHONE = r"\+91[6-9][0-9]{9}"


def _spec(db, **over):
    from app.loom import compose

    o = compose.options(db.connection())
    acct = o["accounts"][0]
    staff = next(s for s in o["staff"] if not s["in_story"])
    amount = min(4_00_000, int(acct["balance"]) // 3)
    return compose.Spec(**{"employee_id": staff["id"], "account_id": acct["id"], "amount": amount, **over})


def test_compose_writes_what_each_system_would_record(db):
    import re

    from app.loom import compose, feed

    conn = db.connection()
    feed.reset(conn)
    spec = _spec(db)
    rows = compose.build(conn, spec)
    by = {}
    for r in rows:
        by.setdefault(r["table"], []).append(r["row"])
    assert [r["t"] for r in rows] == sorted(r["t"] for r in rows)
    assert {a["action"] for a in by["access_event"]} == {"CUST_SEARCH", "ACCT_VIEW", "MOBILE_UPDATE", "LIMIT_CHANGE"}
    assert next(a for a in by["access_event"] if a["action"] == "MOBILE_UPDATE")["override_used"] is True
    grant = by["entitlement"][0]
    assert grant["intended_expiry"] < next(s for s in by["session"] if s["actor_type"] == "EMPLOYEE")["started_at"]
    payouts = [t for t in by["txn"] if t["from_account"] == spec.account_id]
    assert [t["to_account"] for t in payouts] == ["A-7731", "A-7768"]
    assert all(t["amount_paise"] == spec.amount * 100 for t in payouts)
    assert any(t["from_account"] in ("A-7731", "A-7768") and t["to_account"] == "A-6604" for t in by["txn"]), "the ring reacts"
    mobile = next(r for r in rows if r["effect"] and r["effect"]["column"] == "registered_mobile_tok")["effect"]
    assert mobile["new"] != mobile["old"] and mobile["new"].startswith("pho_")
    assert not re.search(RAW_PHONE, str(rows)), "composed rows are tokenised like every other row"
    ids = [r["row"]["id"] for r in rows]
    assert len(ids) == len(set(ids))
    for table, items in by.items():
        clash = conn.execute(text(f"SELECT count(*) FROM {table} WHERE id = ANY(:i)"), {"i": [x["id"] for x in items]}).scalar()
        assert clash == 0, f"{table} IDs must be new"
    assert compose.build(conn, spec) == rows, "the same input gives the same rows"


def test_compose_refuses_what_the_bank_could_not_record(db):
    from app.loom import compose

    conn = db.connection()
    with pytest.raises(compose.ComposeError, match="holds"):
        compose.build(conn, _spec(db, amount=25_00_000, payees=["A-7731", "A-7768", "OUTSIDE"]))
    with pytest.raises(compose.ComposeError, match="operations officer"):
        compose.build(conn, _spec(db, employee_id="EMP-0112"))
    with pytest.raises(compose.ComposeError, match="already part of a case"):
        compose.build(conn, _spec(db, account_id="A-5520"))


def test_composed_input_is_played_and_undone_on_its_own(db):
    from app.loom import compose, feed

    conn = db.connection()
    feed.reset(conn)
    evening_before = feed.status(db)
    spec = _spec(db)
    balance = conn.execute(text("SELECT balance_paise FROM account WHERE id = :a"), {"a": spec.account_id}).scalar()
    staged = compose.stage(conn, compose.build(conn, spec))
    assert feed.status(db)["yours"] == {"total": staged, "ingested": 0}
    for item in feed.pending(db, "yours"):
        feed.ingest(conn, item)
    after = conn.execute(text("SELECT balance_paise FROM account WHERE id = :a"), {"a": spec.account_id}).scalar()
    assert balance - after == 2 * spec.amount * 100
    assert feed.status(db)["pending"] == evening_before["pending"], "tonight's feed is untouched"

    assert feed.reset(conn, "yours") == staged
    assert conn.execute(text("SELECT balance_paise FROM account WHERE id = :a"), {"a": spec.account_id}).scalar() == balance
    assert feed.status(db)["yours"] == {"total": 0, "ingested": 0}, "composed rows are gone, not just un-ingested"


def test_compose_dry_run_describes_without_writing(client, as_user, db):
    from app.loom import feed

    feed.reset(db.connection())
    s = _spec(db)
    body = {"employee_id": s.employee_id, "account_id": s.account_id, "amount": s.amount}
    r = client.post(f"{API}/live/compose?dry_run=true", json=body, headers=as_user("ananya"))
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["money_out"] == 2 * s.amount and "VPN gateway" in out["systems"]
    assert {"t", "system", "summary", "ref"} <= set(out["rows"][0])
    assert feed.status(db)["yours"]["total"] == 0
    bad = client.post(f"{API}/live/compose?dry_run=true", json={**body, "account_id": "A-5520"}, headers=as_user("ananya"))
    assert bad.status_code == 422 and "already part of a case" in bad.json()["detail"]
