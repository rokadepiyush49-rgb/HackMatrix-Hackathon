"""The detection pipeline: Loom → Alibi → signals → Needle → models → Brief → persisted alerts.

    python -m app.cli detect
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pandas as pd
from psycopg.types.json import Jsonb
from sqlalchemy import delete, text

from app.alibi.engine import explain
from app.brief.builder import BriefResult, brief_for
from app.brief.context import BriefContext
from app.core import audit
from app.core.db import engine, session_scope
from app.lab.evaluate import evaluate_scenarios
from app.loom.frames import Frames, load_frames
from app.loom.models import (
    Alert,
    Chain,
    ChainLink,
    EmployeeBaseline,
    Evidence,
    Explanation,
    ModelPrediction,
    ScenarioRun,
    Signal,
)
from app.mend.controls import friction
from app.ml import baselines
from app.ml.features import mule_frame
from app.ml.models import score_mules
from app.needle import chains as N
from app.needle import er
from app.needle.detectors import graph as G
from app.needle.detectors import rules as R


def _log(msg: str, t0: float) -> None:
    print(f"  {msg:<48} {time.perf_counter() - t0:5.1f}s")


def compute(f: Frames, log=True) -> dict:
    """Run every stage in memory and return the results (no database writes)."""
    t0 = time.perf_counter()
    out: dict = {"frames": f}
    ex = explain(f)
    out["explanations"] = ex
    log and _log(f"Alibi: {len(ex):,} accesses ({(ex['verdict'] == 'EXPLAINED').mean():.1%} explained)", t0)

    clusters, cluster_ev = er.customer_clusters(f)
    links = er.employee_customer_links(f)
    out.update(clusters=clusters, cluster_evidence=cluster_ev, er_links=links)
    log and _log(f"Entity resolution: {len(links)} employee↔customer links", t0)

    rhythm = baselines.fit_rhythm(f)
    sess = baselines.session_surprise(f, rhythm)
    nav_model = baselines.fit_navigation(f)
    nav = baselines.session_navigation(f, nav_model)
    out.update(rhythm=rhythm, session_rhythm=sess, session_nav=nav)
    log and _log("Baselines: access rhythm (M1) + navigation (M2)", t0)

    sig: list[dict] = []
    sig += R.r1_structuring(f, clusters)
    sig += R.r2_limit_hugging(f)
    sig += R.r3_dormant(f)
    sig += R.r4_contact_payout(f)
    sig += R.r5_r6_from_alibi(f, ex)
    sig += R.r7_override(f)
    sig += R.r8_sod(f)
    sig += R.r9_expired(f)
    sig += R.r10_presence(f)
    g1 = G.g1_temporal_cycles(f)
    g2 = G.g2_pass_through(f)
    sig += g1 + g2 + G.g3_fan(f)
    g4 = G.g4_mule_factory(f, {s["payload"]["account"] for s in g2})
    sig += g4 + G.g5_shared(f, links)
    for s in sess[(sess["share"] < 0.004) & sess["late"]].itertuples(index=False):
        sig.append(R.signal("M1", [s.actor_id], [s.id], s.started_at, s.started_at, 0.7,
                            f"Session at {s.started_at:%a %H:%M} is rare for this person and role "
                            f"(share {s.share:.4f}; {int(s.late_prior)} prior late sessions)", session=s.id))
    for s in nav[nav["percentile"] < 0.005].itertuples(index=False):
        sig.append(R.signal("M2", [s.employee_id], [s.session_id], None, None, 0.6,
                            f"Navigation in the bottom {s.percentile:.1%} for the role", session=s.session_id,
                            rare=s.rare))
    out["signals"] = sig
    log and _log(f"Signals: {len(sig):,} from {len({s['detector'] for s in sig})} detectors", t0)

    ix = N.Index(f, ex)
    ins = N.insider_chains(ix)
    ext = N.external_chains(ix, {d.account_id for d in ins})
    circ = N.circular_chains(ix, g1)
    st = N.structuring_chains(ix, [s for s in sig if s["detector"] == "R1"])
    mf = N.mule_factory_chains(ix, g4, ins)
    drafts = ins + ext + circ + st + mf
    out.update(index=ix, drafts=drafts)
    log and _log(f"Needle: {len(drafts)} chains ({len(ins)} insider, {len(ext)} takeover, "
                 f"{len(circ)} circular, {len(st)} structuring, {len(mf)} mule)", t0)

    mf_frame = mule_frame(f)
    mules = score_mules(mf_frame)
    out["mule_scores"] = mules
    ctx = BriefContext(f, ix, sig, links, clusters, cluster_ev, sess, nav, mules)
    out["context"] = ctx
    briefs = [brief_for(ctx, d) for d in drafts]
    out["briefs"] = briefs
    counts = pd.Series([b.priority for b in briefs]).value_counts().to_dict()
    log and _log(f"Brief: {counts}", t0)
    return out


# ── persistence ────────────────────────────────────────────────────────────


REASONING_TABLES = [Evidence, Alert, ChainLink, Chain, Signal, Explanation, EmployeeBaseline, ModelPrediction]


JSONB_COLS = {
    "explanation": {"matches", "checked"}, "signal": {"payload"},
    "employee_baseline": {"hour_rates", "peer_hour_rates"}, "relationship": {"detail"},
    "model_prediction": {"contributions"}, "chain": {"contributions", "features"},
    "chain_link": {"alibi"}, "alert": {"dims", "argument"}, "evidence": {"facts"},
}


def _copy(table: str, cols: list[str], rows: list[list]) -> None:
    """COPY rows in; JSONB columns are declared explicitly so [] never becomes a Postgres array."""
    if not rows:
        return
    jcols = {i for i, c in enumerate(cols) if c in JSONB_COLS.get(table, set())}
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row([Jsonb(v) if i in jcols and v is not None else v for i, v in enumerate(r)])
        raw.commit()
    finally:
        raw.close()


def persist(res: dict) -> dict:
    f: Frames = res["frames"]
    with engine.begin() as conn:
        for m in REASONING_TABLES:
            conn.execute(delete(m.__table__))
        conn.execute(text("DELETE FROM relationship WHERE source <> 'DECLARED'"))
        conn.execute(text("DELETE FROM case_note; DELETE FROM evidence_pack; DELETE FROM case_file;"))

    ex = res["explanations"]
    _copy("explanation", ["access_event_id", "employee_id", "verdict", "purpose_ok", "timing_ok", "matches",
                          "checked", "occurred_at"],
          [[r.access_event_id, r.employee_id, r.verdict, bool(r.purpose_ok), bool(r.timing_ok),
            _json(r.matches), _json(r.checked), r.occurred_at] for r in ex.itertuples(index=False)])

    sig_rows = []
    for i, s in enumerate(res["signals"]):
        sig_rows.append([f"SG-{i + 1:06d}", s["detector"], s["family"], s["version"], s["entity_refs"],
                         s["event_refs"][:200], s["window_start"] or f.window_start, s["window_end"] or f.window_end,
                         s["strength"], s["summary"], _json(s["payload"])])
    _copy("signal", ["id", "detector", "family", "version", "entity_refs", "event_refs", "window_start",
                     "window_end", "strength", "summary", "payload"], sig_rows)

    # baselines
    rhythm, sess, ex_df = res["rhythm"], res["session_rhythm"], res["explanations"]
    cov = ex_df.groupby("employee_id")["verdict"].apply(lambda v: (v == "EXPLAINED").mean())
    acc = f.account
    recent = acc[acc["opened_at"] >= f.window_end - pd.Timedelta(days=60)].groupby("kyc_approved_by").size()
    hist = acc[(acc["opened_at"] < f.window_start) & (acc["opened_at"] >= f.window_start - pd.Timedelta(days=365))
               ].groupby("kyc_approved_by").size()
    late = sess.groupby("actor_id").agg(n=("id", "count"), late=("late", "sum"))
    peer_late = sess.groupby("role")["late"].mean()
    base_rows = []
    for emp, role in rhythm.role.items():
        base_rows.append([emp, role, int(late["n"].get(emp, 0)), int(late["late"].get(emp, 0)),
                          float(peer_late.get(role, 0.0)), _json([round(x, 5) for x in rhythm.shrunk(emp)]),
                          _json([round(x, 5) for x in rhythm.peer_share[role]]), float(cov.get(emp, 1.0)),
                          int(recent.get(emp, 0)), round(float(hist.get(emp, 0)) / 6.0, 2)])
    _copy("employee_baseline", ["employee_id", "peer_group", "sessions_90d", "after20_sessions",
                                "peer_after20_share", "hour_rates", "peer_hour_rates", "alibi_coverage",
                                "accounts_approved_60d", "approvals_baseline_60d"], base_rows)

    # ER links as relationships
    rel_rows = [[f"REL-ER-{i + 1:04d}", "EMPLOYEE", lk["employee_id"], "CUSTOMER", lk["customer_id"], "ER_MATCH",
                 "ER", lk["score"], _json(lk), f.window_start] for i, lk in enumerate(res["er_links"])]
    _copy("relationship", ["id", "src_type", "src_id", "dst_type", "dst_id", "rel_type", "source", "confidence",
                           "detail", "valid_from"], rel_rows)

    # mule predictions
    now = datetime.now(UTC)
    ms = res["mule_scores"]
    _copy("model_prediction", ["id", "model", "version", "entity_ref", "p", "contributions", "created_at"],
          [[f"M6:{a}", "M6", "1.0", a, float(r.p), _json(r.contributions[:6]), now]
           for a, r in ms.iterrows() if r.p >= 0.05])

    # chains, links, alerts, evidence
    briefs: list[BriefResult] = sorted(res["briefs"], key=lambda b: (b.draft.first_t, b.draft.kind, b.draft.root_ref))
    chain_rows, link_rows, alert_rows, ev_rows = [], [], [], []
    per_day: dict[str, int] = {}
    ids = {}
    for i, b in enumerate(briefs):
        d = b.draft
        cid = f"CH-{4401 + i}"
        day = d.last_t.strftime("%m%d")
        per_day[day] = per_day.get(day, 0) + 1
        aid = f"AL-{day}-{per_day[day]:03d}"
        ids[id(b)] = (cid, aid)
        ev_by_link: dict[str, list[str]] = {}
        for e in b.evidence:
            for lc in e.link_codes:
                ev_by_link.setdefault(lc, []).append(e.code)
        chain_rows.append([cid, d.kind, d.root_ref, d.employee_id, d.account_id, d.first_t, d.last_t, d.latency_s,
                           int(round(d.amount_at_risk * 100)), b.classifier["p"] if b.classifier else None,
                           _json(b.classifier["contributions"] if b.classifier else []), _json(_clean(d.features)),
                           sorted(str(x) for x in d.entities)])
        for j, lk in enumerate(d.links):
            link_rows.append([f"{cid}:{j + 1:02d}", cid, j + 1, lk.code, lk.event_type, str(lk.event_id), lk.t,
                              lk.title, lk.detail, lk.lane,
                              int(round(lk.amount * 100)) if lk.amount is not None else None,
                              ev_by_link.get(lk.code, []), _json(_alibi_public(lk.alibi))])
        state = {"EXPLAINED": "SUPPRESSED", "WATCH": "WATCH"}.get(b.priority, "OPEN")
        arg = dict(b.argument)
        arg["dims_rule"] = b.lattice_rule
        alert_rows.append([aid, cid, b.typology, b.claim, b.priority, b.lattice_rule,
                           _json([dm.as_dict() for dm in b.dims]), _json(_clean(arg)), b.recoverable, state, None,
                           d.last_t + pd.Timedelta(minutes=2), None])
        for e in b.evidence:
            ev_rows.append([f"{aid}:{e.code}", aid, e.code, e.kind, e.summary, e.source_system, e.source_table,
                            str(e.source_ref), e.reliability, e.credibility, e.observed_at,
                            e.ingested_at if e.ingested_at is not None else e.observed_at,
                            [str(x) for x in e.entities if x], _json(_clean(e.facts)), e.supports, e.rebuts, e.sha256])
    _copy("chain", ["id", "kind", "root_ref", "employee_id", "account_id", "first_t", "last_t", "latency_s",
                    "amount_at_risk_paise", "classifier_p", "contributions", "features", "entity_refs"], chain_rows)
    _copy("chain_link", ["id", "chain_id", "seq", "code", "event_type", "event_id", "t", "title", "detail", "lane",
                         "amount_paise", "evidence_codes", "alibi"], link_rows)
    _copy("alert", ["id", "chain_id", "typology", "claim", "priority", "lattice_rule", "dims", "argument",
                    "recoverable", "state", "assignee", "created_at", "scenario_tag"], alert_rows)
    _copy("evidence", ["id", "alert_id", "code", "kind", "summary", "source_system", "source_table", "source_ref",
                       "reliability", "credibility", "observed_at", "ingested_at", "entities", "facts", "supports",
                       "rebuts", "sha256"], ev_rows)
    return {"chains": len(chain_rows), "alerts": len(alert_rows), "evidence": len(ev_rows)}


def _alibi_public(card: dict | None) -> dict | None:
    if not card:
        return None
    return {k: card[k] for k in ("verdict", "purpose_ok", "timing_ok", "reasons_found", "checked")}


def _clean(obj):
    """Make nested values JSON-safe (timestamps → ISO strings, numpy → Python)."""
    import numpy as np

    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, float) and obj != obj:
        return None
    return obj


def _json(obj):
    return _clean(obj)


def run_pipeline() -> dict:
    t0 = time.perf_counter()
    print("▸ Loading Loom …")
    f = load_frames()
    print(f"  {len(f.txn):,} transactions · {len(f.access_event):,} staff accesses")
    res = compute(f)
    stats = persist(res)
    report = evaluate_scenarios(res)
    queued_refs = {r for b in res["briefs"] if b.priority in ("P1", "P2", "P3")
                   for lk in b.draft.links for r in [*lk.refs, str(lk.event_id)]}
    report["controls_friction"] = friction(f, queued_refs, res["explanations"])
    with session_scope() as db:
        db.add(ScenarioRun(id=f"RUN-{datetime.now(UTC):%Y%m%d%H%M%S}", started_at=datetime.now(UTC),
                           finished_at=datetime.now(UTC), results=_clean(report)))
        audit.append(db, "system", "pipeline.run", payload={**stats, "scenarios_passed": report["summary"]["passed"],
                                                            "scenarios_total": report["summary"]["total"]})
    s = report["summary"]
    print(f"✓ Pipeline done in {time.perf_counter() - t0:.1f}s · {stats['alerts']} alerts · "
          f"scenario checks {s['passed']}/{s['total']} passed")
    for r in report["scenarios"]:
        mark = "✓" if r["passed"] else "✗"
        print(f"   {mark} {r['key']:<16} {r['outcome']}")
    return {**stats, "report": report}
