"""Council, Control Lab (Mend), Scenario Lab, and Ask SUTRA."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.common import alert_full, iso, latest_run
from app.copilot.engine import ask, str_draft
from app.core import audit
from app.core.db import SessionLocal, get_db
from app.core.security import CurrentUser, Investigator, Principal, require
from app.council.engine import AGENTS, MODERATOR, RECORDS, Council
from app.loom.models import (
    Account,
    CouncilRun,
    Roster,
    ScenarioLabel,
    WorkItem,
)
from app.mend.controls import CONTROLS, simulate

router = APIRouter(tags=["workbench"])


# ── Mend ───────────────────────────────────────────────────────────────────


def _mend(db: Session, detail: dict, selected: list[str] | None = None) -> dict | None:
    run = latest_run(db)
    fr = (run.results or {}).get("controls_friction", {}) if run else {}
    chain = {"id": detail["chain_id"], "kind": {"CIRCULAR_FLOW": "CIRCULAR"}.get(detail["typology"], detail["typology"]),
             "features": detail["features"] or {}, "amount_at_risk": detail["amount_at_risk"]}
    links = [dict(lk) for lk in detail["links"]]
    for lk in links:
        if lk["code"] == "E0":
            ent = next((e for e in detail["evidence"] if e["kind"] == "ENTITLEMENT"), None)
            if ent and ent["facts"].get("intended_expiry") not in (None, "None", "NaT"):
                lk["expiry"] = ent["facts"]["intended_expiry"]
    return simulate(chain, links, selected if selected is not None else [], fr)


@router.get("/mend/controls")
def controls(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    run = latest_run(db)
    fr = (run.results or {}).get("controls_friction", {}) if run else {}
    return {"controls": [{"id": c.id, "name": c.name, "description": c.description, "breaks_at": c.breaks_at,
                          "effort": c.effort, "kinds": list(c.kinds), "friction": fr.get(c.id, {})} for c in CONTROLS]}


@router.get("/mend/{alert_id}")
def mend(alert_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)],
         controls: Annotated[list[str] | None, Query()] = None) -> dict:
    detail = alert_full(db, alert_id)
    return _mend(db, detail, controls or [])


# ── Council ────────────────────────────────────────────────────────────────


def _lookups(db: Session, detail: dict) -> dict:
    """Pre-compute what each requestable record would return from Loom."""
    out: dict = {}
    emp = detail.get("employee", {}) or {}
    root = next((lk for lk in detail["links"] if lk["code"] in ("E2", "E3")), None)
    import pandas as pd

    t = pd.Timestamp(root["t"] if root else detail["first_t"]).to_pydatetime()
    roster_ev = [e["code"] for e in detail["evidence"] if e["kind"] == "ROSTER"]
    if emp.get("id") and root:
        rows = db.execute(select(Roster).where(Roster.employee_id == emp["id"], Roster.shift_start <= t,
                                               Roster.shift_end >= t)).scalars().all()
        out["roster"] = {"found": True, "on_duty": bool(rows), "evidence": roster_ev,
                         "text": (f"{rows[0].duty_type.title()} shift covers the access." if rows else
                                  "Retrieved — no regular, overtime or camp shift covers the access time.")}
    acct = detail.get("account") or {}
    cust = None
    if acct.get("id"):
        a = db.get(Account, acct["id"])
        cust = a.customer_id if a else None
    if cust and root:
        wi = db.execute(select(WorkItem).where(WorkItem.customer_id == cust, WorkItem.kind.in_(["CALL", "TICKET", "TOKEN", "EKYC"]),
                                               WorkItem.created_at <= t,
                                               WorkItem.created_at >= _minus(t, 7))).scalars().all()
        out["calls"] = {"found": bool(wi), "evidence": [e["code"] for e in detail["evidence"] if e["kind"] == "ALIBI"][:1],
                        "text": f"{len(wi)} customer contact record(s) found." if wi else
                        f"Retrieved — no call, ticket, token or eKYC for {cust} in the 7 days before."}
    kyc = [e["code"] for e in detail["evidence"] if e["kind"] == "ACCOUNT_OPENING"]
    out["kyc"] = {"found": bool(kyc), "evidence": kyc,
                  "text": f"{len(kyc)} opening record(s): opened and approved by {emp.get('id', 'staff')}, customer not present."
                  if kyc else "No internal KYC records for the recipients."}
    return out


def _minus(t: str, days: int):
    import pandas as pd

    return pd.Timestamp(t) - timedelta(days=days)


@router.get("/council/agents")
def council_agents(p: CurrentUser) -> dict:
    return {"agents": AGENTS, "moderator": MODERATOR,
            "records": [{"key": k, "label": v[0], "system": v[1], "ingested": v[2]} for k, v in RECORDS.items()]}


@router.get("/council/status")
def council_status(p: Annotated[Principal, Depends(require("cases:read"))], check: bool = False) -> dict:
    """Which engine the council uses and, with `check`, whether Groq accepts the key and serves the model.
    The key itself is never returned."""
    from app.core.config import get_settings
    from app.council.harness import PROMPT_VERSION
    from app.council.llm import MODEL_LIMITS, LLMError, client_from_settings

    s = get_settings()
    out = {"configured_engine": s.council_engine, "key_configured": bool(s.groq_api_key), "model": s.groq_model,
           "model_facts": MODEL_LIMITS.get(s.groq_model), "prompt_version": PROMPT_VERSION,
           "effective_engine": "llm" if s.groq_api_key and s.council_engine != "deterministic" else "deterministic",
           "budgets": {"calls": s.council_max_calls, "tokens": s.council_token_budget, "deadline_s": s.council_deadline_s}}
    if check:
        try:
            client = client_from_settings()
            out["check"] = client.check() if client else {"ok": False, "kind": "config", "detail": "no Groq key configured"}
        except LLMError as e:
            out["check"] = {"ok": False, "kind": e.kind, "detail": str(e)}
    return out


def _council_inputs(db: Session, alert_id: str) -> tuple[dict, dict | None, dict]:
    detail = alert_full(db, alert_id)
    detail["latency_s"] = detail.get("latency_s")
    m = _mend(db, detail, [])
    detail["mend"] = m
    look = _lookups(db, detail)
    _with_account_aggregator(db, detail, look)
    return detail, m, look


def _with_account_aggregator(db: Session, detail: dict, look: dict) -> None:
    """Consented statements for the case's customers become labelled evidence and answer 'source of funds'."""
    from app.core.config import get_settings
    from app.integrations.aa.service import evidence_for

    s = get_settings()
    if s.aa_provider == "synthetic" and not s.demo_mode:
        return
    accounts = [e for e in detail.get("entity_refs") or [] if e.startswith("A-")]
    if detail.get("account"):
        accounts.append(detail["account"]["id"])
    customers = sorted(set(db.execute(text("SELECT customer_id FROM account WHERE id = ANY(:a) AND customer_id IS NOT NULL"),
                                      {"a": accounts}).scalars()))
    items, sof = evidence_for(db, customers)
    if sof:
        look["sof"] = {**sof, "system": "Account Aggregator"}
    if items:
        have = {e["code"] for e in detail["evidence"]}
        detail["evidence"] += [e for e in items if e["code"] not in have]


def _case_identity(db: Session, alert_id: str) -> tuple[str | None, str | None]:
    from app.brief import revisions

    key = db.execute(text("SELECT c.kind || '|' || c.root_ref FROM alert a JOIN chain c ON c.id = a.chain_id "
                          "WHERE a.id = :a"), {"a": alert_id}).scalar()
    snap = revisions.snapshots(db.connection()).get(key) if key else None
    return key, revisions.content_sha(snap) if snap else None


def _run_view(r: CouncilRun, current_sha: str | None) -> dict:
    return {"run_id": r.id, "status": r.status, "engine": r.engine, "requested_engine": r.requested_engine,
            "model": r.model, "prompt_version": r.prompt_version, "actor": r.actor,
            "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "usage": r.usage, "coverage": r.coverage,
            "error": r.error, "stale": bool(current_sha and r.case_sha256 and r.case_sha256 != current_sha)}


@router.get("/council/{alert_id}")
def council(alert_id: str, db: Annotated[Session, Depends(get_db)],
            p: Annotated[Principal, Depends(require("cases:read"))], engine: str | None = None) -> dict:
    """The latest saved council run for the alert; without one (or with `engine=deterministic`), the
    deterministic council computed now."""
    if engine != "deterministic":
        saved = db.execute(select(CouncilRun).where(CouncilRun.alert_id == alert_id, CouncilRun.result.is_not(None))
                           .order_by(CouncilRun.started_at.desc()).limit(1)).scalars().first()
        if saved is not None:
            _, sha = _case_identity(db, alert_id)
            return {**saved.result, "run": _run_view(saved, sha)}
    detail, m, look = _council_inputs(db, alert_id)
    result = Council(detail, m, look).run()
    result["engine"] = "deterministic"
    audit.append(db, p.id, "council.run", alert_id, {"outcome": result["consensus"]["outcome"], "engine": "deterministic"})
    db.commit()
    return result


class CouncilRunIn(BaseModel):
    engine: Literal["auto", "llm", "deterministic"] = "auto"


_council_cancel: dict[str, threading.Event] = {}


def _council_worker(run_id: str, alert_id: str, engine: str, actor: str) -> None:
    from app.council.agentic import run_council

    cancel = _council_cancel.setdefault(run_id, threading.Event())
    try:
        with SessionLocal() as db:
            detail, m, look = _council_inputs(db, alert_id)
        result = run_council(detail, m, look, engine, cancel)
        cov = result.get("coverage") or {}
        status = ("FALLBACK" if result.get("fallback_reason") else
                  "PARTIAL" if cov.get("partial") else "COMPLETE")
        with SessionLocal() as db:
            r = db.get(CouncilRun, run_id)
            r.status, r.engine, r.finished_at = status, result.get("engine"), datetime.now(UTC)
            r.model, r.prompt_version = result.get("model"), result.get("prompt_version")
            r.usage = (result.get("trace") or {}).get("usage") or {"seconds": result["stats"].get("seconds")}
            r.coverage, r.trace = cov, result.get("trace") or {}
            r.result = {k: v for k, v in result.items() if k != "trace"}
            r.error = result.get("fallback_reason")
            audit.append(db, actor, "council.run", alert_id, {"run": run_id, "engine": r.engine, "status": status,
                                                               "outcome": result["consensus"]["outcome"],
                                                               "llm_calls": result["stats"].get("llm_calls", 0)})
            db.commit()
    except Exception as e:  # recorded on the run; never leaves a run stuck in RUNNING
        logging.getLogger("sutra.council").exception("council.run.failed run=%s", run_id)
        with SessionLocal() as db:
            r = db.get(CouncilRun, run_id)
            if r is not None:
                r.status, r.finished_at, r.error = "FAILED", datetime.now(UTC), f"{type(e).__name__}: see the API log"
                db.commit()
    finally:
        _council_cancel.pop(run_id, None)


@router.post("/council/{alert_id}/runs", status_code=202)
def start_council(alert_id: str, body: CouncilRunIn, db: Annotated[Session, Depends(get_db)],
                  p: Annotated[Principal, Depends(require("cases:investigate"))]) -> dict:
    """Convene the council (LLM agents when configured). Runs in the background; poll the run."""
    from app.core.config import get_settings

    alert_full(db, alert_id)  # 404 for an unknown alert
    horizon = datetime.now(UTC) - timedelta(seconds=get_settings().council_deadline_s + 60)
    busy = db.execute(select(CouncilRun).where(CouncilRun.alert_id == alert_id, CouncilRun.status == "RUNNING",
                                               CouncilRun.started_at > horizon)).scalars().first()
    if busy:
        raise HTTPException(409, f"The council is already sitting on {alert_id} ({busy.id}).")
    key, sha = _case_identity(db, alert_id)
    run_id = f"CR-{uuid.uuid4().hex[:10].upper()}"
    db.add(CouncilRun(id=run_id, alert_id=alert_id, alert_key=key, case_sha256=sha, requested_engine=body.engine,
                      status="RUNNING", actor=p.id, started_at=datetime.now(UTC), usage={}, coverage={}, trace={}))
    audit.append(db, p.id, "council.convene", alert_id, {"run": run_id, "engine": body.engine})
    db.commit()
    threading.Thread(target=_council_worker, args=(run_id, alert_id, body.engine, p.id), name=f"sutra-{run_id}",
                     daemon=True).start()
    return {"run_id": run_id, "status": "RUNNING"}


@router.get("/council/runs/{run_id}")
def council_run(run_id: str, db: Annotated[Session, Depends(get_db)],
                p: Annotated[Principal, Depends(require("cases:read"))], trace: bool = True) -> dict:
    r = db.get(CouncilRun, run_id)
    if r is None:
        raise HTTPException(404, "Unknown council run")
    _, sha = _case_identity(db, r.alert_id)
    out = {**_run_view(r, sha), "alert_id": r.alert_id}
    if trace:
        out["trace"] = r.trace
    if r.result is not None:
        out["result"] = r.result
    return out


@router.post("/council/runs/{run_id}/cancel")
def cancel_council(run_id: str, p: Annotated[Principal, Depends(require("cases:investigate"))]) -> dict:
    ev = _council_cancel.get(run_id)
    if ev:
        ev.set()
    return {"run_id": run_id, "cancelling": bool(ev)}


# ── Scenario Lab ───────────────────────────────────────────────────────────


@router.get("/lab/report")
def lab_report(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    run = latest_run(db)
    if run is None:
        raise HTTPException(404, "No pipeline run yet — run `make detect`")
    labels = {x.key: x for x in db.execute(select(ScenarioLabel)).scalars()}
    res = dict(run.results)
    for s in res.get("scenarios", []):
        lab = labels.get(s["key"])
        s["entities"] = lab.entities[:12] if lab else []
    from app.ml.models import model_meta

    res["models"] = model_meta()
    res["run_id"], res["run_at"] = run.id, iso(run.finished_at)
    return res


@router.get("/lab/model-eval")
def model_eval(p: CurrentUser) -> dict:
    """M7 against the rule baselines on held-out cases and later events (written by `make train`)."""
    import json

    from app.lab.heldout import REPORTS

    path = REPORTS / "fin04_eval.json"
    if not path.exists():
        raise HTTPException(404, "No model evaluation yet — run `make train`")
    return json.loads(path.read_text())


class FlipIn(BaseModel):
    key: str = "S4-twin"


@router.post("/lab/flip")
def flip(body: FlipIn, p: Investigator, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Counterfactual: remove the twin's explaining records and re-run Alibi → Needle → Brief for it."""
    from app.alibi.engine import explain
    from app.brief.builder import brief_for
    from app.brief.context import BriefContext
    from app.loom.frames import load_frames
    from app.ml import baselines
    from app.needle import chains as N

    lab = db.get(ScenarioLabel, body.key)
    if lab is None or lab.scenario != "S4" or lab.variant != "twin":
        raise HTTPException(422, "Flip is available for the insider twin (S4-twin)")
    f = load_frames()
    wi = f.work_item[f.work_item["id"].isin(lab.events) & f.work_item["kind"].isin(["TICKET", "EKYC"])]
    acc = f.access_event[f.access_event["id"].isin(lab.events)]
    emp = acc["employee_id"].iloc[0]
    day = acc["occurred_at"].iloc[0].normalize()
    ros = f.roster[(f.roster["employee_id"] == emp) & (f.roster["duty_type"] == "CAMP")
                   & (f.roster["shift_start"] >= day)]
    before = explain(f, only_access_ids=set(acc["id"]))
    after = explain(f, exclude_work_items=set(wi["id"]), exclude_rosters=set(ros["id"]), only_access_ids=set(acc["id"]))
    same_day = f.access_event[(f.access_event["employee_id"] == emp)
                              & (f.access_event["occurred_at"].dt.normalize() == day)]
    full = explain(f, exclude_work_items=set(wi["id"]), exclude_rosters=set(ros["id"]),
                   only_access_ids=set(same_day["id"]))
    ix = N.Index(f, full)
    drafts = N.insider_chains(ix, only_accounts=set(acc["account_id"]))
    result = None
    if drafts:
        sess = baselines.session_surprise(f, baselines.fit_rhythm(f))
        nav = baselines.session_navigation(f, baselines.fit_navigation(f))
        import pandas as pd

        ctx = BriefContext(f, ix, [], [], {}, [], sess, nav, pd.DataFrame(columns=["p", "contributions"]))
        b = brief_for(ctx, drafts[0])
        result = {"priority": b.priority, "claim": b.claim, "lattice_rule": b.lattice_rule,
                  "classifier_p": b.classifier["p"] if b.classifier else None,
                  "dims": [d.as_dict() for d in b.dims],
                  "links": [{"code": lk.code, "t": lk.t.isoformat(), "title": lk.title, "detail": lk.detail}
                            for lk in b.draft.links]}
    removed = [{"id": r.id, "kind": r.kind, "ref": r.ref, "text": r.text} for r in wi.itertuples()] + \
              [{"id": r.id, "kind": "ROSTER", "ref": r.id, "text": f"{r.duty_type.title()} roster {r.shift_start:%H:%M}–{r.shift_end:%H:%M}"}
               for r in ros.itertuples()]
    return {"key": body.key, "removed": removed,
            "before": [{"access_id": r.access_event_id, "verdict": r.verdict, "checked": r.checked} for r in before.itertuples()],
            "after": [{"access_id": r.access_event_id, "verdict": r.verdict, "checked": r.checked} for r in after.itertuples()],
            "alert": result,
            "note": "Counterfactual computed in memory; nothing is written to the database."}


# ── Ask SUTRA ──────────────────────────────────────────────────────────────


class AskIn(BaseModel):
    alert_id: str
    question: str = Field(min_length=3, max_length=500)


@router.post("/copilot/ask")
def copilot_ask(body: AskIn, db: Annotated[Session, Depends(get_db)],
                p: Annotated[Principal, Depends(require("copilot:use"))]) -> dict:
    detail = alert_full(db, body.alert_id)
    detail["mend"] = _mend(db, detail, [])
    ans = ask(detail, body.question).as_dict()
    audit.append(db, p.id, "copilot.ask", body.alert_id, {"question": body.question, "mode": ans["mode"],
                                                          "dropped": len(ans["dropped"])})
    db.commit()
    return ans


class StrIn(BaseModel):
    alert_id: str


@router.post("/copilot/str")
def copilot_str(body: StrIn, db: Annotated[Session, Depends(get_db)],
                p: Annotated[Principal, Depends(require("str:draft"))]) -> dict:
    detail = alert_full(db, body.alert_id)
    detail["mend"] = _mend(db, detail, [])
    out = str_draft(detail)
    audit.append(db, p.id, "copilot.str_draft", body.alert_id, {"mode": out["mode"]})
    db.commit()
    return out
