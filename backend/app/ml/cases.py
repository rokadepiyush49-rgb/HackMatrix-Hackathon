"""Connected cases — the unit that M7 scores and the rule baselines alert on (docs/adr/017).

A case is one connected piece of the evidence graph. Its nodes are Needle chains and the signals of
detectors that can open an investigation (`SEED_DETECTORS`). Two nodes join when they share an account,
customer, device, resolved person or external counterparty.

Employees never join cases. One officer touches hundreds of accounts in a quarter, so linking through
staff would merge every customer they served into one blob. An employee is a case *attribute* instead,
and an employee shared by two cases is recorded as a link between them (`Case.linked_cases`), which the
model sees as a graph feature. Hubs are cut the same way: the bank's cash and ATM sinks, and any entity
that appears in more than `HUB_DEGREE` nodes.

Behavioural signals (R5, R6, M1, M2) describe a person or a session, not a money movement, so they never
open a case. They are attached to the cases whose accounts or chain events they touch.

Everything here is deterministic: nodes are processed in a fixed order, and a case's key comes from the
content of its earliest node, never from discovery order or wall-clock time.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pandas as pd

from app.needle.chains import ChainDraft

SEED_DETECTORS = frozenset({"R1", "R2", "R3", "R4", "R7", "R8", "R9", "R10", "G1", "G2", "G3", "G4", "G5"})
ATTRIBUTE_DETECTORS = frozenset({"R5", "R6", "M1", "M2"})
HUBS = frozenset({"X-ATM", "X-CASH"})
HUB_DEGREE = 40


def is_employee(ref: str) -> bool:
    return ref.startswith("EMP-")


def linkable(ref: str) -> bool:
    return bool(ref) and not is_employee(ref) and ref not in HUBS


@dataclass
class Node:
    """A chain or a seeding signal, with the entities and events behind it."""

    kind: str  # "chain" | "signal"
    code: str  # chain kind or detector code
    ident: str  # stable content identity
    entities: set[str]
    events: list[str]
    t0: pd.Timestamp
    t1: pd.Timestamp
    chain: ChainDraft | None = None
    signal: dict | None = None


@dataclass
class Case:
    key: str
    nodes: list[Node]
    entities: set[str]  # linkable entities
    employees: set[str]
    attributes: list[dict] = field(default_factory=list)  # R5/R6/M1/M2 signals attached to the case
    linked_cases: set[str] = field(default_factory=set)

    @property
    def chains(self) -> list[ChainDraft]:
        return [n.chain for n in self.nodes if n.chain is not None]

    @property
    def signals(self) -> list[dict]:
        return [n.signal for n in self.nodes if n.signal is not None]

    @property
    def detectors(self) -> set[str]:
        return {n.code for n in self.nodes if n.kind == "signal"} | {s["detector"] for s in self.attributes}

    @property
    def events(self) -> list[str]:
        return list(dict.fromkeys(e for n in self.nodes for e in n.events))

    @property
    def first_t(self) -> pd.Timestamp:
        return min(n.t0 for n in self.nodes)

    @property
    def last_t(self) -> pd.Timestamp:
        return max(n.t1 for n in self.nodes)

    @property
    def anchor(self) -> Node:
        return self.nodes[0]


def _signal_node(s: dict, window: tuple[pd.Timestamp, pd.Timestamp]) -> Node:
    t0 = s["window_start"] if s["window_start"] is not None else window[0]
    t1 = s["window_end"] if s["window_end"] is not None else window[1]
    ident = f"{s['detector']}|{'|'.join(s['entity_refs'])}|{s['event_refs'][0] if s['event_refs'] else ''}"
    return Node("signal", s["detector"], ident, set(s["entity_refs"]), list(s["event_refs"]),
                pd.Timestamp(t0), pd.Timestamp(t1), signal=s)


def _chain_node(d: ChainDraft) -> Node:
    events = [r for lk in d.links for r in [str(lk.event_id), *map(str, lk.refs)]]
    return Node("chain", d.kind, f"{d.kind}|{d.root_ref}", {str(x) for x in d.entities if x},
                list(dict.fromkeys(events)), d.first_t, d.last_t, chain=d)


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def case_key(anchor: Node) -> str:
    return "CK-" + hashlib.sha1(anchor.ident.encode()).hexdigest()[:10].upper()


def build_cases(signals: list[dict], drafts: list[ChainDraft],
                window: tuple[pd.Timestamp, pd.Timestamp]) -> list[Case]:
    """Group chains and seeding signals into connected cases."""
    nodes = [_chain_node(d) for d in drafts]
    nodes += [_signal_node(s, window) for s in signals if s["detector"] in SEED_DETECTORS]
    nodes.sort(key=lambda n: (n.t0, n.kind != "chain", n.code, n.ident))

    degree = Counter(e for n in nodes for e in {x for x in n.entities if linkable(x)})
    hubs = {e for e, k in degree.items() if k > HUB_DEGREE}
    uf = _UF(len(nodes))
    first_with: dict[str, int] = {}
    for i, n in enumerate(nodes):
        for e in sorted(n.entities):
            if not linkable(e) or e in hubs:
                continue
            if e in first_with:
                uf.union(first_with[e], i)
            else:
                first_with[e] = i

    groups: dict[int, list[Node]] = defaultdict(list)
    for i, n in enumerate(nodes):
        groups[uf.find(i)].append(n)
    cases = []
    for members in groups.values():
        ents = {e for n in members for e in n.entities if linkable(e) and e not in hubs}
        if not ents:  # an employee-only signal (e.g. a toxic entitlement combination) is an attribute, not a case
            continue
        emps = {e for n in members for e in n.entities if is_employee(e)}
        emps |= {n.chain.employee_id for n in members if n.chain is not None and n.chain.employee_id}
        cases.append(Case(case_key(members[0]), members, ents, emps))
    cases.sort(key=lambda c: (c.first_t, c.key))

    # Behavioural signals attach by account (R5/R6) or by the chain session they came from (M1/M2).
    by_entity: dict[str, Case] = {e: c for c in cases for e in c.entities}
    by_event: dict[str, Case] = {ev: c for c in cases for ev in c.events}
    for s in signals:
        if s["detector"] not in ATTRIBUTE_DETECTORS:
            continue
        hit = {by_entity[e].key: by_entity[e] for e in s["entity_refs"] if e in by_entity}
        hit |= {by_event[ev].key: by_event[ev] for ev in s["event_refs"] if ev in by_event}
        for c in hit.values():
            c.attributes.append(s)
        emp_only = [e for e in s["entity_refs"] if is_employee(e)]
        for c in hit.values():
            c.employees |= set(emp_only)

    # Employee-only signals (toxic entitlements) describe every case the employee appears in.
    for s in signals:
        if s["detector"] in SEED_DETECTORS and not any(linkable(e) for e in s["entity_refs"]):
            for c in cases:
                if set(s["entity_refs"]) & c.employees:
                    c.attributes.append(s)

    # Cases that share an employee are connected investigations, even though they are not merged.
    by_emp: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        for e in c.employees:
            by_emp[e].append(c)
    for members in by_emp.values():
        if 1 < len(members) <= HUB_DEGREE:
            for c in members:
                c.linked_cases |= {o.key for o in members if o.key != c.key}
    return cases


# ── ground truth ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CaseLabel:
    y: int  # 1 = overlaps a suspicious scenario instance
    kind: str  # "suspicious" | "lookalike" | "background"
    typology: str  # scenario typology for positives, look-alike type for look-alikes, "" otherwise
    labels: tuple[str, ...]  # scenario instance keys the case touches
    group: str  # cross-validation group: cases tied together by ground truth never straddle folds


def label_cases(cases: list[Case], labels: list[dict], world: str) -> dict[str, CaseLabel]:
    """Label each case against the simulator's ground truth (docs/ml/labeling.md).

    Matching uses accounts, customers and devices only, never employees: an insider also does ordinary
    work, and that work is not part of the scheme. Groups come from a union-find over cases and scenario
    instances, so a ring that spans several cases — a takeover and the mule factory it pays into — lands
    in one fold.
    """
    lab_ents = [(lab, {e for e in lab["entities"] if linkable(e)}) for lab in labels]
    owners: dict[str, list[int]] = defaultdict(list)
    for j, (_lab, ents) in enumerate(lab_ents):
        for e in ents:
            owners[e].append(j)

    n_c = len(cases)
    uf = _UF(n_c + len(lab_ents))
    touched: list[set[int]] = []
    for i, c in enumerate(cases):
        hit = {j for e in c.entities for j in owners.get(e, ())}
        touched.append(hit)
        for j in hit:
            uf.union(i, n_c + j)

    out = {}
    for i, c in enumerate(cases):
        labs = [lab_ents[j][0] for j in sorted(touched[i])]
        susp = [lab for lab in labs if lab["variant"] == "suspicious"]
        twins = [lab for lab in labs if lab["variant"] == "twin"]
        group = f"{world}:{cases[uf.find(i)].key}"  # roots are always cases: union keeps the lower index
        if susp:
            typ = "+".join(sorted({lab["typology"] for lab in susp}))
            out[c.key] = CaseLabel(1, "suspicious", typ, tuple(sorted(lab["key"] for lab in susp)), group)
        elif twins:
            typ = "+".join(sorted({lab.get("lookalike") or lab["scenario"] for lab in twins}))
            out[c.key] = CaseLabel(0, "lookalike", typ, tuple(sorted(lab["key"] for lab in twins)), group)
        else:
            out[c.key] = CaseLabel(0, "background", "", (), group)
    return out
