"""Graph surfaces: case replay (as-of), risk-network neighbourhoods and money trails.

Replay returns every edge and state change with its timestamp, so the client can morph the
graph as the scrubber moves without a round trip; `as_of` additionally filters server-side
on both valid time and system time (ingested_at) for audit reproduction (docs/adr/003).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.common import chain_links, iso, link_dict, load_alert, rupees
from app.core.db import get_db
from app.core.pii import mask_tail
from app.core.security import CurrentUser
from app.loom.models import (
    AccessEvent,
    Account,
    Alert,
    Beneficiary,
    Chain,
    Customer,
    Device,
    Employee,
    Entitlement,
    Explanation,
    ModelPrediction,
    Relationship,
    Roster,
    StateChange,
    Txn,
)
from app.loom.models import (
    Session as Sess,
)

router = APIRouter(tags=["graph"])


def _node(nodes: dict, nid: str, kind: str, label: str, sub: str = "", **extra) -> None:
    if nid and nid not in nodes:
        nodes[nid] = {"id": nid, "kind": kind, "label": label, "sub": sub, **extra}


def _acct_node(db: Session, nodes: dict, aid: str, role: str = "", mule: dict | None = None) -> None:
    a = db.get(Account, aid)
    if a is None:
        return
    kind = "cash" if aid in ("X-ATM", "X-CASH") else "external" if a.kind == "EXTERNAL" else "account"
    _node(nodes, aid, kind, aid, a.holder_name, role=role, status=a.status, bank=a.bank_name,
          mule_p=(mule or {}).get(aid))


@router.get("/replay/{alert_id}")
def replay(alert_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)],
           as_of: datetime | None = None) -> dict:
    a, c = load_alert(db, alert_id)
    links = chain_links(db, c.id)
    mule = {m.entity_ref: m.p for m in db.execute(select(ModelPrediction).where(ModelPrediction.model == "M6")).scalars()}
    ents = set(c.entity_refs or [])
    accounts = [e for e in ents if e.startswith(("A-", "X-"))]
    t0 = min(lk.t for lk in links) - pd.Timedelta(hours=2)
    t1 = max(lk.t for lk in links) + pd.Timedelta(minutes=30)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    events: list[dict] = []

    def edge(eid, s, t, kind, when, label="", **extra):
        edges.append({"id": eid, "source": s, "target": t, "kind": kind, "t": iso(when), "label": label, **extra})

    emp = db.get(Employee, c.employee_id) if c.employee_id else None
    victim = db.get(Account, c.account_id) if c.account_id else None
    if emp:
        _node(nodes, emp.id, "employee", emp.id, emp.pseudonym, role="insider")
    for aid in accounts:
        role = "victim" if aid == c.account_id else ("cashout" if aid == "X-ATM" else "")
        _acct_node(db, nodes, aid, role, mule)
    if victim and victim.customer_id:
        cust = db.get(Customer, victim.customer_id)
        _node(nodes, cust.id, "customer", cust.id, cust.segment.title(), role="owner")
        edge(f"own:{cust.id}", cust.id, victim.id, "OWNS", victim.opened_at, "owns")

    # entitlements (IAM) used in the chain
    for lk in links:
        if lk.event_type == "ENTITLEMENT":
            g = db.get(Entitlement, lk.event_id)
            _node(nodes, g.id, "entitlement", g.request_ref or g.permission_code, g.permission_code.replace("_", " ").lower(),
                  expiry=iso(g.intended_expiry), revoked=iso(g.revoked_at))
            edge(f"holds:{g.id}", emp.id, g.id, "HOLDS", g.valid_from, "granted", expiry=iso(g.intended_expiry))
            events.append({"t": iso(g.valid_from), "lane": "IAM", "title": "Override granted",
                           "detail": f"{g.request_ref} · expires {g.intended_expiry:%d %b %H:%M}", "code": "E0"})
            if g.intended_expiry is not None:
                events.append({"t": iso(g.intended_expiry), "lane": "IAM", "title": "Intended expiry passed",
                               "detail": "Grant never revoked — still usable", "code": "E0·"})

    # staff session + accesses in the window
    if emp:
        acc = db.execute(select(AccessEvent).where(AccessEvent.employee_id == emp.id, AccessEvent.occurred_at >= t0,
                                                   AccessEvent.occurred_at <= t1).order_by(AccessEvent.occurred_at)).scalars().all()
        sess_ids = {x.session_id for x in acc if x.session_id}
        for s in db.execute(select(Sess).where(Sess.id.in_(sess_ids))).scalars():
            _node(nodes, s.device_id, "device", s.device_id, "staff device", role="staff_device")
            edge(f"sess:{s.id}", emp.id, s.device_id, "SESSION", s.started_at, f"{s.channel} login")
        ex = {e.access_event_id: e for e in db.execute(select(Explanation).where(
            Explanation.access_event_id.in_([x.id for x in acc]))).scalars()}
        for x in acc:
            if x.account_id and x.account_id in nodes:
                kind = "CHANGED" if x.action in ("MOBILE_UPDATE", "LIMIT_CHANGE") else "ACCESSED"
                edge(f"acc:{x.id}", emp.id, x.account_id, kind, x.occurred_at, x.action.replace("_", " ").lower(),
                     override=x.override_used, verdict=ex.get(x.id).verdict if x.id in ex else None)
        roster = db.execute(select(Roster).where(Roster.employee_id == emp.id, Roster.shift_end <= t1,
                                                 Roster.shift_end >= t0 - pd.Timedelta(hours=12))
                            .order_by(Roster.shift_end.desc())).scalars().first()
        if roster:
            events.append({"t": iso(roster.shift_end), "lane": "HR", "title": "Shift ended",
                           "detail": f"{roster.duty_type.title()} shift {roster.shift_start:%H:%M}–{roster.shift_end:%H:%M}",
                           "code": "HR"})

    # state histories (bitemporal) for chain accounts
    state: dict[str, dict] = {}
    for aid in [x for x in accounts if x.startswith("A-")]:
        sc = db.execute(select(StateChange).where(StateChange.account_id == aid).order_by(StateChange.occurred_at)).scalars().all()
        acct = db.get(Account, aid)
        hist = {"mobile": [], "limit": [], "password": [], "payees": [], "balance": []}
        first_mobile = next((x.old_value for x in sc if x.field == "REGISTERED_MOBILE"), None)
        hist["mobile"].append({"t": None, "value": first_mobile or f"+91 ••••• {mask_tail(acct.registered_mobile_tok or '0000', 4)[-4:]}"})
        first_limit = next((x.old_value for x in sc if x.field == "TXN_LIMIT"), None)
        hist["limit"].append({"t": None, "value": rupees(int(first_limit)) if first_limit else rupees(acct.daily_limit_paise)})
        for x in sc:
            rec = {"t": iso(x.occurred_at), "ingested_at": iso(x.ingested_at), "by": x.actor_id, "auth": x.auth_method}
            if x.field == "REGISTERED_MOBILE":
                hist["mobile"].append({**rec, "value": x.new_value})
            elif x.field == "TXN_LIMIT":
                hist["limit"].append({**rec, "value": rupees(int(x.new_value))})
            elif x.field == "PASSWORD":
                hist["password"].append(rec)
        for b in db.execute(select(Beneficiary).where(Beneficiary.account_id == aid).order_by(Beneficiary.added_at)).scalars():
            hist["payees"].append({"t": iso(b.added_at), "payee": b.counterparty_account, "name": b.counterparty_name})
            if b.added_at >= t0 and (b.counterparty_account in nodes or aid == c.account_id):
                _acct_node(db, nodes, b.counterparty_account, "", mule)
                edge(f"payee:{b.id}", aid, b.counterparty_account, "PAYEE", b.added_at, "payee added")
        # balance trajectory through the window
        tx = db.execute(select(Txn).where(or_(Txn.from_account == aid, Txn.to_account == aid),
                                          Txn.occurred_at >= t0 - pd.Timedelta(days=1)).order_by(Txn.occurred_at)).scalars().all()
        bal = rupees(acct.balance_paise)
        for x in reversed(tx):
            bal += rupees(x.amount_paise) if x.from_account == aid else -rupees(x.amount_paise)
        start_bal = bal
        hist["balance"].append({"t": None, "value": round(start_bal, 2)})
        for x in tx:
            bal += -rupees(x.amount_paise) if x.from_account == aid else rupees(x.amount_paise)
            hist["balance"].append({"t": iso(x.occurred_at), "value": round(bal, 2)})
        state[aid] = hist

    # customer-side device used in takeover
    if victim and victim.customer_id:
        for s in db.execute(select(Sess).where(Sess.actor_id == victim.customer_id, Sess.started_at >= t0,
                                               Sess.started_at <= t1)).scalars():
            d = db.get(Device, s.device_id) if s.device_id else None
            if d is not None:
                new = abs((s.started_at - d.first_seen).total_seconds()) <= 600
                _node(nodes, d.id, "device", d.id, "never seen before" if new else "customer device",
                      role="new_device" if new else "device")
                edge(f"cdev:{s.id}", victim.id, d.id, "USED_DEVICE", s.started_at, f"{s.channel} from {s.geo_city}")

    # money edges among chain accounts
    tx = db.execute(select(Txn).where(Txn.from_account.in_(accounts), Txn.to_account.in_(accounts + ["X-ATM"]),
                                      Txn.occurred_at >= t0, Txn.occurred_at <= t1).order_by(Txn.occurred_at)).scalars().all()
    for x in tx:
        if x.to_account == "X-ATM":
            _acct_node(db, nodes, "X-ATM", "cashout", mule)
        edge(f"tx:{x.id}", x.from_account, x.to_account, "PAID", x.occurred_at, f"₹{rupees(x.amount_paise):,.0f}",
             amount=rupees(x.amount_paise), channel=x.channel, txn=x.id)

    # KYC approvals by the employee for chain accounts; ER matches
    if emp:
        for aid in accounts:
            acct = db.get(Account, aid)
            if acct and acct.kyc_approved_by == emp.id and aid != c.account_id:
                edge(f"kyc:{aid}", emp.id, aid, "APPROVED", acct.opened_at, "opened + approved KYC")
        for r in db.execute(select(Relationship).where(Relationship.src_id == emp.id, Relationship.rel_type == "ER_MATCH")).scalars():
            owned = [aid for aid in accounts if (db.get(Account, aid) or Account()).customer_id == r.dst_id]
            for aid in owned:
                edge(f"er:{r.id}:{aid}", emp.id, aid, "ER_MATCH", t0, "HR address match", score=r.confidence)

    for lk in links:
        events.append({"t": iso(lk.t), "lane": lk.lane, "title": lk.title, "detail": lk.detail, "code": lk.code,
                       "evidence_codes": lk.evidence_codes or []})
    events.sort(key=lambda e: e["t"])

    # what changed before the money moved (pre-transaction delta)
    first_pay = next((lk for lk in links if lk.code in ("E5", "H1", "D1", "F4")), links[-1])
    deltas = []
    n_accounts = db.execute(select(func.count()).select_from(Account).where(Account.kind != "EXTERNAL")).scalar() or 1
    for lk in links:
        if lk.t < first_pay.t and lk.t >= first_pay.t - pd.Timedelta(days=30):
            base = None
            if lk.code in ("E3", "E3′"):
                field = "REGISTERED_MOBILE" if "Mobile" in lk.title else "TXN_LIMIT"
                cnt = db.execute(select(func.count(func.distinct(StateChange.account_id))).where(StateChange.field == field)).scalar()
                base = f"{cnt} of {n_accounts:,} accounts had this change in 90 days"
            deltas.append({"code": lk.code, "t": iso(lk.t), "title": lk.title, "detail": lk.detail,
                           "before_payment_s": (first_pay.t - lk.t).total_seconds(), "base_rate": base})

    if as_of is not None:
        edges = [e for e in edges if e["t"] is None or e["t"] <= iso(as_of)]
    return {"alert_id": a.id, "chain_id": c.id, "window": {"start": iso(t0), "end": iso(t1)},
            "nodes": list(nodes.values()), "edges": edges, "events": events, "state": state, "deltas": deltas,
            "links": [link_dict(lk) for lk in links], "as_of": iso(as_of)}


# ── risk network: entity neighbourhoods ───────────────────────────────────


def _neighbours(db: Session, nid: str, mule: dict, flagged: set[str], limit: int = 14) -> tuple[list[dict], list[dict]]:
    nodes, edges = {}, []
    if nid.startswith("EMP-"):
        e = db.get(Employee, nid)
        if e is None:
            return [], []
        for acct in db.execute(select(Account).where(Account.kyc_approved_by == nid).order_by(Account.opened_at.desc())
                               .limit(limit)).scalars():
            _acct_node(db, nodes, acct.id, "", mule)
            edges.append({"id": f"kyc:{acct.id}", "source": nid, "target": acct.id, "kind": "APPROVED", "t": iso(acct.opened_at)})
        acc = db.execute(select(AccessEvent.account_id, func.count()).join(
            Explanation, Explanation.access_event_id == AccessEvent.id).where(
            AccessEvent.employee_id == nid, Explanation.verdict != "EXPLAINED", AccessEvent.account_id.isnot(None))
            .group_by(AccessEvent.account_id).limit(limit)).all()
        for aid, n in acc:
            _acct_node(db, nodes, aid, "", mule)
            edges.append({"id": f"acc:{nid}:{aid}", "source": nid, "target": aid, "kind": "ACCESSED", "count": n, "t": None})
        for r in db.execute(select(Relationship).where(Relationship.src_id == nid)).scalars():
            cu = db.get(Customer, r.dst_id)
            if cu:
                _node(nodes, cu.id, "customer", cu.id, cu.segment.title())
                edges.append({"id": f"rel:{r.id}", "source": nid, "target": cu.id, "kind": r.rel_type, "t": None})
    elif nid.startswith(("A-", "X-")):
        a = db.get(Account, nid)
        if a is None:
            return [], []
        if a.customer_id:
            cu = db.get(Customer, a.customer_id)
            _node(nodes, cu.id, "customer", cu.id, cu.segment.title())
            edges.append({"id": f"own:{cu.id}:{nid}", "source": cu.id, "target": nid, "kind": "OWNS", "t": None})
            for d in db.execute(select(Sess.device_id).where(Sess.actor_id == cu.id, Sess.device_id.isnot(None)).distinct()).scalars():
                _node(nodes, d, "device", d, "device")
                edges.append({"id": f"dev:{nid}:{d}", "source": nid, "target": d, "kind": "USED_DEVICE", "t": None})
        if a.kyc_approved_by:
            e = db.get(Employee, a.kyc_approved_by)
            if e:
                _node(nodes, e.id, "employee", e.id, e.pseudonym)
                edges.append({"id": f"kyc:{nid}", "source": e.id, "target": nid, "kind": "APPROVED", "t": iso(a.opened_at)})
        flows = db.execute(select(Txn.to_account, func.sum(Txn.amount_paise), func.count()).where(Txn.from_account == nid)
                           .group_by(Txn.to_account).order_by(func.sum(Txn.amount_paise).desc()).limit(limit)).all()
        for to, amt, n in flows:
            _acct_node(db, nodes, to, "", mule)
            edges.append({"id": f"out:{nid}:{to}", "source": nid, "target": to, "kind": "PAID", "amount": rupees(amt),
                          "count": n, "t": None})
        flows = db.execute(select(Txn.from_account, func.sum(Txn.amount_paise), func.count()).where(Txn.to_account == nid)
                           .group_by(Txn.from_account).order_by(func.sum(Txn.amount_paise).desc()).limit(limit)).all()
        for frm, amt, n in flows:
            _acct_node(db, nodes, frm, "", mule)
            edges.append({"id": f"in:{frm}:{nid}", "source": frm, "target": nid, "kind": "PAID", "amount": rupees(amt),
                          "count": n, "t": None})
    elif nid.startswith("C-"):
        for a in db.execute(select(Account).where(Account.customer_id == nid)).scalars():
            _acct_node(db, nodes, a.id, "", mule)
            edges.append({"id": f"own:{nid}:{a.id}", "source": nid, "target": a.id, "kind": "OWNS", "t": None})
        cu = db.get(Customer, nid)
        if cu and cu.phone_tok:
            for other in db.execute(select(Customer).where(Customer.phone_tok == cu.phone_tok, Customer.id != nid)).scalars():
                _node(nodes, other.id, "customer", other.id, other.segment.title())
                edges.append({"id": f"ph:{nid}:{other.id}", "source": nid, "target": other.id, "kind": "SHARED_PHONE", "t": None})
    else:  # device
        for actor in db.execute(select(Sess.actor_id, Sess.actor_type).where(Sess.device_id == nid).distinct()).all():
            kind = "employee" if actor[1] == "EMPLOYEE" else "customer"
            _node(nodes, actor[0], kind, actor[0], kind)
            edges.append({"id": f"use:{actor[0]}:{nid}", "source": actor[0], "target": nid, "kind": "USED_DEVICE", "t": None})
    for n in nodes.values():
        n["flagged"] = n["id"] in flagged
    return list(nodes.values()), edges


@router.get("/graph/neighborhood")
def neighborhood(p: CurrentUser, db: Annotated[Session, Depends(get_db)], entity: str,
                 hops: Annotated[int, Query(ge=1, le=2)] = 1) -> dict:
    mule = {m.entity_ref: m.p for m in db.execute(select(ModelPrediction).where(ModelPrediction.model == "M6")).scalars()}
    flagged = set()
    for refs, _priority in db.execute(select(Chain.entity_refs, Alert.priority).join(Alert, Alert.chain_id == Chain.id)
                               .where(Alert.priority.in_(["P1", "P2", "P3"]))).all():
        flagged |= set(refs or [])
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    root_kind = "employee" if entity.startswith("EMP-") else "account" if entity.startswith(("A-", "X-")) else \
        "customer" if entity.startswith("C-") else "device"
    nodes[entity] = {"id": entity, "kind": root_kind, "label": entity, "sub": "", "root": True, "flagged": entity in flagged}
    frontier = [entity]
    for h in range(hops):
        nxt = []
        for nid in frontier:
            ns, es = _neighbours(db, nid, mule, flagged, limit=14 if h == 0 else 6)
            for n in ns:
                if n["id"] not in nodes:
                    nodes[n["id"]] = n
                    nxt.append(n["id"])
            for e in es:
                edges[e["id"]] = e
        frontier = [x for x in nxt if not x.startswith("X-")][:12]
    return {"root": entity, "nodes": list(nodes.values()), "edges": list(edges.values())}


# ── money trail ────────────────────────────────────────────────────────────


@router.get("/trail")
def trail(p: CurrentUser, db: Annotated[Session, Depends(get_db)], account: str,
          direction: str = "forward", hops: Annotated[int, Query(ge=1, le=4)] = 3,
          start: datetime | None = None, end: datetime | None = None, min_amount: float = 10_000) -> dict:
    root = db.get(Account, account)
    if root is None:
        raise HTTPException(404, "Account not found")
    mule = {m.entity_ref: m.p for m in db.execute(select(ModelPrediction).where(ModelPrediction.model == "M6")).scalars()}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    _acct_node(db, nodes, account, "root", mule)
    q = deque([(account, start, 0)])
    seen = {account}
    while q:
        acct, since, depth = q.popleft()
        if depth >= hops:
            continue
        col_self, col_other = (Txn.from_account, Txn.to_account) if direction == "forward" else (Txn.to_account, Txn.from_account)
        conds = [col_self == acct, Txn.amount_paise >= int(min_amount * 100)]
        if since is not None and depth > 0:
            conds.append(Txn.occurred_at > since) if direction == "forward" else conds.append(Txn.occurred_at < since)
            conds.append(Txn.occurred_at <= since + pd.Timedelta(hours=72)) if direction == "forward" else \
                conds.append(Txn.occurred_at >= since - pd.Timedelta(hours=72))
        if depth == 0:
            if start is not None:
                conds.append(Txn.occurred_at >= start)
            if end is not None:
                conds.append(Txn.occurred_at <= end)
        rows = db.execute(select(Txn).where(and_(*conds)).order_by(Txn.occurred_at).limit(60)).scalars().all()
        for x in rows:
            other = x.to_account if direction == "forward" else x.from_account
            _acct_node(db, nodes, other, "", mule)
            edges.append({"id": x.id, "source": x.from_account, "target": x.to_account, "amount": rupees(x.amount_paise),
                          "t": iso(x.occurred_at), "channel": x.channel, "narration": x.narration, "depth": depth + 1})
            if other not in seen and not other.startswith("X-"):
                seen.add(other)
                q.append((other, x.occurred_at, depth + 1))
    # stats
    out_root = [e for e in edges if e["source"] == account]
    in_root = [e for e in edges if e["target"] == account]
    cash = sum(e["amount"] for e in edges if e["target"] == "X-ATM")
    first_in = min((e["t"] for e in edges if e["depth"] == 1), default=None)
    first_fwd = min((e["t"] for e in edges if e["depth"] == 2), default=None)
    ttl = (pd.Timestamp(first_fwd) - pd.Timestamp(first_in)).total_seconds() if first_in and first_fwd else None
    sent = sum(e["amount"] for e in out_root)
    fwd = sum(e["amount"] for e in edges if e["depth"] == 2)
    return {"root": account, "direction": direction, "nodes": list(nodes.values()), "edges": edges,
            "stats": {"fan_out": len({e["target"] for e in out_root}), "fan_in": len({e["source"] for e in in_root}),
                      "total_out": sent, "pass_through": round(fwd / sent, 3) if sent else None,
                      "cash_out": cash, "time_to_layering_s": ttl, "edges": len(edges)}}
