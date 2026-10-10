"""FIN-04 Addition 1 — incremental ingest and case revisions.

Delivery is at-least-once and in any order: duplicates must not inflate money, rows or evidence; a
tampered re-delivery must be refused; master data must settle by event time; and every arrival order
must leave Loom in the same state. Case revisions are append-only and say why a case changed.
Database tests run inside the rolled-back test transaction (each plan in its own savepoint).
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.loom import feed, replay


@pytest.fixture()
def evening(db):
    items = feed.pending(db, "evening")
    if len(items) < 200:
        pytest.skip("needs tonight's feed staged and not yet played (`make seed` or a live reset)")
    return items


def _balance(conn, account: str) -> int:
    return conn.execute(text("SELECT balance_paise FROM account WHERE id = :a"), {"a": account}).scalar()


def _txn(items, system: str = "IMPS switch") -> feed.Item:
    return next(i for i in items if i.source_table == "txn" and i.system == system
                and not i.row["to_account"].startswith("X-"))


# ── delivery outcomes ──────────────────────────────────────────────────────


def test_duplicate_delivery_changes_nothing(db, evening):
    conn = db.connection()
    item = _txn(evening)
    src, dst, amt = item.row["from_account"], item.row["to_account"], int(item.row["amount_paise"])
    b_src, b_dst = _balance(conn, src), _balance(conn, dst)

    first = feed.deliver(conn, item)
    again = feed.deliver(conn, item)
    third = feed.deliver(conn, item)

    assert (first.outcome, again.outcome, third.outcome) == ("NEW", "DUPLICATE", "DUPLICATE")
    assert _balance(conn, src) == b_src - amt and _balance(conn, dst) == b_dst + amt, "money moved exactly once"
    assert conn.execute(text("SELECT count(*) FROM txn WHERE id = :i"), {"i": item.ref}).scalar() == 1
    receipts = conn.execute(text("SELECT outcome FROM feed_receipt WHERE ref = :r ORDER BY id"), {"r": item.ref}).scalars().all()
    assert receipts[-3:] == ["NEW", "DUPLICATE", "DUPLICATE"], "every arrival is on the receipt log"


def test_tampered_redelivery_is_refused(db, evening):
    conn = db.connection()
    item = _txn(evening)
    feed.deliver(conn, item)
    dst_before = _balance(conn, item.row["to_account"])
    forged = replace(item, row={**item.row, "amount_paise": int(item.row["amount_paise"]) + 10_00_000})

    rc = feed.deliver(conn, forged)

    assert rc.outcome == "CONFLICT" and "different content" in rc.reason
    assert _balance(conn, item.row["to_account"]) == dst_before
    stored = conn.execute(text("SELECT amount_paise FROM txn WHERE id = :i"), {"i": item.ref}).scalar()
    assert stored == int(item.row["amount_paise"]), "the row of record is untouched"


def test_a_conflict_arriving_first_is_refused_and_the_real_row_still_lands(db, evening):
    conn = db.connection()
    item = _txn(evening)
    forged = replace(item, row={**item.row, "amount_paise": 1})
    assert feed.deliver(conn, forged).outcome == "CONFLICT"
    assert conn.execute(text("SELECT count(*) FROM txn WHERE id = :i"), {"i": item.ref}).scalar() == 0
    assert feed.deliver(conn, item).outcome == "NEW"


def test_rows_behind_the_watermark_are_marked_late(db, evening):
    conn = db.connection()
    early, later = evening[10], evening[60]
    assert early.t < later.t
    assert not feed.deliver(conn, later).late
    rc = feed.deliver(conn, early)
    assert rc.outcome == "NEW" and rc.late and rc.late_by_s == int((later.t - early.t).total_seconds())
    row = conn.execute(text("SELECT late_by_s, arrived_at FROM feed_event WHERE seq = :s"), {"s": early.seq}).one()
    assert row.late_by_s == rc.late_by_s and row.arrived_at is not None


# ── master data settles by event time ──────────────────────────────────────


def _stage_mobile_changes(conn, template: feed.Item) -> tuple[feed.Item, feed.Item, str, str, str]:
    """Two changes to one account's mobile number, 10 minutes apart (staged as composed rows)."""
    acct = template.effect["account_id"]
    a = conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"), {"a": acct}).scalar()
    b, c = "tok:test-b", "tok:test-c"
    seq0 = conn.execute(text("SELECT max(seq) FROM feed_event")).scalar()
    out = []
    for k, (old, new) in enumerate(((a, b), (b, c))):
        t = template.t + timedelta(minutes=10 * k)
        row = {**template.row, "id": f"SC-T{k}", "occurred_at": t.isoformat()}
        effect = {**template.effect, "old": old, "new": new}
        seq = seq0 + 1 + k
        conn.execute(text("INSERT INTO feed_event (seq, t, source_table, ref, system, summary, row, effect, strand) "
                          "VALUES (:s, :t, 'state_change', :r, 'Core banking', 'test', CAST(:row AS jsonb), "
                          "CAST(:e AS jsonb), 'yours')"),
                     {"s": seq, "t": t, "r": row["id"], "row": json.dumps(row), "e": json.dumps(effect)})
        out.append(feed.Item(seq, t, "state_change", row["id"], "Core banking", "test", row, effect))
    return out[0], out[1], a, b, c


def test_master_data_change_is_last_writer_wins_by_event_time(db, evening):
    conn = db.connection()
    template = next(i for i in evening if i.effect and i.effect.get("column") == "registered_mobile_tok")
    first, second, a, _b, c = _stage_mobile_changes(conn, template)
    acct = template.effect["account_id"]

    later_rc = feed.deliver(conn, second)  # the later change arrives first …
    earlier_rc = feed.deliver(conn, first)  # … and the earlier one after it

    assert later_rc.effect == "APPLIED" and earlier_rc.effect == "SUPERSEDED" and earlier_rc.late
    assert conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"), {"a": acct}).scalar() == c
    feed.reset(conn, "yours")
    assert conn.execute(text("SELECT registered_mobile_tok FROM account WHERE id = :a"), {"a": acct}).scalar() == a, \
        "reset restores the value before the earliest change, whatever the arrival order"


# ── arrival order does not change Loom ─────────────────────────────────────


def _ingest_state(conn) -> dict:
    t = replay.converged_state(conn)["totals"]
    return {k: t[k] for k in ("rows_ingested", "rows_by_table", "txn_rows", "txn_total_rupees", "accounts_touched",
                              "balances_sha256", "master_data_sha256")}


@pytest.mark.parametrize("plan", ["late-link", "duplicates", "shuffled", "reverse"])
def test_every_arrival_order_leaves_loom_in_the_same_state(db, evening, plan):
    conn = db.connection()
    states = {}
    for name in ("in-order", plan):
        sp = conn.begin_nested()
        p = replay.build(evening, name, seed=11)
        outcomes = [feed.deliver(conn, d.item, d.arrived_at, f"T-{name}").outcome for d in p.deliveries]
        states[name] = (_ingest_state(conn), outcomes.count("NEW"))
        sp.rollback()
    assert states[plan] == states["in-order"]
    assert states["in-order"][1] == len(evening), "every row lands exactly once"


def test_reset_after_an_out_of_order_replay_restores_the_bank(db, evening):
    conn = db.connection()
    before = _ingest_state(conn)
    for d in replay.build(evening, "reverse").deliveries:
        feed.deliver(conn, d.item, d.arrived_at)
    assert _ingest_state(conn) != before
    feed.reset(conn, "evening")
    assert _ingest_state(conn) == before


# ── plans (no database) ────────────────────────────────────────────────────


def _fake_items(n: int = 40) -> list[feed.Item]:
    t0 = datetime(2026, 9, 22, 14, 30, tzinfo=UTC)
    systems = ["UPI switch", "IMPS switch", "CBS application audit", "Digital banking"]
    out = []
    for i in range(n):
        sys = systems[i % 4]
        table = "txn" if "switch" in sys else "access_event"
        row = {"id": f"R-{i:03d}", "amount_paise": 100_00 * (i + 1)} if table == "txn" else {"id": f"R-{i:03d}"}
        out.append(feed.Item(i + 1, t0 + timedelta(minutes=i), table, row["id"], sys, "x", row, None))
    random.Random(1).shuffle(out)
    return out


def test_plans_deliver_every_row_and_arrive_in_monotonic_time():
    items = _fake_items()
    for name in replay.PLANS:
        p = replay.build(items, name)
        firsts = [d.item.ref for d in p.deliveries if d.copy == 0]
        assert sorted(firsts) == sorted(i.ref for i in items), name
        arr = [d.arrived_at for d in p.deliveries]
        assert arr == sorted(arr), f"{name}: arrival clock runs forward"
        assert p.checkpoints[-1] == len(p.deliveries)


def test_late_link_delays_only_the_lagging_connector():
    p = replay.build(_fake_items(), "late-link")
    cut = p.checkpoints[0]
    assert all(d.item.system != "IMPS switch" for d in p.deliveries[:cut])
    assert all(d.item.system == "IMPS switch" for d in p.deliveries[cut:])
    assert p.deliveries[cut].arrived_at - p.deliveries[cut - 1].arrived_at >= timedelta(minutes=30)


def test_duplicates_plan_resends_every_transfer_and_one_tampered_copy():
    items = _fake_items()
    p = replay.build(items, "duplicates", seed=3)
    copies = [d for d in p.deliveries if d.copy]
    assert {d.item.ref for d in copies if not d.tampered} >= {i.ref for i in items if i.source_table == "txn"}
    assert sum(d.tampered for d in p.deliveries) == 1
    for d in copies:  # a copy always arrives after the original
        first = next(k for k, x in enumerate(p.deliveries) if x.item.ref == d.item.ref and x.copy == 0)
        assert p.deliveries.index(d) > first


# ── case revisions ─────────────────────────────────────────────────────────


def _snap(**kw) -> dict:
    base = {"alert_id": "AL-1", "typology": "INSIDER_ATO", "claim": "c", "priority": "P2", "lattice_rule": "r2",
            "state": "OPEN", "recoverable": True, "dims": {"network": "ELEVATED"}, "amount_at_risk": 100.0,
            "classifier_p": 0.5, "links": [["E3", "SC-1"]], "evidence": [["TXN", "TX-1", "ab"]], "evidence_count": 1,
            "case": {"key": "CK-1", "chains": 1, "accounts": 2, "linked_cases": [], "suspicion_p": 0.4,
                     "above_threshold": False}}
    return {**base, **kw}


def test_revision_diff_names_the_change_and_the_late_row_behind_it():
    from app.brief.revisions import content_sha, diff

    before = _snap()
    after = _snap(priority="P1", lattice_rule="≥3 dimensions High", dims={"network": "HIGH"},
                  links=[["E3", "SC-1"], ["E5", "TX-9"]], evidence=[["TXN", "TX-1", "ab"], ["TXN", "TX-9", "cd"]],
                  evidence_count=2, case={**before["case"], "key": "CK-0", "suspicion_p": 0.91})
    changes = {c["field"]: c for c in diff(before, after, {"late": {"TX-9": 2100}})}
    assert changes["priority"]["before"] == "P2" and changes["priority"]["after"] == "P1"
    assert "≥3 dimensions High" in changes["priority"]["why"]
    assert "TX-9 (arrived late, 35 min behind the feed)" in changes["evidence"]["why"]
    assert "case.key" in changes and "not a finding" in changes["case.suspicion_p"]["why"]
    assert content_sha(before) == content_sha({**before, "alert_id": "AL-0999"}), "display IDs never count"


@pytest.mark.parametrize("change", [
    {"evidence": [["M6_MULE", "TX-1", "zz"]]},  # a computed record recalculated
    {"lattice_rule": "restated"},
    {"case": {**_snap()["case"], "linked_cases": ["CK-9"]}},
    {"case": {**_snap()["case"], "chains": 2, "accounts": 3}},
    {"case": {**_snap()["case"], "above_threshold": True}},
    {"recoverable": False},
    {"typology": "MULE_FACTORY"},
])
def test_no_revision_is_left_unexplained(change):
    from app.brief.revisions import _summary, diff

    changes = diff(_snap(), _snap(**change), {})
    assert changes and all(c["why"] for c in changes)
    assert _summary("REVISED", changes, _snap(**change)) != "Revised: "


def test_revisions_are_written_once_per_change_and_never_edited(db):
    from app.brief import revisions

    conn = db.connection()
    first = revisions.record(conn, "T-REV-1", {"kind": "test"})
    again = revisions.record(conn, "T-REV-2", {"kind": "test"})
    n_alerts = conn.execute(text("SELECT count(*) FROM alert")).scalar()
    assert again["opened"] == again["revised"] == again["withdrawn"] == 0
    assert again["unchanged"] == n_alerts and first["opened"] + first["revised"] + first["unchanged"] == n_alerts
    sp = conn.begin_nested()
    with pytest.raises(Exception, match="append-only"):
        conn.execute(text("UPDATE case_revision SET summary = 'edited' WHERE run_id = 'T-REV-1'"))
        conn.execute(text("UPDATE case_revision SET summary = 'edited'"))
    sp.rollback()


def test_revision_history_endpoint(client, as_user, db):
    from app.brief import revisions

    revisions.record(db.connection(), "T-REV-API", {"kind": "test"})
    alert_id = db.execute(text("SELECT id FROM alert ORDER BY id LIMIT 1")).scalar()
    r = client.get(f"/api/v1/alerts/{alert_id}/revisions", headers=as_user("ananya"))
    assert r.status_code == 200
    body = r.json()
    assert body["revisions"] and body["revisions"][-1]["snapshot_sha256"]
    assert client.get("/api/v1/alerts/AL-NOPE/revisions", headers=as_user("ananya")).status_code == 404
