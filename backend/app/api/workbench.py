"""Council, Control Lab (Mend), Scenario Lab, and Ask SUTRA."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import alert_full, iso, latest_run
from app.copilot.engine import ask, str_draft
from app.core import audit
from app.core.db import get_db
from app.core.security import CurrentUser, Principal, require
from app.council.engine import AGENTS, MODERATOR, RECORDS, Council
from app.loom.models import (
    Account,
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


@router.get("/council/{alert_id}")
def council(alert_id: str, db: Annotated[Session, Depends(get_db)],
            p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
    detail = alert_full(db, alert_id)
    detail["latency_s"] = detail.get("latency_s")
    m = _mend(db, detail, [])
    result = Council(detail, m, _lookups(db, detail)).run()
    audit.append(db, p.id, "council.run", alert_id, {"outcome": result["consensus"]["outcome"]})
    db.commit()
    return result


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


class FlipIn(BaseModel):
    key: str = "S4-twin"


@router.post("/lab/flip")
def flip(body: FlipIn, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
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
                p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
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
                p: Annotated[Principal, Depends(require("cases:read"))]) -> dict:
    detail = alert_full(db, body.alert_id)
    detail["mend"] = _mend(db, detail, [])
    out = str_draft(detail)
    audit.append(db, p.id, "copilot.str_draft", body.alert_id, {"mode": out["mode"]})
    db.commit()
    return out
