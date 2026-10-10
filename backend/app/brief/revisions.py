"""Case revisions — the history of every alert's case state, and why it changed (FIN-04 Addition 1).

After each detection run, `record` takes a snapshot of every alert's case state — priority and the
lattice rule behind it, dimension levels, chain links, cited evidence, money at risk, the connected
case it belongs to and M7's suspicion score — and compares it with that alert's latest revision.
A changed snapshot becomes a new revision that lists each change and the reason for it, naming the
delivered rows (and which of them arrived late) that the alert now cites. An alert detection no longer
finds gets a WITHDRAWN revision. Revisions are append-only: rows are never updated, so the earlier case
state is always there to compare against.

Identity is the alert's natural key — chain kind and root event — not its display ID. Display IDs are
handed out in order of first detection, which depends on when rows arrived; the natural key does not.
`snapshot_sha256` covers everything except the display ID, so two replays of the same event history
can be compared case by case.

Every figure here is copied from what detection persisted. Nothing is scored or re-ranked.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import Connection, text

DIM_LABEL = {"transaction": "Transaction", "employee": "Employee behaviour", "access": "Access", "network": "Network",
             "temporal": "Temporal", "relationship": "Relationship", "historical": "Historical"}
# Evidence copied from a source system's row; everything else (model scores, graph measures, Alibi, entity
# matches) is computed by SUTRA and may be recalculated as events arrive.
SOURCE_KINDS = frozenset({"TXN", "ACCESS", "STATE_CHANGE", "SESSION", "BENEFICIARY", "ENTITLEMENT", "ROSTER",
                          "ACCOUNT_OPENING", "HR_RECORD", "ASSET", "AA_STATEMENT"})


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def snapshots(conn: Connection) -> dict[str, dict]:
    """The current case state of every alert, keyed by natural key `KIND|root_ref`."""
    alerts = conn.execute(text("""
        SELECT a.id, a.typology, a.claim, a.priority, a.lattice_rule, a.state, a.recoverable, a.dims,
               a.argument -> 'case' AS case_card, c.id AS chain_id, c.kind, c.root_ref, c.classifier_p,
               c.amount_at_risk_paise
        FROM alert a JOIN chain c ON c.id = a.chain_id""")).all()
    links: dict[str, list] = defaultdict(list)
    for chain_id, code, event_id in conn.execute(text("SELECT chain_id, code, event_id FROM chain_link ORDER BY chain_id, seq")):
        links[chain_id].append([code, event_id])
    evidence: dict[str, list] = defaultdict(list)
    for alert_id, kind, ref, sha in conn.execute(text("SELECT alert_id, kind, source_ref, sha256 FROM evidence")):
        evidence[alert_id].append([kind, ref, sha[:16]])
    out = {}
    for a in alerts:
        card = a.case_card or {}
        sus = card.get("suspicion") or {}
        snap = {
            "alert_id": a.id, "typology": a.typology, "claim": a.claim, "priority": a.priority,
            "lattice_rule": a.lattice_rule, "state": a.state, "recoverable": bool(a.recoverable),
            "dims": {d["key"]: d["level"] for d in (a.dims or [])},
            "amount_at_risk": round((a.amount_at_risk_paise or 0) / 100, 2),
            "classifier_p": a.classifier_p,
            "links": links.get(a.chain_id, []),
            "evidence": sorted(evidence.get(a.id, [])),
            "evidence_count": len(evidence.get(a.id, [])),
            "case": {"key": card.get("key"), "chains": card.get("chains"), "accounts": card.get("accounts"),
                     "linked_cases": card.get("linked_cases", []), "suspicion_p": sus.get("p"),
                     "above_threshold": sus.get("above_threshold")} if card else None,
        }
        out[f"{a.kind}|{a.root_ref}"] = snap
    return out


def content_sha(snap: dict) -> str:
    """Hash of a snapshot without its display ID — equal for equal case states, whatever the arrival order."""
    return _sha({k: v for k, v in snap.items() if k != "alert_id"})


def _latest(conn: Connection) -> dict[str, dict]:
    rows = conn.execute(text("""
        SELECT DISTINCT ON (alert_key) alert_key, rev, status, snapshot, snapshot_sha256
        FROM case_revision ORDER BY alert_key, rev DESC""")).all()
    return {r.alert_key: {"rev": r.rev, "status": r.status, "snapshot": r.snapshot, "sha": r.snapshot_sha256}
            for r in rows}


def _ref_note(ref: str, trigger: dict) -> str:
    late = trigger.get("late", {})
    if ref in late:
        return f"{ref} (arrived late, {late[ref] // 60} min behind the feed)"
    return ref


def diff(before: dict | None, after: dict, trigger: dict) -> list[dict]:
    """What changed between two snapshots, each change with the reason detection gives for it."""
    if before is None:
        new_refs = [r for r in trigger.get("refs", []) if any(r == e[1] for e in after["evidence"])
                    or any(r == lk[1] for lk in after["links"])]
        why = f"Opened from {after['evidence_count']} evidence item(s)"
        if new_refs:
            why += "; rows that arrived in this run: " + ", ".join(_ref_note(r, trigger) for r in new_refs[:8])
        return [{"field": "status", "before": None, "after": after["priority"],
                 "why": f"{why}. Priority rule: {after['lattice_rule']}."}]
    out = []

    def add(field: str, b, a, why: str) -> None:
        out.append({"field": field, "before": b, "after": a, "why": why})

    if before["priority"] != after["priority"]:
        add("priority", before["priority"], after["priority"], f"Priority rule now reads: {after['lattice_rule']}.")
    for key in sorted(set(before["dims"]) | set(after["dims"])):
        b, a = before["dims"].get(key), after["dims"].get(key)
        if b != a:
            add(f"dims.{key}", b, a, f"{DIM_LABEL.get(key, key)} dimension re-graded on the evidence now cited.")
    b_links, a_links = {lk[1] for lk in before["links"]}, {lk[1] for lk in after["links"]}
    if b_links != a_links:
        gained = [lk for lk in after["links"] if lk[1] not in b_links]
        lost = [lk for lk in before["links"] if lk[1] not in a_links]
        bits = []
        if gained:
            bits.append("gained " + ", ".join(f"{code} {_ref_note(ref, trigger)}" for code, ref in gained[:8]))
        if lost:
            bits.append("lost " + ", ".join(f"{code} {ref}" for code, ref in lost[:8]))
        add("links", len(before["links"]), len(after["links"]), "Chain " + "; ".join(bits) + ".")
    b_ev, a_ev = {e[1]: e for e in before["evidence"]}, {e[1]: e for e in after["evidence"]}
    if set(b_ev) != set(a_ev):
        gained = sorted(set(a_ev) - set(b_ev))
        lost = sorted(set(b_ev) - set(a_ev))
        bits = []
        if gained:
            bits.append(f"{len(gained)} new: " + ", ".join(_ref_note(r, trigger) for r in gained[:8]))
        if lost:
            bits.append(f"{len(lost)} no longer cited: " + ", ".join(lost[:8]))
        add("evidence", before["evidence_count"], after["evidence_count"], "Evidence " + "; ".join(bits) + ".")
    rederived = sorted(r for r in set(a_ev) & set(b_ev) if a_ev[r][2] != b_ev[r][2])
    if rederived:
        source = [r for r in rederived if a_ev[r][0] in SOURCE_KINDS]
        derived = [r for r in rederived if a_ev[r][0] not in SOURCE_KINDS]
        if derived:
            add("evidence.recomputed", len(derived), len(derived),
                f"{len(derived)} computed record(s) were recalculated on the events now in Loom (model scores, graph "
                f"measures, Alibi checks): {', '.join(derived[:6])}.")
        if source:
            add("evidence.source_changed", len(source), len(source),
                f"{len(source)} cited source record(s) now read differently: {', '.join(source[:6])} — check the "
                "delivery receipts for these IDs.")
    if before["amount_at_risk"] != after["amount_at_risk"]:
        add("amount_at_risk", before["amount_at_risk"], after["amount_at_risk"],
            "Money at risk recomputed from the transfers the chain now contains.")
    if before.get("lattice_rule") != after.get("lattice_rule") and before["priority"] == after["priority"]:
        add("lattice_rule", before.get("lattice_rule"), after.get("lattice_rule"),
            f"Priority stays {after['priority']}; the rule behind it now reads: {after.get('lattice_rule')}.")
    if before.get("recoverable") != after.get("recoverable"):
        add("recoverable", before.get("recoverable"), after.get("recoverable"),
            "Whether funds are still recoverable was recomputed from the latest transfers.")
    bc, ac = before.get("case") or {}, after.get("case") or {}
    if bc.get("key") != ac.get("key"):
        add("case.key", bc.get("key"), ac.get("key"),
            f"New evidence joined this alert to a different connected case ({ac.get('chains')} chain(s), "
            f"{ac.get('accounts')} account(s)).")
    if (bc.get("chains"), bc.get("accounts")) != (ac.get("chains"), ac.get("accounts")):
        add("case.size", f"{bc.get('chains')} chains, {bc.get('accounts')} accounts",
            f"{ac.get('chains')} chains, {ac.get('accounts')} accounts",
            "The connected case grew or shrank: chains and signals joined through shared accounts, devices or "
            "counterparties.")
    b_lc, a_lc = set(bc.get("linked_cases") or []), set(ac.get("linked_cases") or [])
    if b_lc != a_lc:
        bits = []
        if a_lc - b_lc:
            bits.append("now linked to " + ", ".join(sorted(a_lc - b_lc)[:6]))
        if b_lc - a_lc:
            bits.append("no longer linked to " + ", ".join(sorted(b_lc - a_lc)[:6]))
        add("case.linked_cases", len(b_lc), len(a_lc),
            "Cases that share a staff member with this one: " + "; ".join(bits) + ". A linked case's ID changes "
            "when an earlier event joins it.")
    if bc.get("suspicion_p") != ac.get("suspicion_p"):
        add("case.suspicion_p", bc.get("suspicion_p"), ac.get("suspicion_p"),
            "M7 re-scored the connected case on its new graph and sequence features. A suspicion score orders "
            "the queue; it is not a finding.")
    if bc.get("above_threshold") != ac.get("above_threshold"):
        add("case.above_threshold", bc.get("above_threshold"), ac.get("above_threshold"),
            "M7's score crossed its operating threshold. Priority is still set by the rules.")
    if before.get("classifier_p") != after.get("classifier_p"):
        add("classifier_p", before.get("classifier_p"), after.get("classifier_p"),
            "M5 re-scored the chain on its new features.")
    if before["claim"] != after["claim"]:
        add("claim", before["claim"], after["claim"], "The argued claim was rebuilt from the new chain.")
    if before["state"] != after["state"]:
        add("state", before["state"], after["state"], "Queue state follows the new priority.")
    if before.get("typology") != after.get("typology"):
        add("typology", before.get("typology"), after.get("typology"), "The chain now reads as a different typology.")
    if not out and content_sha(before) != content_sha(after):  # never a silent revision
        moved = sorted(k for k in after if k != "alert_id" and after.get(k) != before.get(k))
        add("other", None, None, "Case state changed in: " + ", ".join(moved) + ".")
    return out


def _summary(status: str, changes: list[dict], snap: dict) -> str:
    if status == "OPENED":
        return f"Opened at {snap['priority']}: {snap['claim']}"
    if status == "WITHDRAWN":
        return "Withdrawn: detection no longer finds this chain in the evidence now in Loom"
    label = {"evidence.recomputed": "computed evidence recalculated", "case.size": "connected case resized",
             "case.linked_cases": "linked cases changed", "lattice_rule": "priority rule restated",
             "case.key": "joined another connected case", "evidence.source_changed": "a source record reads differently"}
    heads = []
    for c in changes:
        f = c["field"]
        if f in ("priority", "evidence", "links", "case.suspicion_p", "amount_at_risk", "classifier_p"):
            name = {"links": "chain links", "case.suspicion_p": "M7 suspicion", "amount_at_risk": "money at risk",
                    "classifier_p": "M5"}.get(f, f)
            heads.append(f"{name} {c['before']} → {c['after']}")
        elif f.startswith("dims."):
            heads.append(f"{DIM_LABEL.get(f[5:], f[5:])} {c['before']} → {c['after']}")
        else:
            heads.append(label.get(f, f))
    return "Revised: " + ", ".join(dict.fromkeys(heads))


def record(conn: Connection, run_id: str, trigger: dict | None = None) -> dict:
    """Write a revision for every alert whose case state changed in this run. Call after `persist`.

    `trigger` describes what arrived since the previous run: {"refs": [...], "late": {ref: seconds},
    "duplicates": n, "conflicts": n, "kind": "..."} (all optional). Returns counts.
    """
    trigger = trigger or {}
    now = datetime.now(UTC)
    current = snapshots(conn)
    latest = _latest(conn)
    rows, counts = [], {"opened": 0, "revised": 0, "withdrawn": 0, "unchanged": 0}
    for key, snap in sorted(current.items()):
        sha = content_sha(snap)
        prev = latest.get(key)
        if prev and prev["status"] != "WITHDRAWN" and prev["sha"] == sha:
            counts["unchanged"] += 1
            continue
        before = prev["snapshot"] if prev and prev["status"] != "WITHDRAWN" else None
        status = "OPENED" if before is None else "REVISED"
        changes = diff(before, snap, trigger)
        rows.append({"key": key, "alert_id": snap["alert_id"], "rev": (prev["rev"] if prev else 0) + 1,
                     "status": status, "snap": snap, "sha": sha, "changes": changes,
                     "summary": _summary(status, changes, snap)})
        counts["opened" if status == "OPENED" else "revised"] += 1
    for key, prev in sorted(latest.items()):
        if key in current or prev["status"] == "WITHDRAWN":
            continue
        snap = prev["snapshot"]
        changes = [{"field": "status", "before": snap["priority"], "after": "WITHDRAWN",
                    "why": "Detection no longer assembles this chain from the evidence now in Loom (for example, the "
                           "rows it rested on were undone)."}]
        rows.append({"key": key, "alert_id": snap["alert_id"], "rev": prev["rev"] + 1, "status": "WITHDRAWN",
                     "snap": snap, "sha": prev["sha"], "changes": changes,
                     "summary": _summary("WITHDRAWN", changes, snap)})
        counts["withdrawn"] += 1
    public_trigger = {k: trigger[k] for k in ("kind", "refs", "late", "duplicates", "conflicts", "plan", "checkpoint")
                      if k in trigger}
    if "refs" in public_trigger:
        public_trigger["refs"] = public_trigger["refs"][:400]
    for r in rows:
        conn.execute(text("""
            INSERT INTO case_revision (alert_key, alert_id, rev, run_id, created_at, status, snapshot, snapshot_sha256,
                                       changes, trigger, summary)
            VALUES (:key, :alert_id, :rev, :run, :now, :status, CAST(:snap AS jsonb), :sha, CAST(:changes AS jsonb),
                    CAST(:trigger AS jsonb), :summary)"""),
                     {"key": r["key"], "alert_id": r["alert_id"], "rev": r["rev"], "run": run_id, "now": now,
                      "status": r["status"], "snap": json.dumps(r["snap"], default=str), "sha": r["sha"],
                      "changes": json.dumps(r["changes"], default=str), "trigger": json.dumps(public_trigger, default=str),
                      "summary": r["summary"]})
    return counts


def history(conn: Connection, alert_id: str) -> list[dict]:
    """Every revision of the alert with this display ID (followed through its natural key)."""
    key = conn.execute(text("SELECT alert_key FROM case_revision WHERE alert_id = :a ORDER BY rev DESC LIMIT 1"),
                       {"a": alert_id}).scalar()
    if key is None:
        key = conn.execute(text("SELECT c.kind || '|' || c.root_ref FROM alert a JOIN chain c ON c.id = a.chain_id "
                                "WHERE a.id = :a"), {"a": alert_id}).scalar()
    if key is None:
        return []
    rows = conn.execute(text("SELECT rev, run_id, created_at, status, snapshot, snapshot_sha256, changes, trigger, summary "
                             "FROM case_revision WHERE alert_key = :k ORDER BY rev"), {"k": key}).all()
    return [{"rev": r.rev, "run_id": r.run_id, "at": r.created_at.isoformat(), "status": r.status,
             "priority": r.snapshot.get("priority"), "evidence_count": r.snapshot.get("evidence_count"),
             "amount_at_risk": r.snapshot.get("amount_at_risk"),
             "suspicion_p": (r.snapshot.get("case") or {}).get("suspicion_p"),
             "case_key": (r.snapshot.get("case") or {}).get("key"),
             "snapshot_sha256": r.snapshot_sha256, "changes": r.changes, "trigger": r.trigger, "summary": r.summary,
             "alert_key": key} for r in rows]
