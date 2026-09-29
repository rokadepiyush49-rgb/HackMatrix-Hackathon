"""Entity resolution.

1. **Customer identities** — the same person behind several customer records
   (blocking on phone token; confirm with date of birth or name similarity).
2. **Employee ↔ customer links** — HR records matched against customers
   (blocking on PIN code; fuzzy address + surname + phone agreement).

Every match carries per-field agreement so the investigator sees *why* two records
were linked, not just a score.
"""

from __future__ import annotations

import re

import networkx as nx
import pandas as pd
from rapidfuzz import fuzz

from app.loom.frames import Frames

ABBREV = {"apts": "apartments", "apt": "apartment", "soc": "society", "rd": "road",
          "nr": "near", "karvenagar": "karve nagar"}
DROP = {"flat", "no", "house", "plot"}


def canon_address(s: str) -> str:
    toks = [ABBREV.get(t, t) for t in re.split(r"[\s,./-]+", s.lower()) if t]
    return "".join(t for t in " ".join(toks).split() if t not in DROP)


def _surname(name: str) -> set[str]:
    return {t for t in re.split(r"[\s.]+", name.lower()) if len(t) > 2}


def _name_sim(a: str, b: str) -> float:
    strip = lambda s: " ".join(t for t in re.split(r"[\s.]+", s.lower()) if len(t) > 1)  # noqa: E731
    return fuzz.token_set_ratio(strip(a), strip(b)) / 100.0


def customer_clusters(f: Frames) -> tuple[dict[str, str], list[dict]]:
    """Return customer → cluster id, plus match evidence for multi-record clusters."""
    c = f.customer[["id", "full_name", "dob", "phone_tok", "branch_id"]].dropna(subset=["phone_tok"])
    g = nx.Graph()
    g.add_nodes_from(f.customer["id"])
    evidence = []
    for _, grp in c.groupby("phone_tok"):
        if len(grp) < 2 or len(grp) > 12:
            continue
        rows = grp.to_dict("records")
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                same_dob = a["dob"] == b["dob"] and pd.notna(a["dob"])
                ns = _name_sim(a["full_name"], b["full_name"])
                if same_dob or ns >= 0.8:
                    g.add_edge(a["id"], b["id"])
                    evidence.append({"a": a["id"], "b": b["id"], "phone": True, "dob": bool(same_dob),
                                     "name_similarity": round(ns, 2),
                                     "names": [a["full_name"], b["full_name"]],
                                     "branches": [a["branch_id"], b["branch_id"]]})
    cluster = {}
    for comp in nx.connected_components(g):
        cid = "PER-" + min(comp)
        for n in comp:
            cluster[n] = cid
    return cluster, evidence


def employee_customer_links(f: Frames, threshold: float = 0.75) -> list[dict]:
    emp = f.employee.assign(addr=lambda d: d["address_norm"].map(canon_address))
    cus = f.customer.assign(addr=lambda d: d["address_norm"].map(canon_address))
    declared = {(e, c) for e, rels in zip(f.employee["id"], f.employee["declared_relations"], strict=True)
                for c in (rels or [])}
    links = []
    for e in emp.itertuples(index=False):
        cands = cus[cus["pincode"] == e.pincode]
        if cands.empty:
            continue
        esur = _surname(e.full_name.split()[-1])
        for c in cands.itertuples(index=False):
            a_sim = fuzz.ratio(e.addr, c.addr) / 100.0
            if a_sim < 0.97:  # same dwelling after normalisation, not merely the same building
                continue
            surname = bool(esur & _surname(c.full_name))
            phone = bool(e.phone_tok and e.phone_tok == c.phone_tok)
            if not (surname or phone):
                continue
            score = 0.6 * a_sim + 0.25 * surname + 0.15 * phone
            if score >= threshold:
                links.append({
                    "employee_id": e.id, "customer_id": c.id, "score": round(score, 2),
                    "declared": (e.id, c.id) in declared,
                    "fields": {
                        "address": "exact after normalisation" if a_sim >= 0.99 else f"similar ({a_sim:.2f})",
                        "surname": "match" if surname else "no match",
                        "phone": "match" if phone else "no match"},
                })
    return links
