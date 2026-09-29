"""Command Center: what is happening right now, at executive level."""

from __future__ import annotations

from statistics import median
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import (
    TYPOLOGY_LABEL,
    alert_summary,
    chain_links,
    iso,
    latest_run,
    link_dict,
    rupees,
)
from app.core.db import get_db
from app.core.security import CurrentUser
from app.loom.models import (
    Account,
    Alert,
    Chain,
    Evidence,
    Explanation,
    ModelPrediction,
    Signal,
    Txn,
)

router = APIRouter(tags=["command center"])
QUEUED = ("P1", "P2", "P3")


def money_graph(db: Session, alerts: list[tuple[Alert, Chain]]) -> dict:
    """Nodes and edges for 'Money in Motion': who/what moved money, when, and why."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    mule_p = {m.entity_ref: m.p for m in db.execute(select(ModelPrediction).where(ModelPrediction.model == "M6")).scalars()}

    def node(nid: str, kind: str, label: str, sub: str = "", role: str = "", chain: str = "") -> None:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "label": label, "sub": sub, "role": role, "chains": [],
                          "mule_p": mule_p.get(nid)}
        if chain and chain not in nodes[nid]["chains"]:
            nodes[nid]["chains"].append(chain)

    for a, c in alerts:
        if a.typology not in ("INSIDER_ATO", "EXTERNAL_ATO", "MULE_FACTORY"):
            continue
        links = chain_links(db, c.id)
        root = next((lk for lk in links if lk.code in ("E3", "E2")), None)
        if c.employee_id and a.typology == "INSIDER_ATO":
            node(c.employee_id, "employee", c.employee_id, "staff", "insider", c.id)
            if c.account_id:
                acct = db.get(Account, c.account_id)
                node(c.account_id, "account", c.account_id, acct.holder_name if acct else "", "victim", c.id)
                edges.append({"id": f"{c.id}:priv", "source": c.employee_id, "target": c.account_id, "kind": "privilege",
                              "t": iso(root.t) if root else iso(c.first_t), "label": root.title if root else "access",
                              "chain": c.id, "priority": a.priority})
        txns = db.execute(select(Evidence).where(Evidence.alert_id == a.id, Evidence.kind == "TXN")
                          .order_by(Evidence.observed_at)).scalars().all()
        for e in txns:
            frm, to = e.entities[0], e.entities[1]
            for nid in (frm, to):
                acc = db.get(Account, nid)
                kind = "cash" if nid in ("X-ATM", "X-CASH") else "external" if nid.startswith("X-") else "account"
                role = "cashout" if nid == "X-ATM" else ("victim" if nid == c.account_id else "")
                node(nid, kind, nid, acc.holder_name if acc else "", role, c.id)
            lead = (e.observed_at - root.t).total_seconds() if root else None
            edges.append({"id": f"{a.id}:{e.code}", "source": frm, "target": to, "kind": "money",
                          "amount": e.facts.get("amount"), "t": iso(e.observed_at), "channel": e.facts.get("channel"),
                          "txn": e.source_ref, "evidence": e.code, "chain": c.id, "priority": a.priority,
                          "employee": c.employee_id, "chain_latency_s": c.latency_s,
                          "after_root_s": lead, "root_event": root.title if root else None})
    # mark roles
    for e in edges:
        if e["kind"] == "money" and nodes.get(e["target"], {}).get("role") == "" and (nodes[e["target"]]["mule_p"] or 0) >= 0.5:
            nodes[e["target"]]["role"] = "mule"
    return {"nodes": list(nodes.values()), "edges": edges}


@router.get("/overview")
def overview(p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    rows = db.execute(select(Alert, Chain).join(Chain, Chain.id == Alert.chain_id)
                      .where(Alert.priority.in_(QUEUED), Alert.state.notin_(["CLOSED_BENIGN", "CLOSED_UNPROVEN"]))
                      ).all()
    rows = sorted(rows, key=lambda r: ({"P1": 0, "P2": 1, "P3": 2}[r[0].priority], -r[1].amount_at_risk_paise))
    now = db.execute(select(func.max(Txn.occurred_at))).scalar()
    amount = sum(rupees(c.amount_at_risk_paise) for _, c in rows)
    latencies = [c.latency_s for a, c in rows if c.latency_s and a.typology in ("INSIDER_ATO", "EXTERNAL_ATO")]
    in_motion = [c for _, c in rows if now and (now - c.last_t).total_seconds() <= 48 * 3600]
    verdicts = dict(db.execute(select(Explanation.verdict, func.count()).group_by(Explanation.verdict)).all())
    total_access = sum(verdicts.values()) or 1
    det = dict(db.execute(select(Signal.detector, func.count()).group_by(Signal.detector)).all())
    unexplained_overrides = db.execute(
        select(func.count()).select_from(Signal).where(Signal.detector == "R7")).scalar() or 0

    rail_alert = next(((a, c) for a, c in rows if a.typology == "INSIDER_ATO" and a.priority == "P1"), rows[0] if rows else None)
    rail = None
    if rail_alert:
        a, c = rail_alert
        rail = {"alert": alert_summary(a, c), "links": [link_dict(lk) for lk in chain_links(db, c.id)]}

    by_typology: dict[str, dict] = {}
    for a, c in rows:
        t = by_typology.setdefault(a.typology, {"typology": a.typology, "label": TYPOLOGY_LABEL.get(a.typology), "count": 0,
                                                "amount": 0.0})
        t["count"] += 1
        t["amount"] += rupees(c.amount_at_risk_paise)
    signals = db.execute(select(Signal).where(Signal.detector.notin_(["G3", "R6"])).order_by(Signal.window_end.desc())
                         .limit(24)).scalars().all()
    run = latest_run(db)
    return {
        "as_of": iso(now),
        "hero": {"amount_at_risk": amount, "active_chains": len(rows),
                 "critical": sum(1 for a, _ in rows if a.priority == "P1"),
                 "in_motion": len(in_motion)},
        "kpis": {
            "active_chains": len(rows),
            "amount_at_risk": amount,
            "median_access_to_money_s": median(latencies) if latencies else None,
            "unexplained_accesses": verdicts.get("UNEXPLAINED", 0),
            "partially_explained": verdicts.get("PARTIAL", 0),
            "alibi_coverage": round(verdicts.get("EXPLAINED", 0) / total_access, 4),
            "mule_clusters": det.get("G4", 0),
            "controls_bypassed": {"expired_entitlements": det.get("R9", 0), "sod_breaches": det.get("R8", 0),
                                  "presence_less_openings": det.get("R10", 0), "overrides": unexplained_overrides},
        },
        "rail": rail,
        "alerts": [alert_summary(a, c) for a, c in rows],
        "by_typology": list(by_typology.values()),
        "money": money_graph(db, rows),
        "signals": [{"id": s.id, "detector": s.detector, "family": s.family, "summary": s.summary,
                     "t": iso(s.window_end), "entities": s.entity_refs[:4], "strength": s.strength} for s in signals],
        "funnel": (run.results or {}).get("funnel") if run else None,
        "scenario_summary": (run.results or {}).get("summary") if run else None,
    }
