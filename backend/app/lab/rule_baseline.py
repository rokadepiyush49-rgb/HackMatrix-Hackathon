"""Documented rule baselines that M7 is compared against (docs/ml/rule_baseline.md).

RB-1 is the kind of rule set a bank's monitoring team writes: one clause per typology, each built from
SUTRA's own detectors, with no learned parameter. A case alerts when any clause holds. The clauses were
written from the detector catalogue before any evaluation was run and are frozen; changing one means a
new version (RB-1.1 …) and a new row in the report, never a silent edit.

RB-2 is SUTRA's own priority lattice with every model input switched off (no M5, no M6): a case alerts
when any chain in it reaches P1, P2 or P3. It shows what the hand-written argument rules achieve alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.ml.cases import Case

RB1_VERSION = "1.0"
QUEUED = {"P1", "P2", "P3"}


@dataclass(frozen=True)
class Clause:
    code: str
    typology: str
    text: str


RB1_CLAUSES = [
    Clause("C1", "Account takeover", "R4 — a mobile, password or e-mail change, then a new payee paid within 24 h"),
    Clause("C2", "Insider misuse", "R7 override use and R6 access with no purpose on the same account, "
                                   "or R9 an entitlement used after its intended expiry"),
    Clause("C3", "Mule network", "G4 mule factory, or G2 rapid pass-through and R10 presence-less opening "
                                 "on the same account"),
    Clause("C4", "Structuring", "R1 cash structuring spread across at least 2 branches"),
    Clause("C5", "Layering", "G1 time-respecting cycle that returns 70–110% of the first hop"),
    Clause("C6", "Dormant takeover", "R3 debit from a dormant account and R2 limit-hugging transfers "
                                     "from the same account"),
]


def _accounts_by_detector(c: Case) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for s in c.signals + c.attributes:
        p = s["payload"]
        acct = p.get("account")
        refs = {acct} if acct else {e for e in s["entity_refs"] if e.startswith("A-")}
        out[s["detector"]] |= refs
    return out


def rb1(c: Case) -> list[str]:
    """The RB-1 clauses that fire on a case (empty → no alert)."""
    by = _accounts_by_detector(c)
    dets = c.detectors
    fired = []
    if "R4" in dets:
        fired.append("C1")
    if by["R7"] & by["R6"] or "R9" in dets:
        fired.append("C2")
    if "G4" in dets or by["G2"] & by["R10"]:
        fired.append("C3")
    if any(len(s["payload"].get("branches", [])) >= 2 for s in c.signals if s["detector"] == "R1"):
        fired.append("C4")
    if any(0.70 <= s["payload"]["retention"] <= 1.10 for s in c.signals if s["detector"] == "G1"):
        fired.append("C5")
    if by["R3"] & by["R2"]:
        fired.append("C6")
    return fired


def rb2(c: Case, priority_of: dict[tuple[str, str], str]) -> str | None:
    """Best rules-only lattice priority among the case's chains (None when the case has no chain)."""
    order = ["P1", "P2", "P3", "WATCH", "EXPLAINED"]
    pri = [priority_of[(d.kind, d.root_ref)] for d in c.chains if (d.kind, d.root_ref) in priority_of]
    return min(pri, key=order.index) if pri else None


def describe() -> dict:
    return {"RB-1": {"version": RB1_VERSION, "rule": "alert when any clause holds",
                     "clauses": [c.__dict__ for c in RB1_CLAUSES]},
            "RB-2": {"version": "1.0", "rule": "alert when any chain in the case reaches P1–P3 on SUTRA's "
                                               "priority lattice with every model input switched off"}}
