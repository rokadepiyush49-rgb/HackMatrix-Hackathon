"""The detection pipeline: Loom → Alibi → signals → Needle → models → Brief → persisted alerts.

    python -m app.cli detect
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from psycopg.types.json import Jsonb

from app.alibi.engine import explain
from app.brief.builder import BriefResult, brief_for
from app.brief.context import BriefContext
from app.core import audit
from app.core.db import engine, session_scope
from app.lab.evaluate import evaluate_scenarios
from app.loom.frames import Frames, load_frames
from app.loom.models import ScenarioRun
from app.mend.controls import friction
from app.ml import baselines
from app.ml.case_features import case_rows
from app.ml.cases import build_cases
from app.ml.features import mule_frame
from app.ml.models import score_cases, score_mules
from app.needle import chains as N
from app.needle import er
from app.needle.detectors import graph as G
from app.needle.detectors import rules as R


def _log(msg: str, t0: float) -> None:
    print(f"  {msg:<48} {time.perf_counter() - t0:5.1f}s")


Progress = Callable[[str, str | None], None]


def compute(f: Frames, log=True, progress: Progress | None = None, models: bool = True) -> dict:
    """Run every stage in memory and return the results (no database writes).

    `progress(stage, None)` is called as a stage starts and `progress(stage, summary)` as it ends.
    `models=False` switches every learned input off (M5, M6, M7): the lattice then runs on rules alone,
    which is the RB-2 baseline, and the result does not depend on any trained artifact.
    """
    t0 = time.perf_counter()

    def begin(stage: str) -> None:
        if progress:
            progress(stage, None)

    def done(stage: str, msg: str) -> None:
        if log:
            _log(msg, t0)
        if progress:
            progress(stage, msg)

    out: dict = {"frames": f}
    begin("alibi")
    ex = explain(f)
    out["explanations"] = ex
    done("alibi", f"Alibi: {len(ex):,} accesses ({(ex['verdict'] == 'EXPLAINED').mean():.1%} explained)")

    begin("er")
    clusters, cluster_ev = er.customer_clusters(f)
    links = er.employee_customer_links(f)
    out.update(clusters=clusters, cluster_evidence=cluster_ev, er_links=links)
    done("er", f"Entity resolution: {len(links)} employee↔customer links")

    begin("baselines")
    rhythm = baselines.fit_rhythm(f)
    sess = baselines.session_surprise(f, rhythm)
    nav_model = baselines.fit_navigation(f)
    nav = baselines.session_navigation(f, nav_model)
    out.update(rhythm=rhythm, session_rhythm=sess, session_nav=nav)
    done("baselines", "Baselines: access rhythm (M1) + navigation (M2)")

    begin("signals")
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
    done("signals", f"Signals: {len(sig):,} from {len({s['detector'] for s in sig})} detectors")

    begin("needle")
    ix = N.Index(f, ex)
    ins = N.insider_chains(ix)
    ext = N.external_chains(ix, {d.account_id for d in ins})
    circ = N.circular_chains(ix, g1)
    st = N.structuring_chains(ix, [s for s in sig if s["detector"] == "R1"])
    mf = N.mule_factory_chains(ix, g4, ins)
    drafts = ins + ext + circ + st + mf
    out.update(index=ix, drafts=drafts)
    done("needle", f"Needle: {len(drafts)} chains ({len(ins)} insider, {len(ext)} takeover, "
                   f"{len(circ)} circular, {len(st)} structuring, {len(mf)} mule)")

    begin("brief")
    mf_frame = mule_frame(f)
    mules = score_mules(mf_frame) if models else pd.DataFrame(columns=["p", "contributions"])
    out.update(mule_frame=mf_frame, mule_scores=mules)
    ctx = BriefContext(f, ix, sig, links, clusters, cluster_ev, sess, nav, mules, chain_model=models)
    out["context"] = ctx
    briefs = [brief_for(ctx, d) for d in drafts]
    out["briefs"] = briefs
    cases = build_cases(sig, drafts, (f.window_start, f.window_end))
    rows = case_rows(cases, f, ex, mf_frame)
    scores = score_cases(rows) if models else {}
    out.update(cases=cases, case_rows=rows, case_scores=scores)
    counts = pd.Series([b.priority for b in briefs]).value_counts().to_dict()
    done("brief", "Brief: " + ", ".join(f"{counts[k]} {k}" for k in ("P1", "P2", "P3", "WATCH", "EXPLAINED")
                                        if k in counts)
         + f" · {len(cases)} connected cases" + (" ranked by M7" if scores else ""))
    return out


# ── persistence ────────────────────────────────────────────────────────────


JSONB_COLS = {
    "explanation": {"matches", "checked"}, "signal": {"payload"},
    "employee_baseline": {"hour_rates", "peer_hour_rates"}, "relationship": {"detail"},
    "model_prediction": {"contributions"}, "chain": {"contributions", "features"},
    "chain_link": {"alibi"}, "alert": {"dims", "argument"}, "evidence": {"facts"},
}
# Alert states detection sets. Any other state (INVESTIGATING, a decision…) was set by a person and is kept.
MACHINE_STATES = ["OPEN", "WATCH", "SUPPRESSED"]


def _copy(cur, table: str, cols: list[str], rows: list[list]) -> None:
    """COPY rows in; JSONB columns are declared explicitly so [] never becomes a Postgres array."""
    if not rows:
        return
    jcols = {i for i, c in enumerate(cols) if c in JSONB_COLS.get(table, set())}
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row([Jsonb(v) if i in jcols and v is not None else v for i, v in enumerate(r)])


@dataclass(frozen=True)
class Known:
    chain_id: str
    alert_id: str | None
    has_case: bool


def assign_ids(briefs: list[BriefResult], known: dict[tuple[str, str], Known]) -> list[tuple[str, str]]:
    """Stable identity: a chain keeps its ID, and its alert's, for as long as detection finds it.

    Chains are keyed by (kind, root_ref). New chains continue the CH- sequence and new alerts their
    day's AL-MMDD- sequence, so on an empty database this is the original numbering.
    """
    next_ch = max((int(k.chain_id.removeprefix("CH-")) for k in known.values()), default=4400) + 1
    per_day: dict[str, int] = {}
    for k in known.values():
        if k.alert_id:
            _, day, n = k.alert_id.split("-")
            per_day[day] = max(per_day.get(day, 0), int(n))
    out: list[tuple[str, str]] = []
    claimed: set[tuple[str, str]] = set()
    for b in briefs:
        key = (b.draft.kind, b.draft.root_ref)
        prev = None if key in claimed else known.get(key)
        claimed.add(key)
        if prev and prev.alert_id:
            out.append((prev.chain_id, prev.alert_id))
            continue
        if prev:
            cid = prev.chain_id
        else:
            cid, next_ch = f"CH-{next_ch}", next_ch + 1
        day = b.draft.last_t.strftime("%m%d")
        per_day[day] = per_day.get(day, 0) + 1
        out.append((cid, f"AL-{day}-{per_day[day]:03d}"))
    return out


def persist(res: dict) -> dict:
    """Replace the reasoning layer in one transaction, keeping identities, triage state and cases.

    Readers see the previous run until this commits. A chain detection no longer finds is kept as it
    was if a case hangs off it: a re-run never deletes an investigator's work.
    """
    f: Frames = res["frames"]
    briefs: list[BriefResult] = sorted(res["briefs"], key=lambda b: (b.draft.first_t, b.draft.kind, b.draft.root_ref))
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("SELECT c.kind, c.root_ref, c.id, a.id, EXISTS (SELECT 1 FROM case_file cf WHERE cf.alert_id = a.id) "
                    "FROM chain c LEFT JOIN alert a ON a.chain_id = c.id")
        known = {(kind, root): Known(cid, aid, bool(has_case)) for kind, root, cid, aid, has_case in cur.fetchall()}
        ids = assign_ids(briefs, known)
        found = {(b.draft.kind, b.draft.root_ref) for b in briefs}
        keep = [k.chain_id for key, k in known.items() if key not in found and k.has_case]

        cur.execute("CREATE TEMP TABLE keep_chain (id text) ON COMMIT DROP")
        cur.execute("INSERT INTO keep_chain SELECT unnest(%s::text[])", [keep])
        cur.execute("CREATE TEMP TABLE prior_alert ON COMMIT DROP AS SELECT id, state, assignee, created_at FROM alert")
        cur.execute("CREATE TEMP TABLE prior_case ON COMMIT DROP AS SELECT * FROM case_file WHERE alert_id IN "
                    "(SELECT id FROM alert WHERE chain_id NOT IN (SELECT id FROM keep_chain))")
        cur.execute("CREATE TEMP TABLE prior_note ON COMMIT DROP AS SELECT * FROM case_note "
                    "WHERE case_id IN (SELECT id FROM prior_case)")
        cur.execute("CREATE TEMP TABLE prior_pack ON COMMIT DROP AS SELECT * FROM evidence_pack "
                    "WHERE case_id IN (SELECT id FROM prior_case)")
        # cascades to chain links, alerts, evidence and (stashed above) cases, notes and packs
        cur.execute("DELETE FROM chain WHERE id NOT IN (SELECT id FROM keep_chain)")
        for table in ("signal", "explanation", "employee_baseline", "model_prediction"):
            cur.execute(f"DELETE FROM {table}")
        cur.execute("DELETE FROM relationship WHERE source <> 'DECLARED'")

        _write(cur, res, f, briefs, ids)

        cur.execute("INSERT INTO case_file SELECT * FROM prior_case WHERE alert_id IN (SELECT id FROM alert)")
        cur.execute("INSERT INTO case_note SELECT * FROM prior_note WHERE case_id IN (SELECT id FROM case_file)")
        cur.execute("INSERT INTO evidence_pack SELECT * FROM prior_pack WHERE case_id IN (SELECT id FROM case_file)")
        cur.execute("UPDATE alert a SET created_at = p.created_at, assignee = COALESCE(p.assignee, a.assignee), "
                    "state = CASE WHEN p.state = ANY(%s) THEN a.state ELSE p.state END "
                    "FROM prior_alert p WHERE a.id = p.id", [MACHINE_STATES])
        cur.execute("SELECT count(*) FROM alert WHERE id NOT IN (SELECT id FROM prior_alert)")
        new_alerts = cur.fetchone()[0]
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return {"chains": len(briefs), "alerts": len(briefs), "new_alerts": new_alerts, "kept_for_cases": len(keep),
            "evidence": sum(len(b.evidence) for b in briefs)}


def _write(cur, res: dict, f: Frames, briefs: list[BriefResult], ids: list[tuple[str, str]]) -> None:
    ex = res["explanations"]
    _copy(cur, "explanation", ["access_event_id", "employee_id", "verdict", "purpose_ok", "timing_ok", "matches",
                               "checked", "occurred_at"],
          [[r.access_event_id, r.employee_id, r.verdict, bool(r.purpose_ok), bool(r.timing_ok),
            _json(r.matches), _json(r.checked), r.occurred_at] for r in ex.itertuples(index=False)])

    sig_rows = []
    for i, s in enumerate(res["signals"]):
        sig_rows.append([f"SG-{i + 1:06d}", s["detector"], s["family"], s["version"], s["entity_refs"],
                         s["event_refs"][:200], s["window_start"] or f.window_start, s["window_end"] or f.window_end,
                         s["strength"], s["summary"], _json(s["payload"])])
    _copy(cur, "signal", ["id", "detector", "family", "version", "entity_refs", "event_refs", "window_start",
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
    _copy(cur, "employee_baseline", ["employee_id", "peer_group", "sessions_90d", "after20_sessions",
                                     "peer_after20_share", "hour_rates", "peer_hour_rates", "alibi_coverage",
                                     "accounts_approved_60d", "approvals_baseline_60d"], base_rows)

    # ER links as relationships
    rel_rows = [[f"REL-ER-{i + 1:04d}", "EMPLOYEE", lk["employee_id"], "CUSTOMER", lk["customer_id"], "ER_MATCH",
                 "ER", lk["score"], _json(lk), f.window_start] for i, lk in enumerate(res["er_links"])]
    _copy(cur, "relationship", ["id", "src_type", "src_id", "dst_type", "dst_id", "rel_type", "source", "confidence",
                                "detail", "valid_from"], rel_rows)

    # mule predictions, and M7 suspicion scores for connected cases
    now = datetime.now(UTC)
    ms = res["mule_scores"]
    cases, scores = res.get("cases", []), res.get("case_scores", {})
    _copy(cur, "model_prediction", ["id", "model", "version", "entity_ref", "p", "contributions", "created_at"],
          [[f"M6:{a}", "M6", "1.0", a, float(r.p), _json(r.contributions[:6]), now]
           for a, r in ms.iterrows() if r.p >= 0.05]
          + [[f"M7:{c.key}", "M7", "1.0", c.key, scores[c.key].p, _json(scores[c.key].contributions[:6]), now]
             for c in cases if c.key in scores and (c.chains or scores[c.key].p >= 0.05)])
    case_of = {(d.kind, d.root_ref): c for c in cases for d in c.chains}

    # chains, links, alerts, evidence
    chain_rows, link_rows, alert_rows, ev_rows = [], [], [], []
    for b, (cid, aid) in zip(briefs, ids, strict=True):
        d = b.draft
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
        arg["case"] = _case_card(case_of.get((d.kind, d.root_ref)), scores)
        alert_rows.append([aid, cid, b.typology, b.claim, b.priority, b.lattice_rule,
                           _json([dm.as_dict() for dm in b.dims]), _json(_clean(arg)), b.recoverable, state, None,
                           d.last_t + pd.Timedelta(minutes=2), None])
        for e in b.evidence:
            ev_rows.append([f"{aid}:{e.code}", aid, e.code, e.kind, e.summary, e.source_system, e.source_table,
                            str(e.source_ref), e.reliability, e.credibility, e.observed_at,
                            e.ingested_at if e.ingested_at is not None else e.observed_at,
                            [str(x) for x in e.entities if x], _json(_clean(e.facts)), e.supports, e.rebuts, e.sha256])
    _copy(cur, "chain", ["id", "kind", "root_ref", "employee_id", "account_id", "first_t", "last_t", "latency_s",
                         "amount_at_risk_paise", "classifier_p", "contributions", "features", "entity_refs"], chain_rows)
    _copy(cur, "chain_link", ["id", "chain_id", "seq", "code", "event_type", "event_id", "t", "title", "detail", "lane",
                              "amount_paise", "evidence_codes", "alibi"], link_rows)
    _copy(cur, "alert", ["id", "chain_id", "typology", "claim", "priority", "lattice_rule", "dims", "argument",
                         "recoverable", "state", "assignee", "created_at", "scenario_tag"], alert_rows)
    _copy(cur, "evidence", ["id", "alert_id", "code", "kind", "summary", "source_system", "source_table", "source_ref",
                            "reliability", "credibility", "observed_at", "ingested_at", "entities", "facts", "supports",
                            "rebuts", "sha256"], ev_rows)


def _case_card(c, scores: dict) -> dict | None:
    """The connected case an alert belongs to, and M7's suspicion score for it (None when M7 is offline)."""
    if c is None:
        return None
    sc = scores.get(c.key)
    return {"key": c.key, "chains": len(c.chains), "accounts": sum(e.startswith("A-") for e in c.entities),
            "linked_cases": sorted(c.linked_cases)[:12], "detectors": sorted(c.detectors),
            "suspicion": None if sc is None else {
                "model": "M7 connected-case prioritiser", "p": sc.p, "above_threshold": sc.alert,
                "label": "Suspicion score (model) — a reason to look first, not a finding",
                "contributions": sc.contributions[:6]}}


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


def record_run(res: dict, stats: dict) -> dict:
    """Grade the run against ground truth, measure control friction, and log it (ScenarioRun + audit)."""
    f: Frames = res["frames"]
    report = evaluate_scenarios(res)
    queued_refs = {r for b in res["briefs"] if b.priority in ("P1", "P2", "P3")
                   for lk in b.draft.links for r in [*lk.refs, str(lk.event_id)]}
    report["controls_friction"] = friction(f, queued_refs, res["explanations"])
    with session_scope() as db:
        db.add(ScenarioRun(id=f"RUN-{datetime.now(UTC):%Y%m%d%H%M%S}", started_at=datetime.now(UTC),
                           finished_at=datetime.now(UTC), results=_clean(report)))
        audit.append(db, "system", "pipeline.run", payload={**stats, "scenarios_passed": report["summary"]["passed"],
                                                            "scenarios_total": report["summary"]["total"]})
    return report


def run_pipeline() -> dict:
    t0 = time.perf_counter()
    print("▸ Loading Loom …")
    f = load_frames()
    print(f"  {len(f.txn):,} transactions · {len(f.access_event):,} staff accesses")
    res = compute(f)
    stats = persist(res)
    report = record_run(res, stats)
    s = report["summary"]
    print(f"✓ Pipeline done in {time.perf_counter() - t0:.1f}s · {stats['alerts']} alerts ({stats['new_alerts']} new) · "
          f"scenario checks {s['passed']}/{s['total']} passed")
    for r in report["scenarios"]:
        mark = "✓" if r["passed"] else "✗"
        print(f"   {mark} {r['key']:<16} {r['outcome']}")
    return {**stats, "report": report}
