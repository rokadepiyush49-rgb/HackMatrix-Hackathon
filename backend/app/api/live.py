"""Live Ops — the end-to-end demo: raw source rows in, a new alert out, every stage real.

Demo mode only. A run streams source rows into Loom the way a change-data-capture connector would,
one row per transaction, then runs the same detection pipeline as the scheduled job and reports what
changed: new and updated alerts, the chain links that cite the run's rows, the signals they raised,
and Alibi's verdict on every staff access among them. The rows come from one of two places:

  • the **evening** the simulator held back (kestrel_sim.live) — press Play;
  • **your input** — rows composed from a person's choices at the console (app.loom.compose).

Progress is kept in memory per run and served as Server-Sent Events with ids, so a browser that
reconnects resumes where it left off. One run at a time. A reset undoes rows and re-detects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.common import TYPOLOGY_LABEL
from app.core import audit
from app.core.config import get_settings
from app.core.db import SessionLocal, engine, get_db, session_scope
from app.core.security import CurrentUser
from app.loom import compose, feed
from app.loom.frames import load_frames
from app.loom.models import AuditLog, FeedEvent
from app.needle.registry import DETECTORS
from app.pipeline import compute, persist, record_run

router = APIRouter(prefix="/live", tags=["live"])
log = logging.getLogger("sutra.live")

# The stages a run reports, in order. Keys match pipeline.compute's progress callbacks.
STAGES = [
    {"key": "ingest", "label": "Ingest", "what": "Source rows land in Loom, one transaction each"},
    {"key": "loom", "label": "Loom", "what": "Read the 90-day evidence window"},
    {"key": "alibi", "label": "Alibi", "what": "Look for a legitimate reason behind every staff access"},
    {"key": "er", "label": "Entity resolution", "what": "Link staff to customers by address, phone and surname"},
    {"key": "baselines", "label": "Baselines", "what": "Access rhythm (M1) and navigation (M2) per role"},
    {"key": "signals", "label": "Signals", "what": "Rules, models and graph detectors"},
    {"key": "needle", "label": "Needle", "what": "Assemble privilege-to-payment chains"},
    {"key": "brief", "label": "Brief", "what": "Grade evidence, score with M5/M6, set priority"},
    {"key": "persist", "label": "Persist", "what": "One transaction; alert IDs, triage and cases kept"},
    {"key": "lab", "label": "Scenario checks", "what": "Grade every scenario against ground truth"},
]
MAX_GAP_S = 1.5  # never pause longer than this between two events, whatever the speed
PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "WATCH": 3, "EXPLAINED": 4}
Scope = Literal["evening", "yours", "bank"]


@dataclass
class Run:
    id: str
    kind: str  # "feed" | "reset"
    actor: str
    started_at: str
    scope: str = "evening"  # evening | yours | all
    log: list[tuple[str, dict]] = field(default_factory=list)
    finished: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    listener: Callable[[str, dict], None] | None = None  # the CLI prints as the run goes

    def emit(self, event: str, data: dict) -> None:
        self.log.append((event, data))  # list.append is atomic; readers only ever look at a prefix
        if self.listener:
            self.listener(event, data)

    def summary(self) -> dict:
        last = next((d for e, d in reversed(self.log) if e in ("done", "failed", "cancelled")), None)
        return {"id": self.id, "kind": self.kind, "scope": self.scope, "actor": self.actor,
                "started_at": self.started_at, "finished": self.finished, "events": len(self.log), "result": last}


_runs: dict[str, Run] = {}
_guard = threading.Lock()
_active: Run | None = None


def _enabled() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _busy() -> bool:
    return bool(_active and not _active.finished)


def _start(kind: str, scope: str, actor: str, target) -> Run:
    global _active
    with _guard:
        if _busy():
            raise HTTPException(status.HTTP_409_CONFLICT, f"A {_active.kind} run is already in progress ({_active.id}).")
        run = Run(id=f"LIVE-{uuid.uuid4().hex[:8].upper()}", kind=kind, scope=scope, actor=actor,
                  started_at=datetime.now(UTC).isoformat())
        _runs[run.id] = run
        for old in list(_runs)[:-6]:  # keep the last few for reconnects
            _runs.pop(old, None)
        _active = run
    threading.Thread(target=target, args=(run,), name=f"sutra-{run.id}", daemon=True).start()
    return run


def _release(run: Run) -> None:
    global _active
    run.finished = True
    with _guard:
        if _active is run:
            _active = None


# ── the work ────────────────────────────────────────────────────────────────


def _stage(run: Run, t0: float):
    def emit(key: str, state: str, detail: str | None = None) -> None:
        run.emit("stage", {"key": key, "status": state, "detail": detail, "elapsed": round(time.perf_counter() - t0, 1)})
    return emit


def _findings(run: Run, res: dict, before: set[str], refs: dict[str, str]) -> dict:
    """Every alert that is new or now cites this run's rows, the signals those rows raised, and Alibi on them."""
    with engine.connect() as c:
        alerts = c.execute(text("""
            SELECT a.id, a.priority, a.typology, a.claim, a.lattice_rule, a.chain_id, ch.amount_at_risk_paise,
                   ch.employee_id, ch.account_id, ch.classifier_p
            FROM alert a JOIN chain ch ON ch.id = a.chain_id
            WHERE a.id <> ALL(CAST(:before AS text[]))
               OR a.chain_id IN (SELECT chain_id FROM chain_link WHERE event_id = ANY(CAST(:refs AS text[])))"""),
            {"before": list(before), "refs": list(refs)}).all()
        out = []
        for a in sorted(alerts, key=lambda a: (a.id in before, PRIORITY_ORDER.get(a.priority, 9), a.id)):
            links = c.execute(text("SELECT code, event_type, event_id, t AS at, title, detail, lane FROM chain_link "
                                   "WHERE chain_id = :c ORDER BY seq"), {"c": a.chain_id}).all()
            # every one of the run's rows this alert cites, with the first chain link that cites it
            cited = dict(c.execute(text("""
                SELECT DISTINCT ON (ref) ref, code FROM (
                    SELECT event_id AS ref, code, seq FROM chain_link WHERE chain_id = :c
                    UNION ALL
                    SELECT e.source_ref, l.code, l.seq FROM chain_link l
                    JOIN evidence e ON e.alert_id = :a AND e.code = ANY(l.evidence_codes) WHERE l.chain_id = :c) x
                WHERE ref = ANY(CAST(:refs AS text[])) ORDER BY ref, seq"""),
                {"c": a.chain_id, "a": a.id, "refs": list(refs)}).all())
            item = {"id": a.id, "new": a.id not in before, "priority": a.priority, "typology": a.typology,
                    "typology_label": TYPOLOGY_LABEL.get(a.typology, a.typology), "claim": a.claim,
                    "rule": a.lattice_rule, "chain_id": a.chain_id, "amount": (a.amount_at_risk_paise or 0) / 100,
                    "employee_id": a.employee_id, "account_id": a.account_id, "classifier_p": a.classifier_p,
                    "links": [{"code": lk.code, "type": lk.event_type, "event_id": lk.event_id, "t": lk.at.isoformat(),
                               "title": lk.title, "detail": lk.detail, "lane": lk.lane, "live": lk.event_id in refs}
                              for lk in links], "cited": cited}
            out.append(item)
            run.emit("alert", item)

    sig = [s for s in res["signals"] if refs.keys() & set(s["event_refs"])]
    for s in sorted(sig, key=lambda s: -s["strength"]):
        d = DETECTORS.get(s["detector"])
        run.emit("signal", {"detector": s["detector"], "name": d.name if d else s["detector"],
                            "family": s["family"], "strength": s["strength"], "summary": s["summary"]})

    ex = res["explanations"]
    accesses = ex[ex["access_event_id"].isin([r for r, t in refs.items() if t == "access_event"])]
    action = res["frames"].access_event.set_index("id")["action"]
    for r in accesses.sort_values("occurred_at").itertuples(index=False):
        run.emit("alibi", {"ref": r.access_event_id, "employee_id": r.employee_id, "verdict": r.verdict,
                           "action": str(action.get(r.access_event_id, "")), "t": r.occurred_at.isoformat(),
                           "checked": [{"template": x["template"], "ok": bool(x["ok"]), "ref": x.get("ref"),
                                        "note": x.get("note")} for x in r.checked]})
    return {"new": [a["id"] for a in out if a["new"]], "updated": [a["id"] for a in out if not a["new"]],
            "alerts": out, "signals": len(sig), "detectors": sorted({s["detector"] for s in sig}),
            "alibi": {"explained": int((accesses["verdict"] == "EXPLAINED").sum()),
                      "unexplained": int((accesses["verdict"] != "EXPLAINED").sum()),
                      "reasons": sorted({x["template"].lower() for r in accesses.itertuples(index=False)
                                         for x in r.checked if x["ok"]})}}


def _verdict(found: dict, refs: dict[str, str]) -> dict:
    """One sentence on what SUTRA made of the run's rows — the answer to "did it catch me?"."""
    fresh = [a for a in found["alerts"] if a["new"]]
    queued = [a for a in fresh if a["priority"] in ("P1", "P2", "P3")]
    money = any(t == "txn" for t in refs.values())
    alibi, n_sig = found["alibi"], found["signals"]
    if queued:
        a = queued[0]
        return {"outcome": "alert", "headline": f"{a['priority']} raised — {a['claim']}",
                "detail": f"{a['id']} · {a['rule']}"}
    if fresh:
        a = fresh[0]
        return {"outcome": "watch", "headline": f"Kept on the watch list ({a['priority'].lower()}) — {a['claim']}",
                "detail": f"{a['id']} · {a['rule']}"}
    if found["updated"]:
        return {"outcome": "updated", "headline": "No new alert — existing alerts now cite your rows",
                "detail": ", ".join(found["updated"])}
    if alibi["unexplained"] == 0 and alibi["explained"]:
        why = ", ".join(alibi["reasons"]) or "the paperwork"
        return {"outcome": "explained", "headline": "No alert — Alibi explained every staff access",
                "detail": f"Reasons on record: {why}. A chain never starts from an explained access."}
    if not money:
        return {"outcome": "signals", "headline": "No alert — no money moved",
                "detail": f"{n_sig} signal{'s' if n_sig != 1 else ''} recorded. Access without a payout is a signal, "
                          "not a chain: SUTRA alerts when privilege reaches money."}
    return {"outcome": "signals", "headline": "No alert — the signals did not join into a chain",
            "detail": f"{n_sig} signal{'s' if n_sig != 1 else ''} recorded on your rows; they stay on file for the next run."}


def _truth() -> dict:
    """Ground truth for the evening, revealed after the run: how many of each strand's rows queued alerts cite."""
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT fe.strand, count(*) AS events,
                   count(*) FILTER (WHERE fe.ref IN (
                       SELECT l.event_id FROM chain_link l JOIN alert a ON a.chain_id = l.chain_id
                       WHERE a.priority IN ('P1', 'P2', 'P3')
                       UNION SELECT e.source_ref FROM evidence e JOIN alert a ON a.id = e.alert_id
                       WHERE a.priority IN ('P1', 'P2', 'P3'))) AS cited
            FROM feed_event fe WHERE fe.ingested_at IS NOT NULL AND fe.strand NOT IN ('yours', 'bank')
            GROUP BY fe.strand""")).all()
    return {r.strand: {"events": r.events, "cited": r.cited} for r in rows}


def _detect(run: Run, t0: float, refs: dict[str, str] | None) -> dict:
    stage = _stage(run, t0)
    with engine.connect() as c:
        before = {r[0] for r in c.execute(text("SELECT id FROM alert"))}
    stage("loom", "running")
    f = load_frames()
    stage("loom", "done", f"{len(f.txn):,} transactions · {len(f.access_event):,} staff accesses")
    res = compute(f, log=False, progress=lambda key, msg: stage(key, "running" if msg is None else "done",
                                                                 msg and msg.split(": ", 1)[-1]))
    stage("persist", "running")
    stats = persist(res)
    stage("persist", "done", f"{stats['alerts']} alerts ({stats['new_alerts']} new) · "
                             f"{stats['evidence']:,} evidence items · one transaction")
    found = _findings(run, res, before, refs) if refs is not None else {}
    stage("lab", "running")
    report = record_run(res, stats)
    s = report["summary"]
    stage("lab", "done", f"{s['passed']}/{s['total']} scenario checks passed")
    return {**found, "scenarios": {"passed": s["passed"], "total": s["total"]}}


def play_feed(run: Run, speed: float, detect: bool = True, scope: str = "evening") -> None:
    t0 = time.perf_counter()
    stage = _stage(run, t0)
    try:
        with SessionLocal() as db:
            items = feed.pending(db, scope) if scope != "bank" else []
        if scope == "bank":  # the bank wrote its rows as they happened; this run only detects
            with engine.connect() as c:
                already = feed.ingested_refs(c, "bank")
        run.emit("start", {"run": run.id, "kind": "feed", "scope": scope, "started_at": run.started_at,
                           "total": len(items), "speed": speed, "stages": STAGES,
                           "feed_start": items[0].t.isoformat() if items else None,
                           "feed_end": items[-1].t.isoformat() if items else None})
        stage("ingest", "running")
        prev = items[0].t if items else None
        for n, ev in enumerate(items, start=1):
            if run.cancel.is_set():
                run.emit("cancelled", {"ingested": n - 1, "elapsed": round(time.perf_counter() - t0, 1)})
                return
            if speed > 0:
                time.sleep(min(max((ev.t - prev).total_seconds(), 0) / speed, MAX_GAP_S))
            prev = ev.t
            with engine.begin() as conn:
                feed.ingest(conn, ev)
            run.emit("event", {**ev.public(), "n": n})
        if scope == "bank":
            stage("ingest", "done", f"{len(already)} rows already in Loom — the bank recorded them as they happened")
            refs = already
        else:
            stage("ingest", "done", f"{len(items)} rows from {len({i.system for i in items})} source systems")
            refs = {i.ref: i.source_table for i in items}
        result = _detect(run, t0, refs) if detect else {}
        alerts = result.pop("alerts", [])
        with session_scope() as db:
            audit.append(db, run.actor, "live.run", target=run.id,
                         payload={"scope": scope, "ingested": len(items), "new_alerts": result.get("new", []),
                                  "updated_alerts": result.get("updated", [])})
        extra = {"truth": _truth()} if scope == "evening" else {
            "verdict": _verdict({**result, "alerts": alerts}, refs) if detect else None}
        run.emit("done", {**result, **extra, "ingested": len(refs), "elapsed": round(time.perf_counter() - t0, 1)})
    except Exception:
        log.exception("live.run.failed run=%s", run.id)
        run.emit("failed", {"message": "The live run failed — see the API log for details."})
    finally:
        _release(run)


def _born(db: Session, scope: str) -> set[str]:
    """Alerts created by live runs in `scope` since that scope was last reset (read from the audit chain)."""
    born: set[str] = set()
    for action, payload in db.execute(select(AuditLog.action, AuditLog.payload)
                                      .where(AuditLog.action.in_(["live.run", "live.reset"])).order_by(AuditLog.id)):
        s = payload.get("scope", "all" if action == "live.reset" else "evening")
        if action == "live.reset":
            if s in ("all", scope):
                born.clear()
        elif scope == "all" or s == scope:
            born.update(payload.get("new_alerts", []))
    return born


def reset_feed(run: Run, scope: str = "all") -> None:
    t0 = time.perf_counter()
    stage = _stage(run, t0)
    try:
        label = {"yours": "Undo your input", "bank": "Undo bank activity"}.get(scope, "Undo feed")
        what = {"yours": "Remove the rows you composed, restore the accounts",
                "bank": "Remove what was done in Kestrel Bank, restore the accounts"}.get(
            scope, "Remove tonight's rows and everything added since, restore balances")
        run.emit("start", {"run": run.id, "kind": "reset", "scope": scope, "started_at": run.started_at,
                           "stages": [{"key": "reset", "label": label, "what": what}, *STAGES[1:]]})
        stage("reset", "running")
        with SessionLocal() as db:
            born = _born(db, scope)
        with engine.begin() as conn:
            refs = list(feed.ingested_refs(conn, scope))
            # Alerts these rows created (and any case opened on them during the demo) go; alerts that existed
            # before keep their IDs and cases and are simply re-detected without the undone rows.
            gone = conn.execute(text("DELETE FROM chain WHERE id IN (SELECT chain_id FROM alert "
                                     "WHERE id = ANY(CAST(:born AS text[]))) OR root_ref = ANY(CAST(:refs AS text[])) "
                                     "RETURNING id"), {"born": sorted(born), "refs": refs}).all()
            undone = feed.reset(conn, scope)
        with session_scope() as db:
            audit.append(db, run.actor, "live.reset", target=run.id,
                         payload={"scope": scope, "undone": undone, "chains_removed": [g[0] for g in gone]})
        stage("reset", "done", f"{undone} rows undone · {len(gone)} chain{'s' if len(gone) != 1 else ''} they created removed")
        result = _detect(run, t0, None)
        run.emit("done", {**result, "undone": undone, "elapsed": round(time.perf_counter() - t0, 1)})
    except Exception:
        log.exception("live.reset.failed run=%s", run.id)
        run.emit("failed", {"message": "The reset failed — see the API log for details."})
    finally:
        _release(run)


# ── HTTP ────────────────────────────────────────────────────────────────────


class RunIn(BaseModel):
    speed: float = Field(240.0, ge=0, le=10_000, description="Simulated seconds per real second; 0 = no pauses")
    detect: bool = True


class ComposeIn(BaseModel):
    """What the person did at the console. Everything else about the rows follows from the bank's state."""

    employee_id: str = Field(..., max_length=16)
    account_id: str = Field(..., max_length=16)
    at: str = Field("21:20", pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Login time on 22 Sep, bank time")
    channel: Literal["VPN", "BRANCH"] = "VPN"
    auth: Literal["OVERRIDE", "MAKER_ONLY", "BIOMETRIC"] = "OVERRIDE"
    expired_grant: bool = True
    ticket: bool = False
    ekyc: bool = False
    rostered: bool = False
    change_mobile: bool = True
    raise_limit_to: int | None = Field(5_00_000, ge=10_000, le=50_00_000)
    takeover: bool = True
    payees: list[Literal["A-7731", "A-7768", "OUTSIDE", "FAMILY"]] = Field(default_factory=lambda: ["A-7731", "A-7768"],
                                                                         max_length=4)
    amount: int = Field(4_00_000, ge=1_000, le=25_00_000, description="Rupees per transfer")
    delay_min: int = Field(38, ge=5, le=600, description="Minutes from the login to the first transfer")
    ring_reacts: bool = True
    speed: float = Field(600.0, ge=0, le=10_000)


@router.get("/status")
def live_status(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    _enabled()
    current = _active or (next(reversed(_runs.values())) if _runs else None)
    return {**feed.status(db), "stages": STAGES, "run": current.summary() if current else None, "busy": _busy()}


@router.get("/feed")
def live_feed(p: CurrentUser, db: Annotated[Session, Depends(get_db)], reveal: bool = False) -> list[dict]:
    """Tonight's held-back rows. Ground truth (`strand`) only once the whole evening is in and no run is going."""
    _enabled()
    rows = db.execute(select(FeedEvent).where(FeedEvent.strand.notin_(feed.LIVE_STRANDS)).order_by(FeedEvent.seq)).scalars().all()
    show = reveal and rows and all(r.ingested_at for r in rows) and not _busy()
    return [{"seq": r.seq, "t": r.t.isoformat(), "table": r.source_table, "ref": r.ref, "system": r.system,
             "summary": r.summary, "ingested": r.ingested_at is not None, **({"strand": r.strand} if show else {})}
            for r in rows]


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(body: RunIn, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    _enabled()
    if not feed.status(db)["pending"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tonight's feed has already been played — reset it first.")
    run = _start("feed", "evening", p.id, lambda r: play_feed(r, body.speed, body.detect, "evening"))
    return {"run_id": run.id}


@router.get("/compose/options")
def compose_options(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Who can act, which accounts can be targeted and where money can go — from the bank as it is now."""
    _enabled()
    return compose.options(db.connection())


@router.post("/compose", status_code=status.HTTP_202_ACCEPTED)
def compose_run(body: ComposeIn, p: CurrentUser, db: Annotated[Session, Depends(get_db)],
                dry_run: bool = False) -> dict:
    """Build the rows for these choices. With `dry_run`, only describe them; otherwise stage, play and detect."""
    _enabled()
    if not dry_run and _busy():
        raise HTTPException(status.HTTP_409_CONFLICT, "A run is in progress — wait for it to finish.")
    spec = compose.Spec(**body.model_dump(exclude={"speed"}))
    conn = db.connection()
    try:
        rows = compose.build(conn, spec)
    except compose.ComposeError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    if dry_run:
        out = compose.preview(conn, rows)
        return {"rows": out, "systems": sorted({r["system"] for r in out}),
                "money_out": sum(r["row"]["amount_paise"] for r in rows if r["table"] == "txn"
                                 and r["row"]["from_account"] == body.account_id) / 100}
    staged = compose.stage(conn, rows)
    db.commit()
    with session_scope() as s:
        audit.append(s, p.id, "live.compose", target=body.account_id,
                     payload={"rows": staged, **body.model_dump(exclude={"speed"})})
    run = _start("feed", "yours", p.id, lambda r: play_feed(r, body.speed, True, "yours"))
    return {"run_id": run.id, "rows": staged}


@router.post("/detect", status_code=status.HTTP_202_ACCEPTED)
def detect_bank(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Run detection now over what Kestrel Bank has recorded (the scheduled job would, every 15 minutes)."""
    _enabled()
    if not feed.status(db)["bank"]["ingested"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing has happened in Kestrel Bank yet.")
    run = _start("feed", "bank", p.id, lambda r: play_feed(r, 0, True, "bank"))
    return {"run_id": run.id}


@router.get("/bank-activity")
def bank_activity(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    """What Kestrel Bank has written into Loom, oldest first — the input of a bank detection run."""
    _enabled()
    rows = db.execute(select(FeedEvent).where(FeedEvent.strand == "bank").order_by(FeedEvent.seq)).scalars().all()
    return [{"seq": r.seq, "t": r.t.isoformat(), "table": r.source_table, "ref": r.ref, "system": r.system,
             "summary": r.summary} for r in rows]


@router.post("/reset", status_code=status.HTTP_202_ACCEPTED)
def start_reset(p: CurrentUser, db: Annotated[Session, Depends(get_db)],
                scope: Literal["all", "yours", "bank"] = "all") -> dict:
    _enabled()
    st = feed.status(db)
    has = {"all": st["ingested"] or st["yours"]["total"] or st["bank"]["total"],
           "yours": st["yours"]["total"], "bank": st["bank"]["total"]}[scope]
    if not has:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing to reset.")
    run = _start("reset", scope, p.id, lambda r: reset_feed(r, scope))
    return {"run_id": run.id}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, p: CurrentUser) -> dict:
    _enabled()
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run")
    run.cancel.set()
    return {"run_id": run_id, "cancelling": not run.finished}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, p: CurrentUser):
    _enabled()
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run")
    try:
        start = int(request.headers.get("last-event-id", "-1")) + 1
    except ValueError:
        start = 0

    async def gen():
        i = start
        while True:
            while i < len(run.log):
                event, data = run.log[i]
                yield f"id: {i}\nevent: {event}\ndata: {json.dumps(data)}\n\n"
                i += 1
            if run.finished and i >= len(run.log):
                yield "event: end\ndata: {}\n\n"
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
