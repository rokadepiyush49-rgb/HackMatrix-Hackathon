"""Intelligence surfaces: Alibi Ledger and Mule Factory."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import employee_card, iso, rupees
from app.core.db import get_db
from app.core.security import CurrentUser
from app.loom.models import (
    AccessEvent,
    Account,
    Customer,
    Employee,
    Explanation,
    ModelPrediction,
    Signal,
    Txn,
)
from app.loom.models import (
    Session as Sess,
)

router = APIRouter(tags=["intelligence"])
TEMPLATES = ["TICKET", "PORTFOLIO", "QUEUE", "INTERACTION", "ROSTER"]


@router.get("/alibi/summary")
def alibi_summary(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    verdicts = dict(db.execute(select(Explanation.verdict, func.count()).group_by(Explanation.verdict)).all())
    total = sum(verdicts.values()) or 1
    by_emp = db.execute(select(Explanation.employee_id, Explanation.verdict, func.count())
                        .group_by(Explanation.employee_id, Explanation.verdict)).all()
    emp_cov: dict[str, dict] = {}
    for emp, v, n in by_emp:
        d = emp_cov.setdefault(emp, {"EXPLAINED": 0, "PARTIAL": 0, "UNEXPLAINED": 0})
        d[v] = n
    emps = {e.id: e for e in db.execute(select(Employee)).scalars()}
    role_cov: dict[str, list] = {}
    for emp, d in emp_cov.items():
        r = emps[emp].role if emp in emps else "?"
        role_cov.setdefault(r, []).append(d)
    template_hits = {t: 0 for t in TEMPLATES}
    for (matches,) in db.execute(select(Explanation.matches)).all():
        for m in matches or []:
            template_hits[m["template"]] = template_hits.get(m["template"], 0) + 1
    worst = sorted(emp_cov.items(), key=lambda kv: -(kv[1]["UNEXPLAINED"] * 10 + kv[1]["PARTIAL"]))[:8]
    r5 = db.execute(select(func.count()).select_from(Signal).where(Signal.detector.in_(["R5", "R6"]))).scalar()
    return {
        "total": sum(verdicts.values()), "explained": verdicts.get("EXPLAINED", 0), "partial": verdicts.get("PARTIAL", 0),
        "unexplained": verdicts.get("UNEXPLAINED", 0), "coverage": round(verdicts.get("EXPLAINED", 0) / total, 4),
        "false_positives_removed": verdicts.get("EXPLAINED", 0), "raw_access_signals": r5,
        "by_role": [{"role": r, "coverage": round(sum(x["EXPLAINED"] for x in lst) / max(sum(sum(x.values()) for x in lst), 1), 4),
                     "accesses": sum(sum(x.values()) for x in lst)} for r, lst in sorted(role_cov.items())],
        "by_template": [{"template": t, "matches": n} for t, n in template_hits.items()],
        "attention": [{"employee": employee_card(db, emps.get(e)), **d} for e, d in worst],
    }


@router.get("/alibi/ledger")
def alibi_ledger(p: CurrentUser, db: Annotated[Session, Depends(get_db)], employee: str | None = None,
                 verdict: str | None = None, limit: int = 80, day: str | None = None) -> list[dict]:
    stmt = select(Explanation, AccessEvent).join(AccessEvent, AccessEvent.id == Explanation.access_event_id)
    if employee:
        stmt = stmt.where(Explanation.employee_id == employee)
    if verdict:
        stmt = stmt.where(Explanation.verdict == verdict)
    if day:
        stmt = stmt.where(func.date(Explanation.occurred_at) == day)
    rows = db.execute(stmt.order_by(Explanation.occurred_at.desc()).limit(min(limit, 400))).all()
    return [{"access_id": x.access_event_id, "t": iso(x.occurred_at), "employee_id": x.employee_id,
             "action": ae.action, "account_id": ae.account_id, "customer_id": ae.customer_id,
             "override": ae.override_used, "verdict": x.verdict, "purpose_ok": x.purpose_ok, "timing_ok": x.timing_ok,
             "reasons_found": sum(1 for c in x.checked if c["ok"]), "checked": x.checked,
             "reason": next((c.get("ref") or c["template"].title() for c in x.checked if c["ok"]), None)}
            for x, ae in rows]


@router.get("/alibi/access/{access_id}")
def alibi_access(access_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    x = db.get(Explanation, access_id)
    ae = db.get(AccessEvent, access_id)
    if x is None or ae is None:
        raise HTTPException(404, "Access not found")
    return {"access_id": access_id, "t": iso(ae.occurred_at), "employee_id": ae.employee_id, "action": ae.action,
            "account_id": ae.account_id, "verdict": x.verdict, "checked": x.checked}


@router.get("/mule/clusters")
def mule_clusters(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    out = []
    mule = {m.entity_ref: (m.p, m.contributions) for m in db.execute(select(ModelPrediction).where(ModelPrediction.model == "M6")).scalars()}
    for s in db.execute(select(Signal).where(Signal.detector == "G4")).scalars():
        pl = s.payload
        emp = db.get(Employee, pl["employee"])
        accounts, nodes, edges = [], [], []
        nodes.append({"id": emp.id, "kind": "employee", "label": emp.id, "sub": emp.pseudonym})
        ident_owner: dict[str, list[str]] = {}
        for aid in pl["accounts"]:
            a = db.get(Account, aid)
            cu = db.get(Customer, a.customer_id)
            devs = [d for d in db.execute(select(Sess.device_id).where(Sess.actor_id == a.customer_id,
                                                                         Sess.device_id.isnot(None)).distinct()).scalars()]
            inflow = db.execute(select(func.coalesce(func.sum(Txn.amount_paise), 0)).where(Txn.to_account == aid)).scalar()
            cash = db.execute(select(func.coalesce(func.sum(Txn.amount_paise), 0)).where(Txn.from_account == aid,
                                                                                         Txn.to_account == "X-ATM")).scalar()
            mp = mule.get(aid, (None, []))
            accounts.append({"id": aid, "opened_at": iso(a.opened_at), "mode": a.opening_mode,
                             "self_approved": a.opened_by == a.kyc_approved_by, "segment": cu.segment if cu else None,
                             "devices": devs, "inflow": rupees(inflow), "cash_out": rupees(cash), "mule_p": mp[0],
                             "presenceless": aid in pl["presenceless"]})
            nodes.append({"id": aid, "kind": "account", "label": aid, "sub": cu.segment.title() if cu else "",
                          "mule_p": mp[0]})
            edges.append({"id": f"{emp.id}>{aid}", "source": emp.id, "target": aid, "kind": "APPROVED"})
            for d in devs:
                ident_owner.setdefault(f"dev:{d}", []).append(aid)
            if cu and cu.phone_tok:
                ident_owner.setdefault(f"ph:{cu.phone_tok}", []).append(aid)
        for ident, owners in ident_owner.items():
            if len(owners) < 2:
                continue
            kind, raw = ident.split(":", 1)
            nid = raw if kind == "dev" else f"PHONE-{raw[-4:].upper()}"
            nodes.append({"id": nid, "kind": "device" if kind == "dev" else "phone", "label": nid,
                          "sub": f"shared by {len(owners)}"})
            for aid in owners:
                edges.append({"id": f"{aid}>{nid}", "source": aid, "target": nid,
                              "kind": "SHARED_DEVICE" if kind == "dev" else "SHARED_PHONE"})
        shared_dev = sum(1 for k, v in ident_owner.items() if k.startswith("dev:") and len(v) > 1)
        shared_ph = sum(1 for k, v in ident_owner.items() if k.startswith("ph:") and len(v) > 1)
        base = pl["baseline_60d"]
        out.append({
            "signal_id": s.id, "employee": employee_card(db, emp), "summary": s.summary,
            "stats": {"accounts": pl["approvals_60d"], "baseline": base,
                      "deviation": round((pl["approvals_60d"] - base) / base, 2) if base else None,
                      "burst_p": pl["burst_p"], "shared_accounts": len(pl["shared_accounts"]),
                      "shared_devices": shared_dev, "shared_phones": shared_ph,
                      "presenceless": len(pl["presenceless"]),
                      "inflow": sum(x["inflow"] for x in accounts), "cash_out": sum(x["cash_out"] for x in accounts)},
            "accounts": accounts, "graph": {"nodes": nodes, "edges": edges},
        })
    return out
