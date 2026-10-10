"""Case features for M7: graph structure, event sequence and detector evidence (docs/ml/features.md).

Every feature comes with its provenance: the accounts, events or cases that produced its value, so an
investigator can open the records behind any bar in the score breakdown. Features never read arrival
times (`ingested_at`), display IDs or anything else that depends on the order rows reached SUTRA.

Families
  graph     who is connected to whom: size, new and presence-less accounts, shared identifiers, fan-in,
            pass-through, cash-out, cycles, and links to other cases through shared staff
  sequence  in what order and how fast: access-to-money latency, hop-grammar progress, gaps, span,
            burstiness, night share, change→payee timing, balance drained, grant-to-use delay
  evidence  what the detectors said: distinct rule, graph and behavioural detectors, Alibi coverage,
            record systems, strongest signal

The model sees `graph + sequence + evidence`. The ablation "M7 without detector features" drops the
evidence family to show how much the structure and timing carry on their own.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.loom.frames import Frames
from app.ml.cases import Case

GRAPH_FEATURES = [
    "g_accounts", "g_customers", "g_employees", "g_devices", "g_external_share", "g_new_account_share",
    "g_presenceless_share", "g_self_approved_share", "g_opener_concentration", "g_shared_identifier",
    "g_max_fan_in", "g_max_pass_through", "g_cash_out", "g_cycle_retention", "g_linked_cases",
]
SEQUENCE_FEATURES = [
    "s_log_latency", "s_grammar", "s_hops", "s_min_hop_gap", "s_span", "s_burstiness", "s_night_share",
    "s_change_to_payee", "s_balance_moved", "s_grant_to_use_days",
]
EVIDENCE_FEATURES = [
    "e_rule_detectors", "e_graph_detectors", "e_behaviour", "e_alibi_unexplained", "e_off_roster",
    "e_record_systems", "e_max_strength",
]
CASE_FEATURES = GRAPH_FEATURES + SEQUENCE_FEATURES + EVIDENCE_FEATURES
STRUCTURE_FEATURES = GRAPH_FEATURES + SEQUENCE_FEATURES
FAMILY = {**{k: "graph" for k in GRAPH_FEATURES}, **{k: "sequence" for k in SEQUENCE_FEATURES},
          **{k: "evidence" for k in EVIDENCE_FEATURES}}

CASE_LABELS = {
    "g_accounts": "Bank accounts in the case",
    "g_customers": "Customers in the case",
    "g_employees": "Staff involved",
    "g_devices": "Devices involved",
    "g_external_share": "Share of counterparties at other banks",
    "g_new_account_share": "Accounts opened in the last 90 days",
    "g_presenceless_share": "New accounts opened without the customer present",
    "g_self_approved_share": "Accounts whose opener approved their own KYC",
    "g_opener_concentration": "New accounts opened by one employee",
    "g_shared_identifier": "Accounts sharing a device or phone with other customers",
    "g_max_fan_in": "Most distinct senders into one account",
    "g_max_pass_through": "Inflow forwarded within 60 min",
    "g_cash_out": "Share cashed out at ATMs",
    "g_cycle_retention": "Money that came back round a cycle",
    "g_linked_cases": "Other cases sharing staff with this one",
    "s_log_latency": "Access-to-money latency",
    "s_grammar": "Insider hop grammar completed",
    "s_hops": "Hops in the longest chain",
    "s_min_hop_gap": "Shortest gap between hops",
    "s_span": "Time from first to last event",
    "s_burstiness": "Burstiness of event timing",
    "s_night_share": "Events between 20:00 and 06:00",
    "s_change_to_payee": "Contact change → new payee within 30 min",
    "s_balance_moved": "Share of balance moved out",
    "s_grant_to_use_days": "Days from entitlement grant to use",
    "e_rule_detectors": "Distinct rule detectors",
    "e_graph_detectors": "Distinct graph detectors",
    "e_behaviour": "Behavioural detectors (rhythm, navigation)",
    "e_alibi_unexplained": "Staff accesses Alibi could not explain",
    "e_off_roster": "Staff accesses outside any roster",
    "e_record_systems": "Independent record systems in the evidence",
    "e_max_strength": "Strongest single signal",
}

INSIDER_GRAMMAR = ("E0", "E1", "E2", "E3", "E4", "E5", "E5′", "E6")
CONTACT_FIELDS = ("REGISTERED_MOBILE", "PASSWORD", "EMAIL", "DEVICE_BINDING", "TXN_LIMIT")
EVENT_TABLES = {  # table → (time column, source type)
    "txn": ("occurred_at", "payments"), "access_event": ("occurred_at", "staff_audit"),
    "state_change": ("occurred_at", "core_banking"), "beneficiary": ("added_at", "digital_banking"),
    "session": ("started_at", "sessions"), "account": ("opened_at", "account_opening"),
    "entitlement": ("valid_from", "iam"), "work_item": ("created_at", "service_desk"),
}
PROV = 8  # references kept per feature


@dataclass
class CaseRow:
    key: str
    values: dict[str, float]
    provenance: dict[str, list[str]]


class FeatureContext:
    """Per-world lookups, built once and shared by every case."""

    def __init__(self, f: Frames, ex: pd.DataFrame, mule: pd.DataFrame, cases: list[Case]):
        self.f = f
        self.acc = f.account.set_index("id")
        self.internal = set(self.acc.index[self.acc["kind"] != "EXTERNAL"])
        self.devices = set(f.device["id"])
        self.mule = mule
        self.window_start = f.window_start

        a = f.access_event[["id", "account_id"]].rename(columns={"id": "access_event_id"})
        e = ex[["access_event_id", "verdict", "timing_ok"]].merge(a, on="access_event_id")
        self.access_by_account = {k: g for k, g in e.groupby("account_id")}

        wanted = {ev for c in cases for ev in c.events}
        parts = []
        for table, (col, src) in EVENT_TABLES.items():
            df = getattr(f, table)
            hit = df.loc[df["id"].isin(wanted), ["id", col]].rename(columns={col: "t"})
            parts.append(hit.assign(source=src))
        ev = pd.concat(parts, ignore_index=True).dropna(subset=["t"]).drop_duplicates("id")
        self.event_t = dict(zip(ev["id"], ev["t"], strict=True))
        self.event_src = dict(zip(ev["id"], ev["source"], strict=True))

        # A contact or limit change followed by a new payee on the same account within 30 minutes.
        sc = f.state_change[f.state_change["field"].isin(CONTACT_FIELDS)][["id", "account_id", "occurred_at"]]
        ben = f.beneficiary[["id", "account_id", "added_at"]].sort_values("added_at")
        m = pd.merge_asof(sc.sort_values("occurred_at"), ben.rename(columns={"id": "ben_id"}),
                          left_on="occurred_at", right_on="added_at", by="account_id", direction="forward",
                          tolerance=pd.Timedelta(minutes=30))
        m = m.dropna(subset=["ben_id"])
        self.change_payee = {r.account_id: [r.id, r.ben_id] for r in m.itertuples(index=False)}


def _log1p(x: float) -> float:
    return float(np.log1p(max(x, 0.0)))


def _nan() -> float:
    return float("nan")


def case_row(c: Case, fx: FeatureContext) -> CaseRow:
    v: dict[str, float] = {}
    prov: dict[str, list[str]] = {}
    acc = fx.acc
    internal = sorted(e for e in c.entities if e in fx.internal)
    external = sorted(e for e in c.entities if e.startswith("X-") or (e in acc.index and e not in fx.internal))
    customers = sorted({e for e in c.entities if e.startswith("C-")}
                       | {acc.at[a, "customer_id"] for a in internal if isinstance(acc.at[a, "customer_id"], str)})
    devices = sorted(e for e in c.entities if e in fx.devices)
    mule = fx.mule.loc[[a for a in internal if a in fx.mule.index]]

    # ── graph
    v["g_accounts"], prov["g_accounts"] = _log1p(len(internal)), internal[:PROV]
    v["g_customers"], prov["g_customers"] = _log1p(len(customers)), customers[:PROV]
    v["g_employees"], prov["g_employees"] = float(len(c.employees)), sorted(c.employees)[:PROV]
    v["g_devices"], prov["g_devices"] = float(len(devices)), devices[:PROV]
    v["g_external_share"] = len(external) / max(len(internal) + len(external), 1)
    prov["g_external_share"] = external[:PROV]
    opened = acc.loc[internal, "opened_at"]
    new = sorted(opened[opened >= fx.window_start].index)
    v["g_new_account_share"], prov["g_new_account_share"] = len(new) / max(len(internal), 1), new[:PROV]
    pl = sorted(a for a in new if a in mule.index and mule.at[a, "presenceless"] > 0)
    v["g_presenceless_share"], prov["g_presenceless_share"] = len(pl) / max(len(new), 1), pl[:PROV]
    sa = sorted(a for a in internal if a in mule.index and mule.at[a, "self_approved"] > 0)
    v["g_self_approved_share"], prov["g_self_approved_share"] = len(sa) / max(len(internal), 1), sa[:PROV]
    if len(new) >= 2:
        openers = acc.loc[new, "opened_by"].dropna()
        top = openers.value_counts()
        emp = top.index[0] if len(top) else None
        v["g_opener_concentration"] = float(top.iloc[0]) / len(new) if len(top) else 0.0
        prov["g_opener_concentration"] = ([emp] if emp else []) + sorted(openers[openers == emp].index)[:PROV - 1]
    else:
        v["g_opener_concentration"], prov["g_opener_concentration"] = 0.0, []
    shared = sorted(a for a in internal if a in mule.index
                    and (mule.at[a, "device_shared"] > 0 or mule.at[a, "phone_shared"] > 0))
    v["g_shared_identifier"], prov["g_shared_identifier"] = _log1p(len(shared)), shared[:PROV]
    for feat, col in (("g_max_fan_in", "n_senders"), ("g_max_pass_through", "pass_through_share"),
                      ("g_cash_out", "atm_share")):
        if len(mule):
            a = mule[col].idxmax()
            val = float(mule.at[a, col])
            v[feat] = _log1p(val) if feat == "g_max_fan_in" else val
            prov[feat] = [a] if val > 0 else []
        else:
            v[feat], prov[feat] = 0.0, []
    g1 = [s for s in c.signals if s["detector"] == "G1"]
    best = max(g1, key=lambda s: s["payload"]["retention"], default=None)
    v["g_cycle_retention"] = float(best["payload"]["retention"]) if best else 0.0
    prov["g_cycle_retention"] = best["event_refs"][:PROV] if best else []
    v["g_linked_cases"], prov["g_linked_cases"] = _log1p(len(c.linked_cases)), sorted(c.linked_cases)[:PROV]

    # ── sequence
    chains = c.chains
    lat = [(d.latency_s, d) for d in chains if d.latency_s is not None and d.kind in ("INSIDER_ATO", "EXTERNAL_ATO")]
    if lat:
        s, d = min(lat, key=lambda x: x[0])
        v["s_log_latency"] = _log1p(s / 60)
        prov["s_log_latency"] = [str(lk.event_id) for lk in d.links if lk.code in ("E1", "E5")][:PROV]
    else:
        v["s_log_latency"], prov["s_log_latency"] = _nan(), []
    insiders = [d for d in chains if d.kind == "INSIDER_ATO"]
    if insiders:
        d = max(insiders, key=lambda d: len({lk.code for lk in d.links} & set(INSIDER_GRAMMAR)))
        codes = {lk.code for lk in d.links} & set(INSIDER_GRAMMAR)
        v["s_grammar"] = len(codes) / len(INSIDER_GRAMMAR)
        prov["s_grammar"] = [str(lk.event_id) for lk in d.links if lk.code in codes][:PROV]
    else:
        v["s_grammar"], prov["s_grammar"] = _nan(), []
    if chains:
        d = max(chains, key=lambda d: (len({lk.code for lk in d.links}), d.root_ref))
        v["s_hops"], prov["s_hops"] = float(len({lk.code for lk in d.links})), [d.root_ref]
        gaps = []
        for d in chains:
            ls = sorted(d.links, key=lambda lk: lk.t)
            gaps += [((b.t - a.t).total_seconds(), a, b) for a, b in zip(ls, ls[1:], strict=False)
                     if a.code != b.code and b.t > a.t]
        if gaps:
            g, a, b = min(gaps, key=lambda x: x[0])
            v["s_min_hop_gap"], prov["s_min_hop_gap"] = _log1p(g), [str(a.event_id), str(b.event_id)]
        else:
            v["s_min_hop_gap"], prov["s_min_hop_gap"] = _nan(), []
    else:
        v["s_hops"], prov["s_hops"] = 0.0, []
        v["s_min_hop_gap"], prov["s_min_hop_gap"] = _nan(), []

    timed = sorted(((t, ev) for ev in c.events if (t := fx.event_t.get(ev)) is not None), key=lambda x: (x[0], x[1]))
    timed += sorted(((lk.t, str(lk.event_id)) for d in chains for lk in d.links), key=lambda x: (x[0], x[1]))
    timed = sorted(dict((ev, t) for t, ev in timed).items(), key=lambda x: (x[1], x[0]))
    if timed:
        first, last = timed[0], timed[-1]
        v["s_span"] = _log1p((last[1] - first[1]).total_seconds() / 3600)
        prov["s_span"] = [first[0], last[0]]
        hours = np.array([t.hour for _, t in timed])
        night = [ev for (ev, t), h in zip(timed, hours, strict=True) if h >= 20 or h < 6]
        v["s_night_share"], prov["s_night_share"] = len(night) / len(timed), night[:PROV]
    else:
        v["s_span"], prov["s_span"] = 0.0, []
        v["s_night_share"], prov["s_night_share"] = 0.0, []
    if len(timed) >= 3:
        secs = np.diff(np.array([t.value for _, t in timed], dtype=np.int64)) / 1e9
        v["s_burstiness"] = float(secs.std() / secs.mean()) if secs.mean() > 0 else 0.0
        prov["s_burstiness"] = [ev for ev, _ in timed][:PROV]
    else:
        v["s_burstiness"], prov["s_burstiness"] = _nan(), []
    cp = next((fx.change_payee[a] for a in internal if a in fx.change_payee), None)
    v["s_change_to_payee"], prov["s_change_to_payee"] = (1.0, cp) if cp else (0.0, [])
    moved = [(float(d.features.get("amount_to_balance", 0.0)), d) for d in chains if "amount_to_balance" in d.features]
    if moved:
        m, d = max(moved, key=lambda x: (x[0], x[1].root_ref))
        v["s_balance_moved"] = m
        prov["s_balance_moved"] = next((list(map(str, lk.refs))[:PROV] for lk in d.links if lk.code == "E5"), [])
    else:
        v["s_balance_moved"], prov["s_balance_moved"] = _nan(), []
    grants = []
    for d in insiders:
        e0 = next((lk for lk in d.links if lk.code == "E0"), None)
        e3 = next((lk for lk in d.links if lk.code == "E3"), None)
        if e0 and e3:
            grants.append(((e3.t - e0.t).total_seconds() / 86400, e0, e3))
    if grants:
        days, e0, e3 = min(grants, key=lambda x: x[0])
        v["s_grant_to_use_days"], prov["s_grant_to_use_days"] = float(days), [str(e0.event_id), str(e3.event_id)]
    else:
        v["s_grant_to_use_days"], prov["s_grant_to_use_days"] = _nan(), []

    # ── evidence
    dets = c.detectors
    rules = sorted(d for d in dets if d.startswith("R"))
    graphs = sorted(d for d in dets if d.startswith("G"))
    behav = sorted(d for d in dets if d in ("M1", "M2"))
    v["e_rule_detectors"], prov["e_rule_detectors"] = float(len(rules)), rules
    v["e_graph_detectors"], prov["e_graph_detectors"] = float(len(graphs)), graphs
    v["e_behaviour"], prov["e_behaviour"] = float(len(behav)), behav
    acc_rows = [fx.access_by_account[a] for a in internal if a in fx.access_by_account]
    if acc_rows:
        ae = pd.concat(acc_rows)
        unexp = ae[ae["verdict"] != "EXPLAINED"]
        off = ae[~ae["timing_ok"].astype(bool)]
        v["e_alibi_unexplained"] = len(unexp) / len(ae)
        prov["e_alibi_unexplained"] = sorted(unexp["access_event_id"])[:PROV]
        v["e_off_roster"], prov["e_off_roster"] = len(off) / len(ae), sorted(off["access_event_id"])[:PROV]
    else:
        v["e_alibi_unexplained"], prov["e_alibi_unexplained"] = 0.0, []
        v["e_off_roster"], prov["e_off_roster"] = 0.0, []
    srcs = sorted({fx.event_src[ev] for ev in c.events if ev in fx.event_src})
    v["e_record_systems"], prov["e_record_systems"] = float(len(srcs)), srcs
    strong = max(c.signals + c.attributes, key=lambda s: (s["strength"], s["detector"]), default=None)
    v["e_max_strength"] = float(strong["strength"]) if strong else 0.0
    prov["e_max_strength"] = ([strong["detector"], *strong["event_refs"][:PROV - 1]] if strong else [])

    return CaseRow(c.key, {k: float(v[k]) for k in CASE_FEATURES}, {k: prov[k] for k in CASE_FEATURES})


def case_rows(cases: list[Case], f: Frames, ex: pd.DataFrame, mule: pd.DataFrame) -> list[CaseRow]:
    fx = FeatureContext(f, ex, mule, cases)
    return [case_row(c, fx) for c in cases]


def matrix(rows: list[CaseRow], names: list[str]) -> np.ndarray:
    return np.array([[r.values[k] for k in names] for r in rows], dtype=float).reshape(len(rows), len(names))
