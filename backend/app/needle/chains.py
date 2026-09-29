"""Needle — stitches signals and events into time-ordered chains.

Hop grammar for insider chains (each hop within 72 h of the previous):

    E0 entitlement grant (precursor) → E1 staff login → E2 record viewed → E3 state change
    → E4 digital takeover (new device / password reset / new payees) → E5 payouts to new payees
    → E5′ forwarding downstream → E6 money loops back

A chain is emitted only when it reaches money (E5). Access without money is a signal, not
a chain — that structural filter is what keeps honest-but-unusual work out of the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.loom.frames import Frames
from app.needle.detectors.rules import rupees

HOP = pd.Timedelta(hours=72)
ROOT_FIELDS = {"REGISTERED_MOBILE", "TXN_LIMIT", "EMAIL"}
OUT_CHANNELS = {"IMPS", "UPI", "NEFT", "RTGS"}


@dataclass
class Link:
    code: str
    event_type: str
    event_id: str
    t: pd.Timestamp
    title: str
    detail: str
    lane: str
    amount: float | None = None
    refs: list[str] = field(default_factory=list)  # every source row behind this link
    alibi: dict | None = None


@dataclass
class ChainDraft:
    kind: str
    root_ref: str
    employee_id: str | None
    account_id: str | None
    links: list[Link]
    amount_at_risk: float
    latency_s: int | None
    features: dict
    entities: set[str]
    context: dict = field(default_factory=dict)

    @property
    def first_t(self) -> pd.Timestamp:
        return min(link.t for link in self.links)

    @property
    def last_t(self) -> pd.Timestamp:
        return max(link.t for link in self.links)


class Index:
    """Per-entity lookups built once per pipeline run."""

    def __init__(self, f: Frames, ex: pd.DataFrame):
        self.f = f
        self.ex = ex.set_index("access_event_id")
        self.acc = f.account.set_index("id")
        self.cust = f.customer.set_index("id")
        self.emp = f.employee.set_index("id")
        self.dev = f.device.set_index("id")
        self.sess = f.session.set_index("id")
        self.txn_out = {a: g.sort_values("occurred_at") for a, g in f.txn.groupby("from_account")}
        self.txn_in = {a: g.sort_values("occurred_at") for a, g in f.txn.groupby("to_account")}
        self.ben = {a: g.sort_values("added_at") for a, g in f.beneficiary.groupby("account_id")}
        self.sc = {a: g.sort_values("occurred_at") for a, g in f.state_change.groupby("account_id")}
        cs = f.session[f.session["actor_type"] == "CUSTOMER"]
        self.cust_sess = {c: g.sort_values("started_at") for c, g in cs.groupby("actor_id")}
        self.acc_by_emp_session = {s: g.sort_values("occurred_at")
                                   for s, g in f.access_event.groupby("session_id")}
        self.empty_txn = f.txn.iloc[0:0]

    def outflows(self, acct: str, after: pd.Timestamp, until: pd.Timestamp) -> pd.DataFrame:
        g = self.txn_out.get(acct, self.empty_txn)
        return g[(g["occurred_at"] > after) & (g["occurred_at"] <= until)]

    def holder(self, acct: str) -> str:
        return self.acc.at[acct, "holder_name"] if acct in self.acc.index else acct

    def is_internal(self, acct: str) -> bool:
        return acct in self.acc.index and self.acc.at[acct, "kind"] != "EXTERNAL"

    def new_device(self, sess_row) -> bool:
        d = sess_row["device_id"]
        if d is None or d not in self.dev.index:
            return False
        return abs((sess_row["started_at"] - self.dev.at[d, "first_seen"]).total_seconds()) <= 600


def _alibi_card(ix: Index, access_id: str) -> dict | None:
    if access_id not in ix.ex.index:
        return None
    r = ix.ex.loc[access_id]
    return {"verdict": r["verdict"], "purpose_ok": bool(r["purpose_ok"]),
            "timing_ok": bool(r["timing_ok"]), "checked": r["checked"],
            "reasons_found": int(sum(1 for c in r["checked"] if c["ok"]))}


def _downstream(ix: Index, recipients: list[tuple[str, pd.Timestamp, float]], chain_accts: set[str],
                links: list[Link], depth: int = 2) -> tuple[float, list[str]]:
    """Follow internal recipients' outflows (≥10% of what they received) for up to `depth` hops."""
    forwarded, loop_refs = 0.0, []
    frontier = recipients
    seen = set()
    for level in range(depth):
        nxt = []
        for acct, t_in, amt_in in frontier:
            if not ix.is_internal(acct) or acct in seen:
                continue
            seen.add(acct)
            outs = ix.outflows(acct, t_in, t_in + HOP)
            outs = outs[outs["amount"] >= 0.1 * amt_in]
            if outs.empty:
                continue
            transfers = outs[outs["to_account"] != "X-ATM"]
            cash = outs[outs["to_account"] == "X-ATM"]
            if level == 0:
                forwarded += float(outs["amount"].sum())
            for r in transfers.itertuples(index=False):
                if r.to_account in chain_accts and r.to_account != acct:
                    loop_refs.append(r.id)
                    links.append(Link("E6", "TXN", r.id, r.occurred_at, "Loop closes",
                                      f"{rupees(r.amount)} back from {r.from_account} to {r.to_account}",
                                      "AML", r.amount, [r.id]))
                else:
                    links.append(Link("E5′", "TXN", r.id, r.occurred_at, "Forwarded",
                                      f"{rupees(r.amount)} {r.from_account} → {r.to_account} "
                                      f"({ix.holder(r.to_account)})", "AML", r.amount, [r.id]))
                    nxt.append((r.to_account, r.occurred_at, r.amount))
                    chain_accts.add(r.to_account)
            if not cash.empty:
                links.append(Link("E5′", "TXN", cash["id"].iloc[0], cash["occurred_at"].iloc[0], "Cash-out",
                                  f"{rupees(cash['amount'].sum())} withdrawn at ATMs from {acct}", "AML",
                                  float(cash["amount"].sum()), cash["id"].tolist()))
        frontier = nxt
    return forwarded, loop_refs


# ── insider chains ─────────────────────────────────────────────────────────


def insider_chains(ix: Index, only_accounts: set[str] | None = None) -> list[ChainDraft]:
    """Roots: staff state changes whose performing access is not fully explained by Alibi."""
    f = ix.f
    ae = f.access_event[f.access_event["action"].isin(["MOBILE_UPDATE", "LIMIT_CHANGE", "ADDRESS_UPDATE"])]
    if only_accounts is not None:
        ae = ae[ae["account_id"].isin(only_accounts)]
    ae = ae[ae["id"].isin(ix.ex.index)]
    ae = ae[ix.ex.loc[ae["id"], "verdict"].to_numpy() != "EXPLAINED"].sort_values("occurred_at")
    drafts = []
    done: set[tuple[str, str]] = set()
    for act in ae.itertuples(index=False):
        key = (act.employee_id, act.account_id)
        if key in done:
            continue
        changes = ix.sc.get(act.account_id)
        if changes is None:
            continue
        root = changes[(changes["actor_id"] == act.employee_id) & changes["field"].isin(ROOT_FIELDS)
                       & ((changes["occurred_at"] - act.occurred_at).abs() <= pd.Timedelta(seconds=60))]
        if root.empty:
            continue
        card = _alibi_card(ix, act.id)
        d = _build_insider(ix, next(root.itertuples(index=False)), pd.Series(act._asdict()), card)
        if d is not None:
            drafts.append(d)
            done.add(key)
    return drafts


def _build_insider(ix: Index, root, act, card) -> ChainDraft | None:
    f = ix.f
    emp, acct = root.actor_id, root.account_id
    t0 = root.occurred_at
    cust = ix.acc.at[acct, "customer_id"]
    links: list[Link] = []
    feats: dict = {}

    # all employee changes to this account within 2 h (e.g. mobile, then limit)
    changes = ix.sc.get(acct, f.state_change.iloc[0:0])
    changes = changes[(changes["actor_id"] == emp) & (changes["occurred_at"] >= t0)
                      & (changes["occurred_at"] <= t0 + pd.Timedelta(hours=2))]
    after_changes = changes["occurred_at"].max()

    # money must move: new payees added after the change, paid within the hop window
    ben = ix.ben.get(acct, f.beneficiary.iloc[0:0])
    new_payees = ben[(ben["added_at"] > t0) & (ben["added_at"] <= after_changes + HOP)]
    if new_payees.empty:
        return None
    pay = ix.outflows(acct, t0, new_payees["added_at"].max() + HOP)
    pay = pay[pay["to_account"].isin(new_payees["counterparty_account"])
              & pay["channel"].isin(OUT_CHANNELS)]
    if pay.empty:
        return None

    # E0: the entitlement that authorised an override, if it had expired
    overrides = changes[changes["auth_method"] == "OVERRIDE"]
    if len(overrides):
        ent = f.entitlement[(f.entitlement["employee_id"] == emp)
                            & (f.entitlement["permission_code"] == "MOBILE_UPDATE_OVERRIDE")
                            & (f.entitlement["valid_from"] <= t0)
                            & (f.entitlement["revoked_at"].isna() | (f.entitlement["revoked_at"] > t0))]
        if not ent.empty:
            g = ent.sort_values("valid_from").iloc[-1]
            expired = pd.notna(g["intended_expiry"]) and g["intended_expiry"] < t0
            feats["expired_entitlement"] = int(expired)
            links.append(Link("E0", "ENTITLEMENT", g["id"], g["valid_from"],
                              "Temp override granted" if expired else "Override entitlement",
                              f"{g['permission_code']} via {g['request_ref'] or 'role baseline'}"
                              + (f"; meant to expire {g['intended_expiry']:%d %b}, never revoked" if expired else ""),
                              "IAM", None, [g["id"]]))

    # E1 / E2: the staff session and what was viewed in it
    sid = act["session_id"]
    sess = ix.sess.loc[sid] if isinstance(sid, str) and sid in ix.sess.index else None
    session_accesses = ix.acc_by_emp_session.get(sid, f.access_event.iloc[0:0]) if sess is not None else f.access_event.iloc[0:0]
    if sess is not None:
        t_login = sess["started_at"]
        login_card = _alibi_card(ix, act["id"])
        links.append(Link("E1", "SESSION", sid, t_login,
                          "Off-hours login" if not card["timing_ok"] else "Staff login",
                          f"{sess['channel']} session from {sess['device_id']} ({sess['geo_city']})",
                          "SOC", None, [sid], login_card))
    else:
        t_login = act["occurred_at"]
    views = session_accesses[(session_accesses["account_id"] == acct) & (session_accesses["action"] == "ACCT_VIEW")
                             & (session_accesses["occurred_at"] <= t0)]
    if not views.empty:
        v = views.iloc[0]
        vcard = _alibi_card(ix, v["id"])
        found = vcard["reasons_found"] if vcard else 0
        links.append(Link("E2", "ACCESS", v["id"], v["occurred_at"], "Account viewed",
                          f"{acct} ({ix.acc.at[acct, 'status'].lower()}) · alibi {found} of 5",
                          "SOC", None, [v["id"]], vcard))

    # E3: state changes
    for i, c in enumerate(changes.itertuples(index=False)):
        if c.field == "REGISTERED_MOBILE":
            title, detail = "Mobile no. changed", f"{c.old_value} → {c.new_value} · auth {c.auth_method}"
        elif c.field == "TXN_LIMIT":
            title, detail = "Limit raised", f"{rupees(float(c.old_value) / 100)} → {rupees(float(c.new_value) / 100)} · auth {c.auth_method}"
        else:
            title, detail = f"{c.field.title()} changed", f"auth {c.auth_method}"
        acc_row = session_accesses[(session_accesses["occurred_at"] - c.occurred_at).abs() <= pd.Timedelta(seconds=60)]
        a_id = acc_row["id"].iloc[0] if not acc_row.empty else None
        links.append(Link("E3" if i == 0 else "E3′", "STATE_CHANGE", c.id, c.occurred_at, title, detail, "SOC",
                          None, [c.id] + ([a_id] if a_id else []), _alibi_card(ix, a_id) if a_id else None))

    # E4: digital takeover
    csess = ix.cust_sess.get(cust)
    takeover_sess = None
    if csess is not None:
        cand = csess[(csess["started_at"] > t0) & (csess["started_at"] <= new_payees["added_at"].max())]
        for _, s in cand.iterrows():
            if ix.new_device(s):
                takeover_sess = s
                break
    pw = ix.sc.get(acct, f.state_change.iloc[0:0])
    pw = pw[(pw["field"] == "PASSWORD") & (pw["occurred_at"] > t0) & (pw["occurred_at"] <= new_payees["added_at"].max())]
    t4 = new_payees["added_at"].min()
    detail = f"{len(new_payees)} new payee(s)"
    if takeover_sess is not None:
        detail += f" · new device {takeover_sess['device_id']}"
    if not pw.empty:
        detail += " · password reset"
    links.append(Link("E4", "BENEFICIARY", new_payees["id"].iloc[0], t4,
                      f"{len(new_payees)} payee{'s' if len(new_payees) > 1 else ''} added", detail, "FRAUD", None,
                      new_payees["id"].tolist() + pw["id"].tolist()
                      + ([takeover_sess.name] if takeover_sess is not None else [])))

    # E5: payouts
    amt = float(pay["amount"].sum())
    links.append(Link("E5", "TXN", pay["id"].iloc[0], pay["occurred_at"].min(),
                      f"{rupees(amt)} out",
                      f"{len(pay)} × {rupees(pay['amount'].iloc[0])} via {pay['channel'].iloc[0]} to "
                      + ", ".join(pay["to_account"].tolist()), "FRAUD", amt, pay["id"].tolist()))

    chain_accts = {acct, *pay["to_account"]}
    recips = [(r.to_account, r.occurred_at, r.amount) for r in pay.itertuples(index=False)]
    forwarded, loop_refs = _downstream(ix, recips, chain_accts, links)

    # relationships: recipients the employee KYC-approved
    approved = [a for a in pay["to_account"] if ix.is_internal(a) and ix.acc.at[a, "kyc_approved_by"] == emp]

    balance_before = float(ix.acc.at[acct, "balance_paise"]) / 100 + amt
    latency = int((pay["occurred_at"].min() - t_login).total_seconds())
    limit_ratio = 0.0
    lim = changes[changes["field"] == "TXN_LIMIT"]
    if not lim.empty:
        limit_ratio = float(pay["amount"].max() / (float(lim["new_value"].iloc[-1]) / 100))
    feats.update({
        "latency_min": latency / 60,
        "override": int(len(overrides) > 0),
        "purpose_explained": int(card["purpose_ok"]),
        "timing_explained": int(card["timing_ok"]),
        "new_device": int(takeover_sess is not None),
        "password_reset": int(not pw.empty),
        "n_new_payees": int(len(new_payees)),
        "limit_ratio": round(limit_ratio, 3),
        "amount_to_balance": round(amt / max(balance_before, 1), 3),
        "pass_through": round(forwarded / max(amt, 1), 3),
        "dormant": int(ix.acc.at[acct, "status"] == "INOPERATIVE"),
        "recipients_approved_by_employee": int(len(approved) > 0),
        "loop": int(len(loop_refs) > 0),
        "night": int(t_login.hour >= 20 or t_login.hour < 6),
    })
    feats.setdefault("expired_entitlement", 0)
    links.sort(key=lambda link: (link.t, link.code))
    ents = {emp, acct, cust, *chain_accts}
    if takeover_sess is not None:
        ents.add(takeover_sess["device_id"])
    return ChainDraft("INSIDER_ATO", act["id"], emp, acct, links, amt, latency, feats, ents,
                      {"approved_recipients": approved, "forwarded": forwarded,
                       "session_id": sid, "root_access": act["id"], "changes": changes["id"].tolist()
                       if "id" in changes else []})


# ── external (customer-side) takeover chains ───────────────────────────────


def external_chains(ix: Index, covered_accounts: set[str]) -> list[ChainDraft]:
    f = ix.f
    sc = f.state_change[(f.state_change["actor_type"] == "CUSTOMER")
                        & f.state_change["field"].isin(["PASSWORD", "REGISTERED_MOBILE", "DEVICE_BINDING"])]
    drafts = []
    for root in sc.itertuples(index=False):
        acct = root.account_id
        if acct in covered_accounts or not isinstance(root.session_id, str) or root.session_id not in ix.sess.index:
            continue
        s = ix.sess.loc[root.session_id]
        if not ix.new_device(s):
            continue
        t0 = root.occurred_at
        ben = ix.ben.get(acct, f.beneficiary.iloc[0:0])
        new_payees = ben[(ben["added_at"] >= s["started_at"]) & (ben["added_at"] <= t0 + pd.Timedelta(hours=24))]
        if new_payees.empty:
            continue
        pay = ix.outflows(acct, t0, t0 + pd.Timedelta(hours=24))
        pay = pay[pay["to_account"].isin(new_payees["counterparty_account"])]
        if pay.empty:
            continue
        cust = ix.acc.at[acct, "customer_id"]
        usual_city = ix.cust.at[cust, "address_norm"].split()[-2] if cust in ix.cust.index else ""
        links = [
            Link("E1", "SESSION", root.session_id, s["started_at"], "New-device login",
                 f"{s['channel']} from never-seen {s['device_id']} in {s['geo_city']}", "FRAUD", None,
                 [root.session_id]),
            Link("E2", "STATE_CHANGE", root.id, t0, f"{root.field.replace('_', ' ').title()}",
                 f"auth {root.auth_method}", "FRAUD", None, [root.id]),
            Link("E4", "BENEFICIARY", new_payees["id"].iloc[0], new_payees["added_at"].min(),
                 f"{len(new_payees)} payee(s) added", ", ".join(new_payees["counterparty_account"]), "FRAUD",
                 None, new_payees["id"].tolist()),
        ]
        amt = float(pay["amount"].sum())
        links.append(Link("E5", "TXN", pay["id"].iloc[0], pay["occurred_at"].min(), f"{rupees(amt)} out",
                          f"{len(pay)} transfers to new payees", "FRAUD", amt, pay["id"].tolist()))
        lookup_limit = float(ix.acc.at[acct, "daily_limit_paise"]) / 100
        latency = int((pay["occurred_at"].min() - s["started_at"]).total_seconds())
        feats = {"latency_min": latency / 60, "override": 0, "purpose_explained": 1, "timing_explained": 1,
                 "new_device": 1, "password_reset": int(root.field == "PASSWORD"),
                 "n_new_payees": int(len(new_payees)),
                 "limit_ratio": round(float(pay["amount"].max()) / max(lookup_limit, 1), 3),
                 "amount_to_balance": round(amt / max(float(ix.acc.at[acct, "balance_paise"]) / 100 + amt, 1), 3),
                 "pass_through": 0.0, "dormant": int(ix.acc.at[acct, "status"] == "INOPERATIVE"),
                 "recipients_approved_by_employee": 0, "loop": 0, "expired_entitlement": 0,
                 "geo_change": int(s["geo_city"] not in (usual_city.title(), "Pune", "Nashik")
                                   and s["geo_city"] != ix.cust.at[cust, "address_norm"]),
                 "night": int(s["started_at"].hour < 6)}
        drafts.append(ChainDraft("EXTERNAL_ATO", root.id, None, acct, links, amt, latency, feats,
                                 {acct, cust, s["device_id"], *pay["to_account"]}))
        covered_accounts.add(acct)
    return drafts


# ── network chains from graph / rule signals ───────────────────────────────


def circular_chains(ix: Index, g1: list[dict]) -> list[ChainDraft]:
    out = []
    for s in g1:
        p = s["payload"]
        links = [Link(f"H{i + 1}", "TXN", h["txn"], pd.Timestamp(h["t"]).tz_convert("Asia/Kolkata"),
                      f"{rupees(h['amount'])} hop", f"{h['from']} → {h['to']} ({ix.holder(h['to'])})", "AML",
                      h["amount"], [h["txn"]]) for i, h in enumerate(p["hops"])]
        out.append(ChainDraft("CIRCULAR", s["event_refs"][0], None, p["accounts"][0], links,
                              float(p["hops"][0]["amount"]), int(p["hours"] * 3600),
                              {"retention": p["retention"], "hours": p["hours"], "hops": len(p["hops"])},
                              set(p["accounts"]), {"signal": s}))
    return out


def structuring_chains(ix: Index, r1: list[dict]) -> list[ChainDraft]:
    f = ix.f
    out = []
    t = f.txn.set_index("id")
    for s in r1:
        p = s["payload"]
        deps = t.loc[s["event_refs"]].sort_values("occurred_at")
        links = [Link(f"D{i + 1}", "TXN", tid, r["occurred_at"], f"{rupees(r['amount'])} cash",
                      f"{r['to_account']} at {r['branch_id']}", "AML", float(r["amount"]), [tid])
                 for i, (tid, r) in enumerate(deps.iterrows())]
        last = deps["occurred_at"].max()
        outs = pd.concat([ix.outflows(a, last, last + HOP) for a in p["accounts"]])
        outs = outs[outs["channel"].isin(OUT_CHANNELS)]
        if not outs.empty:
            links.append(Link("C1", "TXN", outs["id"].iloc[0], outs["occurred_at"].min(), "Consolidated out",
                              f"{rupees(outs['amount'].sum())} to {', '.join(sorted(outs['to_account'].unique()))}",
                              "AML", float(outs["amount"].sum()), outs["id"].tolist()))
        out.append(ChainDraft("STRUCTURING", s["event_refs"][0], None, p["accounts"][0], links,
                              float(p["total"]), int((last - deps["occurred_at"].min()).total_seconds()),
                              {"deposits": len(deps), "branches": len(p["branches"]), "accounts": len(p["accounts"]),
                               "consolidated": float(outs["amount"].sum()) if not outs.empty else 0.0},
                              set(p["accounts"]) | {p["person"]} | set(outs["to_account"]), {"signal": s}))
    return out


def mule_factory_chains(ix: Index, g4: list[dict], insider: list[ChainDraft]) -> list[ChainDraft]:
    out = []
    for s in g4:
        p = s["payload"]
        accts = ix.acc.loc[p["accounts"]].sort_values("opened_at")
        emp = p["employee"]
        links = [Link("F1", "ACCOUNT", accts.index[0], accts["opened_at"].iloc[0], "Openings begin",
                      f"{accts.index[0]} opened and KYC-approved by {emp}", "SOC", None, [accts.index[0]])]
        if len(accts) > 2:
            links.append(Link("F2", "ACCOUNT", accts.index[len(accts) // 2], accts["opened_at"].iloc[len(accts) // 2],
                              f"{len(accts)} openings in 60 days",
                              f"baseline {p['baseline_60d']} per 60 days · {len(p['presenceless'])} without customer present",
                              "SOC", None, list(accts.index)))
        links.append(Link("F3", "IDENTITY", p["shared_identifiers"][0] if p["shared_identifiers"] else accts.index[0],
                          accts["opened_at"].iloc[-1], "Shared identifiers",
                          f"{len(p['shared_accounts'])} accounts share {len(p['shared_identifiers'])} devices/phones",
                          "FRAUD", None, p["shared_accounts"]))
        inflow = sum(float(ix.txn_in.get(a, ix.empty_txn)["amount"].sum()) for a in p["accounts"])
        links.append(Link("F4", "TXN", accts.index[0], s["window_end"], "Fan-in → cash-out",
                          f"{rupees(inflow)} received across the cluster; {len(p['pass_through_accounts'])} "
                          "accounts pass money on within an hour", "AML", inflow, []))
        linked = [c for c in insider if set(p["accounts"]) & c.entities]
        for c in linked:
            e5 = next((lk for lk in c.links if lk.code == "E5"), None)
            if e5:
                links.append(Link("F5", "CHAIN", e5.event_id, e5.t, "Receives takeover money",
                                  f"{e5.detail}", "AML", e5.amount, e5.refs))
        links.sort(key=lambda lk: lk.t)
        out.append(ChainDraft("MULE_FACTORY", f"G4:{emp}", emp, accts.index[0], links, inflow, None,
                              {"approvals": p["approvals_60d"], "baseline": p["baseline_60d"],
                               "shared": len(p["shared_accounts"]), "presenceless": len(p["presenceless"]),
                               "pass_through": len(p["pass_through_accounts"])},
                              set(p["accounts"]) | {emp}, {"signal": s, "linked_chains": linked}))
    return out


def feature_vector(d: ChainDraft, names: list[str]) -> np.ndarray:
    return np.array([float(d.features.get(n, 0.0)) for n in names])
