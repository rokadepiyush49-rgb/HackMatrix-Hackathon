"""Graph detectors G1–G5 over the transaction / identity graph."""

from __future__ import annotations

from collections import Counter, defaultdict

import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import poisson

from app.loom.frames import Frames
from app.needle.detectors.rules import rupees, signal
from app.needle.registry import DETECTORS

CASH = {"X-CASH", "X-ATM"}


def internal_accounts(f: Frames) -> set[str]:
    return set(f.account.loc[f.account["kind"] != "EXTERNAL", "id"])


# ── G1 temporal cycles ─────────────────────────────────────────────────────


def g1_temporal_cycles(f: Frames) -> list[dict]:
    """Enumerate time-respecting simple cycles (each hop strictly later than the previous,
    all within the window) — a small-graph version of 2SCENT (Kumar & Calders, 2018)."""
    p = DETECTORS["G1"].params
    inside = internal_accounts(f)
    e = f.txn[f.txn["from_account"].isin(inside) & f.txn["to_account"].isin(inside)
              & (f.txn["amount"] >= p["min_amount"])].sort_values("occurred_at")
    adj: dict[str, list] = defaultdict(list)
    for r in e.itertuples(index=False):
        adj[r.from_account].append((r.occurred_at, r.to_account, r.amount, r.id))
    horizon = pd.Timedelta(hours=p["window_h"])
    found: dict[frozenset, list] = {}

    def dfs(start, node, path, visited, last_t, deadline):
        for t, nxt, amt, tid in adj.get(node, []):
            if t <= last_t or t > deadline:
                continue
            if nxt == start and len(path) >= 1:
                cyc = [*path, (node, nxt, t, amt, tid)]
                if amt / cyc[0][3] >= p["min_retention"]:
                    found.setdefault(frozenset(x[4] for x in cyc), cyc)
                continue
            if nxt in visited or len(path) + 1 >= p["max_len"]:
                continue
            dfs(start, nxt, [*path, (node, nxt, t, amt, tid)], visited | {nxt}, t, deadline)

    for r in e.itertuples(index=False):
        first = (r.from_account, r.to_account, r.occurred_at, r.amount, r.id)
        dfs(r.from_account, r.to_account, [first], {r.from_account, r.to_account}, r.occurred_at,
            r.occurred_at + horizon)

    out = []
    for cyc in found.values():
        accts = [c[0] for c in cyc]
        hours = (cyc[-1][2] - cyc[0][2]).total_seconds() / 3600
        ret = cyc[-1][3] / cyc[0][3]
        out.append(signal("G1", accts, [c[4] for c in cyc], cyc[0][2], cyc[-1][2], min(1.0, ret),
                          f"{rupees(cyc[0][3])} went round {len(cyc)} accounts and {ret:.0%} came back "
                          f"within {hours:.0f} h",
                          accounts=accts, hops=[{"from": c[0], "to": c[1], "t": c[2].isoformat(),
                                                 "amount": c[3], "txn": c[4]} for c in cyc],
                          retention=round(ret, 3), hours=round(hours, 1)))
    return out


# ── G2 rapid pass-through ──────────────────────────────────────────────────


def g2_pass_through(f: Frames) -> list[dict]:
    p = DETECTORS["G2"].params
    inside = internal_accounts(f)
    win = pd.Timedelta(minutes=p["window_min"])
    ins = f.txn[f.txn["to_account"].isin(inside) & (f.txn["amount"] >= p["min_inflow"])
                & ~f.txn["from_account"].isin(CASH)]
    outs = f.txn[f.txn["from_account"].isin(set(ins["to_account"]))].sort_values("occurred_at")
    out_by = {a: (g["occurred_at"].array.asi8, g["amount"].to_numpy().cumsum(), g)
              for a, g in outs.groupby("from_account")}
    hits = defaultdict(list)
    for r in ins.itertuples(index=False):
        ob = out_by.get(r.to_account)
        if ob is None:
            continue
        times, csum, g = ob
        lo = np.searchsorted(times, r.occurred_at.value, side="right")
        hi = np.searchsorted(times, (r.occurred_at + win).value, side="right")
        if hi <= lo:
            continue
        moved = csum[hi - 1] - (csum[lo - 1] if lo > 0 else 0)
        ratio = moved / r.amount
        if ratio >= p["ratio"]:
            hits[r.to_account].append((r, ratio, g.iloc[lo:hi]))
    out = []
    for acct, lst in hits.items():
        events = []
        for r, _, g in lst:
            events += [r.id, *g["id"]]
        ratios = [x[1] for x in lst]
        out.append(signal("G2", [acct], events, lst[0][0].occurred_at, lst[-1][2]["occurred_at"].max(),
                          min(1.0, 0.5 + 0.1 * len(lst)),
                          f"{len(lst)} inflow(s) moved on within {p['window_min']} min "
                          f"(median {np.median(ratios):.0%} of the inflow)",
                          account=acct, occurrences=len(lst), median_ratio=float(np.median(ratios))))
    return out


# ── G3 fan-in / fan-out ────────────────────────────────────────────────────


def g3_fan(f: Frames) -> list[dict]:
    p = DETECTORS["G3"].params
    inside = internal_accounts(f)
    win = pd.Timedelta(hours=p["window_h"])
    out = []
    for direction, key, other in (("fan-out", "from_account", "to_account"), ("fan-in", "to_account", "from_account")):
        t = f.txn[f.txn[key].isin(inside) & ~f.txn[other].isin(CASH) & (f.txn["kind"] != "UPI_PAY")
                  & (f.txn["kind"] != "UPI_CREDIT")]
        for acct, g in t.groupby(key):
            if len(g) < p["k"]:
                continue
            g = g.sort_values("occurred_at")
            times, cps = g["occurred_at"].tolist(), g[other].tolist()
            cnt: Counter = Counter()
            j, best = 0, (0, 0, 0)
            for i in range(len(g)):
                cnt[cps[i]] += 1
                while times[i] - times[j] > win:
                    cnt[cps[j]] -= 1
                    if cnt[cps[j]] == 0:
                        del cnt[cps[j]]
                    j += 1
                if len(cnt) > best[0]:
                    best = (len(cnt), j, i)
            if best[0] >= p["k"]:
                w = g.iloc[best[1]:best[2] + 1]
                out.append(signal("G3", [acct], w["id"].tolist()[:60], w["occurred_at"].min(),
                                  w["occurred_at"].max(), min(1.0, best[0] / 40),
                                  f"{direction}: {best[0]} distinct counterparties within {p['window_h']} h "
                                  f"({rupees(w['amount'].sum())})",
                                  account=acct, direction=direction, distinct=best[0],
                                  kinds=sorted(w["kind"].unique())))
    return out


# ── identity helpers ───────────────────────────────────────────────────────


def customer_devices(f: Frames) -> dict[str, set[str]]:
    s = f.session[(f.session["actor_type"] == "CUSTOMER") & f.session["device_id"].notna()]
    return s.groupby("actor_id")["device_id"].apply(set).to_dict()


# ── G4 mule factory ────────────────────────────────────────────────────────


def g4_mule_factory(f: Frames, pass_through: set[str]) -> list[dict]:
    p = DETECTORS["G4"].params
    end = f.window_end
    acc = f.account[(f.account["kind"] != "EXTERNAL") & f.account["kyc_approved_by"].notna()]
    recent = acc[(acc["opened_at"] >= end - pd.Timedelta(days=60)) & (acc["opened_at"] <= end)]
    hist = acc[(acc["opened_at"] < f.window_start) & (acc["opened_at"] >= f.window_start - pd.Timedelta(days=365))]
    devs = customer_devices(f)
    phone = f.customer.set_index("id")["phone_tok"]
    presence = f.work_item[f.work_item["kind"].isin(["TOKEN", "EKYC"])].groupby("customer_id")["created_at"].apply(list)
    out = []
    for emp, g in recent.groupby("kyc_approved_by"):
        n = len(g)
        base = max(len(hist[hist["kyc_approved_by"] == emp]) / 6.0, 0.5)
        pval = float(poisson.sf(n - 1, base))
        if pval >= p["burst_p"]:
            continue
        # identity graph among these accounts
        G = nx.Graph()
        for a in g.itertuples(index=False):
            G.add_node(a.id, kind="account")
            for d in devs.get(a.customer_id, set()):
                G.add_edge(a.id, f"dev:{d}")
            ph = phone.get(a.customer_id)
            if isinstance(ph, str):
                G.add_edge(a.id, f"ph:{ph}")
        shared_ids = [n_ for n_ in G.nodes if not str(n_).startswith("A-") and G.degree(n_) >= 2]
        shared_accts = sorted({nb for s in shared_ids for nb in G.neighbors(s)})
        if len(shared_accts) < p["min_shared"]:
            continue
        comms = nx.community.louvain_communities(G, seed=42)
        biggest = max(comms, key=lambda c: len([x for x in c if str(x).startswith("A-")]))
        presenceless = [a.id for a in g.itertuples(index=False)
                        if not any(abs(t - a.opened_at) <= pd.Timedelta(hours=24)
                                   for t in presence.get(a.customer_id, []))]
        cashout = sorted(set(g["id"]) & pass_through)
        out.append(signal(
            "G4", [emp, *g["id"], *[s.split(":", 1)[1] for s in shared_ids if s.startswith("dev:")]],
            g["id"], g["opened_at"].min(), end, min(1.0, 0.4 + len(shared_accts) / 10),
            f"{n} accounts KYC-approved in 60 days (baseline {base:.1f}); {len(shared_accts)} share "
            f"{len(shared_ids)} device/phone identifiers; {len(presenceless)} opened without the customer present",
            employee=emp, accounts=sorted(g["id"]), approvals_60d=n, baseline_60d=round(base, 1),
            burst_p=pval, shared_accounts=shared_accts,
            shared_identifiers=[s for s in shared_ids], presenceless=presenceless,
            pass_through_accounts=cashout,
            community=sorted(x for x in biggest if str(x).startswith("A-"))))
    return out


# ── G5 shared identifiers ──────────────────────────────────────────────────


def g5_shared(f: Frames, er_links: list[dict]) -> list[dict]:
    k = DETECTORS["G5"].params["min_customers"]
    out = []
    s = f.session[(f.session["actor_type"] == "CUSTOMER") & f.session["device_id"].notna()]
    by_dev = s.groupby("device_id")["actor_id"].apply(lambda x: sorted(set(x)))
    for dev, custs in by_dev.items():
        if len(custs) >= k:
            out.append(signal("G5", [dev, *custs], [], s["started_at"].min(), s["started_at"].max(),
                              min(1.0, len(custs) / 6), f"Device {dev} used by {len(custs)} different customers",
                              kind="device", identifier=dev, customers=custs))
    by_phone = f.customer.dropna(subset=["phone_tok"]).groupby("phone_tok")["id"].apply(sorted)
    for _phone, custs in by_phone.items():
        if len(custs) >= k:
            out.append(signal("G5", custs, [], f.window_start, f.window_end, min(1.0, len(custs) / 6),
                              f"One phone number registered to {len(custs)} customers",
                              kind="phone", customers=custs))
    for link in er_links:
        if link["declared"]:
            continue
        out.append(signal("G5", [link["employee_id"], link["customer_id"]], [], f.window_start, f.window_end,
                          link["score"], f"Employee HR record matches customer {link['customer_id']} "
                          f"(address {link['fields']['address']}, surname {link['fields']['surname']})",
                          kind="employee_customer", **link))
    return out
