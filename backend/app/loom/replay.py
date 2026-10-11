"""Replay the same event history in different arrival orders (FIN-04 Addition 1).

A *plan* fixes the order and the arrival time in which tonight's source rows reach SUTRA. Every
delivery goes through the production ingest (`app.loom.feed.deliver`), and detection runs at the
plan's checkpoints exactly as the scheduled job would, writing case revisions as cases change. The
harness may schedule arrivals by *source system* (an IMPS connector that lags) but never by the
simulator's ground truth, and detection only ever sees rows that have arrived.

    python -m app.cli replay            (make replay)

Plans
  in-order    each row arrives when its source system committed it — the reference
  late-link   the IMPS switch connector lags: its rows (the payouts among them) arrive 35 minutes after
              the rest of the evening, and detection runs before and after they land
  duplicates  at-least-once delivery: about 30% of rows are delivered again later (fixed seed), every
              money row is re-sent once, and one transfer is re-sent with a tampered amount
  shuffled    a random permutation (fixed seed)
  reverse     newest first

After every plan the converged state is captured — each alert's case snapshot (by natural key, without
display IDs), the money and master data the feed moved, signal and evidence totals, and M7's case
scores — and the report checks that every plan converged to the same state as in-order delivery.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, text

from app.loom import feed

PLANS = ("in-order", "late-link", "duplicates", "shuffled", "reverse")
LAGGING_SYSTEM = "IMPS switch"
LAG = timedelta(minutes=35)


@dataclass(frozen=True)
class Delivery:
    item: feed.Item
    arrived_at: datetime
    copy: int = 0  # 0 = first delivery; 1.. = a re-delivery
    tampered: bool = False


@dataclass
class Plan:
    name: str
    description: str
    deliveries: list[Delivery]
    checkpoints: list[int]  # run detection after this many deliveries
    meta: dict = field(default_factory=dict)


def _commit_time(item: feed.Item) -> datetime:
    """When the source system committed the row — when a CDC connector would deliver it."""
    raw = item.row.get("ingested_at")
    try:
        t = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        t = None
    return max(t, item.t) if t and t.tzinfo else item.t


def _monotonic(seq: list[tuple[feed.Item, int, bool]], nominal: list[datetime]) -> list[Delivery]:
    out, prev = [], None
    for (item, copy, tampered), t in zip(seq, nominal, strict=True):
        arrived = t if prev is None or t > prev else prev + timedelta(milliseconds=500)
        out.append(Delivery(item, arrived, copy, tampered))
        prev = arrived
    return out


def _even_checkpoints(n: int, k: int) -> list[int]:
    k = max(1, k)
    return sorted({max(1, round(n * (i + 1) / k)) for i in range(k)})


def build(items: list[feed.Item], name: str, seed: int = 7, checkpoints: int = 2) -> Plan:
    """The deliveries for one plan over `items` (tonight's staged rows, any order)."""
    if name not in PLANS:
        raise ValueError(f"unknown plan {name!r} — choose from {', '.join(PLANS)}")
    items = sorted(items, key=lambda i: (i.t, i.seq))
    commits = sorted(_commit_time(i) for i in items)
    rng = random.Random(seed)
    if name == "in-order":
        seq = [(i, 0, False) for i in items]
        plan = Plan(name, "Each row arrives when its source system committed it.",
                    _monotonic(seq, [_commit_time(i) for i in items]), _even_checkpoints(len(seq), checkpoints))
    elif name == "late-link":
        main = [i for i in items if i.system != LAGGING_SYSTEM]
        late = [i for i in items if i.system == LAGGING_SYSTEM]
        tail = max(_commit_time(i) for i in items) + LAG
        nominal = [_commit_time(i) for i in main] + [tail + timedelta(seconds=15 * k) for k in range(len(late))]
        plan = Plan(name, f"The {LAGGING_SYSTEM} connector lags: its {len(late)} rows arrive {int(LAG.total_seconds() // 60)} "
                          "minutes after the rest of the evening.",
                    _monotonic([(i, 0, False) for i in main + late], nominal), [len(main), len(main) + len(late)],
                    {"delayed_system": LAGGING_SYSTEM, "delayed": [i.ref for i in late]})
    elif name == "duplicates":
        seq: list[tuple[feed.Item, int, bool]] = [(i, 0, False) for i in items]
        extras: list[tuple[int, tuple[feed.Item, int, bool]]] = []
        for pos, i in enumerate(items):
            if i.source_table == "txn" or rng.random() < 0.30:
                extras.append((rng.randint(pos + 1, len(items)), (i, 1, False)))
        money = [i for i in items if i.source_table == "txn" and i.system == LAGGING_SYSTEM]
        if money:
            victim = money[0]
            forged = replace(victim, row={**victim.row, "amount_paise": int(victim.row["amount_paise"]) + 10_00_000})
            extras.append((len(items), (forged, 1, True)))
        for pos, d in sorted(extras, key=lambda x: x[0], reverse=True):
            seq.insert(pos, d)
        nominal, prev = [], commits[0]
        for item, copy, _ in seq:
            prev = _commit_time(item) if copy == 0 else prev + timedelta(seconds=2)
            nominal.append(prev)
        plan = Plan(name, "At-least-once delivery: rows re-sent later, every transfer twice, one tampered re-send.",
                    _monotonic(seq, nominal), _even_checkpoints(len(seq), checkpoints),
                    {"redelivered": sum(1 for _, c, t in seq if c and not t), "tampered": sum(1 for *_, t in seq if t)})
    elif name == "shuffled":
        order = list(items)
        rng.shuffle(order)
        plan = Plan(name, f"A random arrival order (seed {seed}).",
                    _monotonic([(i, 0, False) for i in order], commits), _even_checkpoints(len(order), checkpoints))
    else:
        order = list(reversed(items))
        plan = Plan(name, "Newest first.", _monotonic([(i, 0, False) for i in order], commits),
                    _even_checkpoints(len(order), checkpoints))
    plan.meta.update({"seed": seed, "deliveries": len(plan.deliveries), "rows": len(items)})
    return plan


# ── converged state ─────────────────────────────────────────────────────────


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def converged_state(conn: Connection) -> dict:
    """What a plan settled to: case snapshots by natural key, and the totals duplicates could inflate."""
    from app.brief import revisions

    snaps = revisions.snapshots(conn)
    refs = [r[0] for r in conn.execute(text("SELECT ref FROM feed_event WHERE ingested_at IS NOT NULL "
                                            "AND strand NOT IN ('yours', 'bank')"))]
    txn = conn.execute(text("SELECT count(*), coalesce(sum(amount_paise), 0) FROM txn WHERE id = ANY(:r)"),
                       {"r": refs}).one()
    touched = conn.execute(text("""
        SELECT id, balance_paise, registered_mobile_tok, daily_limit_paise, status FROM account
        WHERE id IN (SELECT row->>'from_account' FROM feed_event WHERE source_table = 'txn'
                     UNION SELECT row->>'to_account' FROM feed_event WHERE source_table = 'txn'
                     UNION SELECT effect->>'account_id' FROM feed_event WHERE effect IS NOT NULL)
        ORDER BY id""")).all()
    rows_by_table = dict(conn.execute(text("SELECT source_table, count(*) FROM feed_event WHERE ingested_at IS NOT NULL "
                                           "AND strand NOT IN ('yours', 'bank') GROUP BY 1")).all())
    m7 = dict(conn.execute(text("SELECT entity_ref, p FROM model_prediction WHERE model = 'M7'")).all())
    totals = {
        "rows_ingested": len(refs), "rows_by_table": rows_by_table,
        "txn_rows": txn[0], "txn_total_rupees": txn[1] / 100,
        "accounts_touched": len(touched),
        "balances_sha256": _sha([[a.id, a.balance_paise] for a in touched]),
        "master_data_sha256": _sha([[a.id, a.registered_mobile_tok, a.daily_limit_paise, a.status] for a in touched]),
        "signals": conn.execute(text("SELECT count(*) FROM signal")).scalar(),
        "alerts": len(snaps),
        "by_priority": dict(Counter(s["priority"] for s in snaps.values())),
        "evidence_total": sum(s["evidence_count"] for s in snaps.values()),
        "m7_cases": len(m7), "m7_scores_sha256": _sha(sorted(m7.items())),
    }
    return {"totals": totals, "cases": {k: revisions.content_sha(s) for k, s in sorted(snaps.items())},
            "priorities": {k: s["priority"] for k, s in sorted(snaps.items())}}


def compare(reference: dict, other: dict) -> dict:
    """Field-by-field comparison of two converged states."""
    diffs = [k for k in reference["totals"] if reference["totals"][k] != other["totals"].get(k)]
    keys = set(reference["cases"]) | set(other["cases"])
    case_diffs = sorted(k for k in keys if reference["cases"].get(k) != other["cases"].get(k))
    return {"identical": not diffs and not case_diffs, "totals_differ": diffs, "cases_differ": case_diffs,
            "cases_compared": len(keys)}


# ── running a plan against the database ─────────────────────────────────────


Listener = Callable[[str, dict], None]


def _detect(trigger: dict) -> dict:
    from app.core import audit
    from app.core.db import engine, session_scope
    from app.loom.frames import load_frames
    from app.pipeline import compute, persist, record_run

    with engine.connect() as c:
        before = {r[0] for r in c.execute(text("SELECT id FROM alert"))}
    t0 = time.perf_counter()
    res = compute(load_frames(), log=False)
    stats = persist(res)
    report = record_run(res, stats, trigger)
    with engine.connect() as c:
        after = {r[0] for r in c.execute(text("SELECT id FROM alert"))}
    new = sorted(after - before)
    with session_scope() as db:  # so a later reset knows which alerts the feed created (app.api.live._born)
        audit.append(db, "replay", "live.run", target=trigger.get("plan"),
                     payload={"scope": "evening", "ingested": len(trigger.get("refs", [])), "new_alerts": new,
                              "updated_alerts": [], "replay": trigger.get("plan"), "checkpoint": trigger.get("checkpoint")})
    return {"run_id": report["run_id"], "revisions": report["revisions"], "new_alerts": new,
            "seconds": round(time.perf_counter() - t0, 1),
            "scenarios": {"passed": report["summary"]["passed"], "total": report["summary"]["total"]}}


def reset_evening(listener: Listener | None = None) -> None:
    from app.api import live

    run = live.Run(id="REPLAY-RESET", kind="reset", actor="replay", started_at=datetime.now(UTC).isoformat(),
                   listener=listener)
    live.reset_feed(run, "all")
    if not any(e == "done" for e, _ in run.log):
        raise RuntimeError("feed reset failed — see the API log")


def run_plan(plan: Plan, listener: Listener | None = None) -> dict:
    """Deliver a plan through production ingest, detect at its checkpoints, return its log."""
    from app.core.db import engine

    say = listener or (lambda e, d: None)
    run_id = f"RP-{plan.name}-{datetime.now(UTC):%H%M%S}"[:32]
    checkpoints, pending, outcomes = [], {"refs": [], "late": {}, "duplicates": 0, "conflicts": 0}, Counter()
    marks = set(plan.checkpoints)
    for n, d in enumerate(plan.deliveries, start=1):
        with engine.begin() as conn:
            rc = feed.deliver(conn, d.item, d.arrived_at, run_id)
        say("delivery", {**d.item.public(), "n": n, "copy": d.copy, "receipt": rc.public()})
        outcomes[rc.outcome] += 1
        outcomes["LATE"] += rc.late
        if rc.outcome == "NEW":
            pending["refs"].append(rc.ref)
            if rc.late:
                pending["late"][rc.ref] = rc.late_by_s
        pending["duplicates"] += rc.outcome == "DUPLICATE"
        pending["conflicts"] += rc.outcome == "CONFLICT"
        if n in marks:
            trigger = {"kind": "replay", "plan": plan.name, "checkpoint": len(checkpoints) + 1, **pending}
            say("checkpoint", {"plan": plan.name, "after": n, "new_rows": len(pending["refs"]),
                               "late": len(pending["late"]), "duplicates": pending["duplicates"],
                               "conflicts": pending["conflicts"]})
            out = _detect(trigger)
            with engine.connect() as c:
                revs = c.execute(text("SELECT alert_id, rev, status, summary, changes FROM case_revision "
                                      "WHERE run_id = :r ORDER BY alert_id"), {"r": out["run_id"]}).all()
            checkpoints.append({"after_deliveries": n, "at": d.arrived_at.isoformat(), **{k: v for k, v in trigger.items()
                                if k in ("duplicates", "conflicts")}, "new_rows": len(pending["refs"]),
                                "late_rows": pending["late"], **out,
                                "revisions": [{"alert_id": r.alert_id, "rev": r.rev, "status": r.status,
                                               "summary": r.summary, "changes": r.changes} for r in revs]})
            say("detected", {"plan": plan.name, "checkpoint": len(checkpoints), **{k: out[k] for k in
                                                                                  ("revisions", "new_alerts", "seconds")}})
            pending = {"refs": [], "late": {}, "duplicates": 0, "conflicts": 0}
    with engine.connect() as c:
        state = converged_state(c)
        receipts = c.execute(text("SELECT ref, source_table, event_t, arrived_at, outcome, late, late_by_s, effect, "
                                  "content_sha256, detail FROM feed_receipt WHERE run_id = :r ORDER BY id"),
                             {"r": run_id}).all()
    return {"plan": plan.name, "description": plan.description, "meta": plan.meta, "run_id": run_id,
            "outcomes": dict(outcomes), "checkpoints": checkpoints, "state": state,
            "receipts": [dict(r._mapping) for r in receipts]}


def replay(plans: list[str], seed: int = 7, checkpoints: int = 2, out_dir: Path | None = None,
           keep: bool = False, listener: Listener | None = None) -> dict:
    """Run each plan from the same starting point and check they all converge to in-order's state."""
    from app.core.db import SessionLocal

    say = listener or (lambda e, d: None)
    names = list(dict.fromkeys(["in-order", *plans]))
    results = {}
    for name in names:
        say("plan", {"plan": name})
        reset_evening()
        with SessionLocal() as db:
            items = feed.pending(db, "evening")
        results[name] = run_plan(build(items, name, seed, checkpoints), listener)
    ref = results["in-order"]["state"]
    verdict = {name: compare(ref, r["state"]) for name, r in results.items() if name != "in-order"}
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "seed": seed, "plans": names,
        "invariant": all(v["identical"] for v in verdict.values()),
        "comparison_to_in_order": verdict,
        "note": "Synthetic Kestrel-Sim evening (22 Sep). Arrival plans schedule by source system, never by ground truth.",
        "results": {n: {k: v for k, v in r.items() if k != "receipts"} for n, r in results.items()},
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "replay_report.json").write_text(json.dumps(report, indent=2, default=str))
        for name, r in results.items():
            with (out_dir / f"receipts_{name}.csv").open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["ref", "source_table", "event_t", "arrived_at", "outcome", "late", "late_by_s", "effect",
                            "content_sha256", "reason"])
                for x in r["receipts"]:
                    w.writerow([x["ref"], x["source_table"], x["event_t"].isoformat(), x["arrived_at"].isoformat(),
                                x["outcome"], x["late"], x["late_by_s"], x["effect"], x["content_sha256"],
                                (x["detail"] or {}).get("reason", "")])
    if not keep:
        reset_evening()
    return report
