"""Scenario Lab: grade every scenario (suspicious and legitimate twin) against ground truth.

Every number here is computed from the synthetic world and is labelled as such in the UI.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from app.core.db import session_scope
from app.loom.models import ScenarioLabel

QUEUED = {"P1", "P2", "P3"}
KIND = {"INSIDER_ATO": "INSIDER_ATO", "EXTERNAL_ATO": "EXTERNAL_ATO", "CIRCULAR_FLOW": "CIRCULAR",
        "STRUCTURING": "STRUCTURING", "MULE_FACTORY": "MULE_FACTORY"}


def _labels() -> list[dict]:
    with session_scope() as db:
        rows = db.execute(select(ScenarioLabel)).scalars().all()
        return [{c.name: getattr(r, c.name) for c in ScenarioLabel.__table__.columns} for r in rows]


def _why_quiet(res: dict, lab: dict) -> str:
    ex = res["explanations"].set_index("access_event_id")
    sig = res["signals"]
    ents = set(lab["entities"])
    fired = Counter(s["detector"] for s in sig if ents & set(s["entity_refs"]))
    sid = lab["scenario"]
    if sid == "S4":
        acc = [e for e in lab["events"] if e in ex.index]
        if acc:
            r = ex.loc[acc[-1]]
            reasons = [f"{c['template'].title()} ({c.get('ref', '✓')})" for c in r["checked"] if c["ok"]]
            return f"Alibi {r['verdict'].lower()}: {', '.join(reasons)} — no chain is rooted in an explained access"
    if sid == "S2":
        return "Loop detected (G1) but it repeats monthly with invoices between long-standing payees → explained"
    if sid == "S3":
        return "Near-threshold deposits go to one account at one branch on a months-long stable pattern → R1 does not fire"
    if sid == "S5":
        return "Relationship is declared in the conflict register and no chain involves it"
    if sid == "S6":
        return "New device, but no password reset, no new payees → Needle builds no chain"
    if sid == "S7":
        return ("Fan-in detected (G3) but no shared identifiers, no presence-less openings and no cash-out → "
                "no mule factory")
    signals = ", ".join(f"{k}×{v}" for k, v in fired.most_common(4)) or "none"
    return f"No queued alert; signals on these entities: {signals}"


def evaluate_scenarios(res: dict, labels: list[dict] | None = None) -> dict:
    """Score every scenario against its ground-truth label. Labels default to the database copy."""
    briefs = res["briefs"]
    labels = _labels() if labels is None else labels
    alerts = [{"kind": b.draft.kind, "priority": b.priority, "entities": {str(x) for x in b.draft.entities},
               "claim": b.claim, "root": b.draft.root_ref} for b in briefs]
    suspicious_entities = set().union(*[set(lab["entities"]) for lab in labels if lab["variant"] == "suspicious"] or [set()])
    out = []
    for lab in sorted(labels, key=lambda x: (x["scenario"], x["variant"] != "suspicious")):
        exp = lab["expected"] or {}
        ents = set(lab["entities"])
        if lab["scenario"] in ("S1",):
            fps = [a for a in alerts if a["priority"] in ("P1", "P2") and not (a["entities"] & suspicious_entities)]
            passed = not fps
            out.append({"key": lab["key"], "scenario": lab["scenario"], "variant": lab["variant"],
                        "title": lab["title"], "passed": passed,
                        "outcome": "no P1/P2 alerts on baseline entities" if passed else f"{len(fps)} P1/P2 false positive(s)",
                        "expected": exp, "matched": [], "differing_fact": lab["differing_fact"],
                        "description": lab["description"]})
            continue
        matched = [a for a in alerts if a["entities"] & ents]
        if lab["variant"] == "suspicious":
            kind = KIND.get(exp.get("kind", ""), exp.get("kind"))
            ok = [a for a in matched if a["kind"] == kind and a["priority"] in set(exp.get("priority_in", QUEUED))]
            best = sorted(matched, key=lambda a: ["P1", "P2", "P3", "WATCH", "EXPLAINED"].index(a["priority"]))
            passed = bool(ok)
            outcome = (f"{ok[0]['kind'].replace('_', ' ').title()} alert at {ok[0]['priority']}" if ok else
                       f"missed (best match: {best[0]['kind']} {best[0]['priority']})" if best else "missed — no chain")
        else:
            loud = [a for a in matched if a["priority"] in ("P1", "P2")]
            passed = not loud
            outcome = ("quiet — " + _why_quiet(res, lab)) if passed else f"false positive at {loud[0]['priority']}"
        out.append({"key": lab["key"], "scenario": lab["scenario"], "variant": lab["variant"], "title": lab["title"],
                    "passed": passed, "outcome": outcome, "expected": exp,
                    "matched": [{"kind": a["kind"], "priority": a["priority"]} for a in matched][:5],
                    "differing_fact": lab["differing_fact"], "description": lab["description"]})

    ex = res["explanations"]
    pri = Counter(b.priority for b in briefs)
    sig = res["signals"]
    by_det = Counter(s["detector"] for s in sig)
    on_scenario = Counter(s["detector"] for s in sig if set(s["entity_refs"]) & suspicious_entities)
    funnel = {
        "staff_accesses": int(len(ex)),
        "explained_by_alibi": int((ex["verdict"] == "EXPLAINED").sum()),
        "signals": len(sig),
        "candidate_chains": len(briefs),
        "queued": int(sum(pri[p] for p in QUEUED)),
        "watch": int(pri["WATCH"]),
        "suppressed": int(pri["EXPLAINED"]),
        "by_priority": dict(pri),
    }
    detectors = [{"code": k, "signals": v, "on_scenario_entities": on_scenario.get(k, 0),
                  "elsewhere": v - on_scenario.get(k, 0)} for k, v in sorted(by_det.items())]
    return {"summary": {"passed": sum(r["passed"] for r in out), "total": len(out),
                        "twins_quiet": sum(r["passed"] for r in out if r["variant"] == "twin"),
                        "twins_total": sum(1 for r in out if r["variant"] == "twin"),
                        "suspicious_caught": sum(r["passed"] for r in out if r["variant"] == "suspicious"),
                        "suspicious_total": sum(1 for r in out if r["variant"] == "suspicious")},
            "scenarios": out, "funnel": funnel, "detectors": detectors,
            "note": "Computed on the synthetic Kestrel-Sim world (seed 42). Not real-bank accuracy."}
