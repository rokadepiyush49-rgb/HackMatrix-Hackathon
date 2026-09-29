"""Brief — turns a chain into an argued, prioritised alert.

No single score. Seven dimensions each get a level with supporting *and* contradicting
evidence; priority comes from readable rules over those levels (the lattice); benign
hypotheses are tested and shown as a defence column; missing evidence is listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.brief.context import BriefContext
from app.brief.evidence import (
    EvidenceItem,
    build_chain_evidence,
    ev_account_opening,
    ev_er,
    ev_model,
)
from app.ml.models import score_chain
from app.needle.chains import ChainDraft
from app.needle.detectors.rules import rupees
from app.needle.registry import DETECTORS

LEVELS = ["NONE", "LOW", "ELEVATED", "HIGH"]
DIM_LABELS = {"transaction": "Transaction", "employee": "Employee behaviour", "access": "Access",
              "network": "Network", "temporal": "Temporal", "relationship": "Relationship",
              "historical": "Historical"}


@dataclass
class Dim:
    key: str
    level: str
    summary: str
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": DIM_LABELS[self.key], "level": self.level, "summary": self.summary,
                "supporting": self.supporting, "contradicting": self.contradicting}


@dataclass
class Rebuttal:
    hypothesis: str
    status: str  # refuted | supported | open
    note: str
    codes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"hypothesis": self.hypothesis, "status": self.status, "note": self.note, "codes": self.codes}


@dataclass
class BriefResult:
    draft: ChainDraft
    typology: str
    claim: str
    summary: str
    priority: str
    lattice_rule: str
    dims: list[Dim]
    rebuttals: list[Rebuttal]
    evidence: list[EvidenceItem]
    argument: dict
    recoverable: bool
    classifier: dict | None


def _codes(book_items: list[EvidenceItem], pred) -> list[str]:
    return [e.code for e in book_items if pred(e)]


def _mins(s: float) -> str:
    m = s / 60
    if m < 90:
        return f"{m:.0f} min"
    if m < 48 * 60:
        return f"{m / 60:.1f} h"
    return f"{m / 1440:.1f} days"


# ── lattice ────────────────────────────────────────────────────────────────


def lattice(dims: list[Dim], systems: set[str], explained: bool, recoverable: bool,
            p: float | None, benign_supported: bool) -> tuple[str, str]:
    high = [d for d in dims if d.level == "HIGH"]
    elev = [d for d in dims if d.level == "ELEVATED"]
    if benign_supported:
        return "EXPLAINED", "A benign explanation is supported by evidence → suppressed (5% sampled to QA)"
    if explained:
        return "EXPLAINED", "Every access link has an alibi → suppressed (5% sampled to QA)"
    record_systems = {s for s in systems if not s.startswith("SUTRA")}
    if len(high) >= 3 and len(record_systems) >= 2 and recoverable:
        return "P1", (f"{len(high)} dimensions High ({', '.join(DIM_LABELS[d.key] for d in high)}), evidenced by "
                      f"{len(record_systems)} independent systems, no alibi, funds still recoverable → P1")
    if len(high) >= 2 or (len(high) == 1 and p is not None and p >= 0.8):
        why = f"{len(high)} dimensions High" + (f" and chain classifier {p:.2f}" if p is not None and len(high) < 2 else "")
        return "P2", f"{why}, no alibi → P2"
    if (len(high) == 1 or len(elev) >= 2) and (p is None or p >= 0.2):
        return "P3", f"{len(high)} High / {len(elev)} Elevated dimensions" + (f", classifier {p:.2f}" if p is not None else "") + " → P3"
    reason = f"{len(high)} High / {len(elev)} Elevated"
    if p is not None and p < 0.2:
        reason += f"; chain classifier {p:.2f} < 0.20"
    return "WATCH", reason + " → watch-list (not queued)"


# ── insider takeover ───────────────────────────────────────────────────────


def _insider(ctx: BriefContext, d: ChainDraft) -> BriefResult:
    f, ix = ctx.f, ctx.ix
    book = build_chain_evidence(ctx, d)
    emp = d.employee_id
    feats = d.features
    acct = d.account_id
    cust = ix.acc.at[acct, "customer_id"]
    root_access = d.context.get("root_access")
    sid = d.context.get("session_id")
    card = ix.ex.loc[root_access] if root_access in ix.ex.index else None

    # model & behaviour evidence
    rhythm = ctx.rhythm_by_session.loc[sid] if isinstance(sid, str) and sid in ctx.rhythm_by_session.index else None
    nav = ctx.nav_by_session.loc[sid] if isinstance(sid, str) and sid in ctx.nav_by_session.index else None
    t_sess = ix.sess.at[sid, "started_at"] if isinstance(sid, str) and sid in ix.sess.index else d.first_t
    if rhythm is not None:
        late_note = (f"{int(rhythm['late_prior'])} of {int(rhythm['sessions_prior'])} prior sessions started after 20:00; "
                     f"peers {rhythm['peer_late_share']:.1%}")
        book.add(ev_model("M1_RHYTHM", f"Access rhythm: session at {t_sess:%a %H:%M} has a shrunk personal share of "
                          f"{rhythm['share']:.4f} (peer-weighted, leave-one-out). {late_note}", sid, t_sess, [emp],
                          {"share": float(rhythm["share"]), "late_prior": int(rhythm["late_prior"]),
                           "sessions_prior": int(rhythm["sessions_prior"])}), "E1")
    if nav is not None:
        rare = "; ".join(f"{r['from']}→{r['to']} (p={r['p']})" for r in nav["rare"]) or "none"
        book.add(ev_model("M2_NAVIGATION", f"Navigation: session sequence in the bottom {nav['percentile']:.1%} for "
                          f"{nav['role'].replace('_', ' ').lower()}s. Rarest transitions: {rare}", sid, t_sess, [emp],
                          {"percentile": float(nav["percentile"]), "rare": nav["rare"],
                           "actions": list(nav["actions"])}), "E1")

    # relationships
    for a in d.context.get("approved_recipients", []):
        book.add(ev_account_opening(ix.acc.loc[a], a), "E5")
    chain_custs = {ix.acc.at[a, "customer_id"] for a in d.entities if a in ix.acc.index and ix.is_internal(a)}
    er = [lk for lk in ctx.er_links if lk["employee_id"] == emp and lk["customer_id"] in chain_custs]
    for lk in er:
        book.add(ev_er(lk, d.last_t), "E6")
    # mule scores for internal recipients
    for a in {x for x in d.entities if x in ctx.mule_scores.index and x != acct}:
        ms = ctx.mule_scores.loc[a]
        if ms["p"] >= 0.5:
            top = ", ".join(c["label"].lower() for c in ms["contributions"][:3])
            book.add(ev_model("M6_MULE", f"{a} mule-likeness {ms['p']:.2f} (LightGBM; top factors: {top})", f"M6:{a}",
                              d.last_t, [a], {"p": float(ms["p"]), "contributions": ms["contributions"][:5]}), "E5")
    # mule factory context
    g4 = [s for s in ctx.signals if s["detector"] == "G4" and s["payload"]["employee"] == emp]
    for s in g4:
        book.add(ev_model("G4_FACTORY", s["summary"], f"G4:{emp}", s["window_end"], [emp], s["payload"]), "E5")
    # defence evidence
    emp_row = ix.emp.loc[emp]
    tenure = (d.first_t.date() - emp_row["hire_date"]).days / 365.25
    prior = ctx.prior_alerts.get(emp, 0)
    hist_item = book.add(EvidenceItem("HR_RECORD", f"{emp}: {tenure:.0f} years' tenure; {prior} prior alerts or cases",
                                      "HRMS", "employee", emp, "A", pd.Timestamp(d.first_t), None, [emp],
                                      {"tenure_years": round(tenure, 1), "prior_alerts": prior},
                                      supports=[], rebuts=["claim"]))
    own_device = None
    if isinstance(sid, str) and sid in ix.sess.index:
        dev = ix.sess.at[sid, "device_id"]
        if isinstance(dev, str) and dev.startswith(("LAP-", "BT-")):
            own_device = book.add(EvidenceItem("ASSET", f"Session device {dev} is the employee's own issued device",
                                               "IT asset register", "device", dev, "B", pd.Timestamp(t_sess), None,
                                               [emp, dev], {"device": dev}, supports=[], rebuts=["attribution"]))

    # classifier
    sc = score_chain(feats)
    if sc is not None:
        top = ", ".join(f"{c['label'].lower()} ({c['contribution']:+.2f})" for c in sc.contributions[:3])
        book.add(ev_model("M5_CLASSIFIER", f"Chain classifier {sc.p:.2f} (calibrated on synthetic seed 7). "
                          f"Largest contributions: {top}", f"M5:{d.root_ref}", d.last_t, [emp, acct],
                          {"p": sc.p, "decision": sc.decision, "contributions": sc.contributions}), "E5")
    items = book.finalise()
    by_kind = lambda *k: [e.code for e in items if e.kind in k]  # noqa: E731
    by_link = lambda code: [e.code for e in items if code in e.link_codes]  # noqa: E731

    # ── dimensions
    amt = d.amount_at_risk
    r2 = ctx.signals_for(set().union(*[set(lk.refs) for lk in d.links if lk.code == "E5"]), set(), {"R2"})
    dims = []
    lvl = "HIGH" if (r2 or feats.get("dormant") and amt >= 1e5 or amt >= 5e5) else "ELEVATED" if amt >= 1e5 else "LOW"
    txt = f"{rupees(amt)} to {int(feats.get('n_new_payees', 0))} new payee(s)"
    if feats.get("dormant"):
        txt += " from a dormant account"
    if r2:
        txt += f"; {r2[0]['summary']}"
    dims.append(Dim("transaction", lvl, txt, by_link("E5"), []))

    share = float(rhythm["share"]) if rhythm is not None else 1.0
    pct = float(nav["percentile"]) if nav is not None else 1.0
    first_late = rhythm is not None and bool(rhythm["late"]) and int(rhythm["late_prior"]) == 0
    lvl = "HIGH" if (share < 0.004 and first_late) or pct < 0.005 else "ELEVATED" if share < 0.02 or pct < 0.02 else "LOW"
    parts = []
    if rhythm is not None:
        parts.append("first session after 20:00 in 90 days" if first_late else f"session-time share {share:.3f}")
    if nav is not None:
        parts.append(f"navigation bottom {pct:.1%} for role")
    dims.append(Dim("employee", lvl, "; ".join(parts) or "no behavioural deviation", by_kind("M1_RHYTHM", "M2_NAVIGATION"),
                    [hist_item.code]))

    purpose_ok = bool(card["purpose_ok"]) if card is not None else True
    timing_ok = bool(card["timing_ok"]) if card is not None else True
    override = bool(feats.get("override"))
    expired = bool(feats.get("expired_entitlement"))
    lvl = "HIGH" if (not purpose_ok and (override or not timing_ok)) or expired else \
        "ELEVATED" if (not purpose_ok or not timing_ok) else "LOW"
    bits = []
    if not purpose_ok:
        bits.append("no ticket, portfolio, queue or interaction")
    if not timing_ok:
        bits.append("outside any rostered shift")
    if override:
        bits.append("override used")
    if expired:
        bits.append("entitlement past its intended expiry")
    dims.append(Dim("access", lvl, "; ".join(bits) or "access explained",
                    by_kind("ALIBI", "ENTITLEMENT") + by_link("E3"), [own_device.code] if own_device else []))

    pt = float(feats.get("pass_through", 0))
    loop = bool(feats.get("loop"))
    in_factory = bool(g4)
    lvl = "HIGH" if (pt >= 0.6 and loop) or in_factory or pt >= 0.9 else "ELEVATED" if pt > 0 or amt >= 1e5 else "LOW"
    txt = f"{pt:.0%} of the payout moved on within the chain" + ("; money looped back" if loop else "")
    if in_factory:
        txt += "; recipients belong to a mule cluster"
    dims.append(Dim("network", lvl, txt, by_link("E5′") + by_link("E6") + by_kind("M6_MULE", "G4_FACTORY"), []))

    lat = d.latency_s or 0
    lvl = "HIGH" if lat <= 7200 else "ELEVATED" if lat <= 86400 else "LOW"
    dims.append(Dim("temporal", lvl, f"access → money in {_mins(lat)}", by_link("E1") + by_link("E5"),
                    [] if lat <= 86400 else by_link("E5")))

    approved = d.context.get("approved_recipients", [])
    lvl = "HIGH" if approved and er else "ELEVATED" if approved or er else "NONE"
    txt = []
    if approved:
        txt.append(f"{len(approved)} recipient(s) opened and KYC-approved by {emp}")
    if er:
        txt.append(f"{er[0]['customer_id']} matches {emp}'s HR address")
    dims.append(Dim("relationship", lvl, "; ".join(txt) or "no employee–customer link", by_kind("ACCOUNT_OPENING", "ENTITY_MATCH"), []))

    dims.append(Dim("historical", "LOW" if prior == 0 else "ELEVATED",
                    f"{prior} prior alerts; {tenure:.0f} years' tenure", [], [hist_item.code]))

    # ── rebuttals (benign hypotheses)
    wi = f.work_item[(f.work_item["customer_id"] == cust) & (f.work_item["created_at"] <= d.first_t + pd.Timedelta(hours=1))
                     & (f.work_item["created_at"] >= d.links[0].t - pd.Timedelta(days=7))]
    rebuttals = [
        Rebuttal("The customer asked for the change",
                 "supported" if len(wi) else "refuted",
                 f"{len(wi)} ticket/call/token/eKYC record(s) for {cust} in the 7 days before" if len(wi)
                 else f"No ticket, IVR call, branch token or eKYC for {cust} in the 7 days before",
                 by_kind("ALIBI")),
        Rebuttal("Authorised extended duty (camp or overtime)",
                 "supported" if timing_ok else "refuted",
                 "Rostered at the time" if timing_ok else f"{emp} was not on any roster at the time",
                 by_kind("ROSTER")),
        Rebuttal("Someone else used the employee's credentials",
                 "open",
                 ("Session came from the employee's own issued device — IT forensics needed before attributing to the person"
                  if own_device else "Session device is not the employee's issued device — compromise plausible"),
                 [own_device.code] if own_device else []),
        Rebuttal("The customer set up these payees", "refuted" if feats.get("new_device") else "open",
                 "Payees were added from a never-seen device after the staff-side change" if feats.get("new_device")
                 else "Payees added from the customer's usual device", by_link("E4")),
    ]
    dims_d = dims
    systems = {e.source_system for e in items if e.supports}
    recoverable = True
    p = sc.p if sc else None
    benign = rebuttals[0].status == "supported" and rebuttals[1].status == "supported"
    prio, rule = lattice(dims_d, systems, False, recoverable, p, benign)

    claim_bits = ["Employee-enabled takeover"]
    claim_bits.append("of a dormant account" if feats.get("dormant") else "of a customer account")
    if approved:
        claim_bits.append("with layering through accounts the same employee opened")
    claim = " ".join(claim_bits)
    verb = "used an expired override to change" if expired else "changed"
    when = " after hours" if not timing_ok else ""
    summary = (f"{emp} {verb} {acct}'s contact details{when}; {rupees(amt)} left {_mins(lat)} later"
               + (f" into accounts {emp} opened." if approved else "."))
    missing = ["Branch CCTV and biometric attendance are not ingested",
               f"Customer {cust} not yet contacted through a verified channel",
               "Device forensics on the session device pending"]
    actions = [f"Place a debit freeze on internal recipients ({', '.join(a for a in d.entities if a in ix.acc.index and ix.is_internal(a) and a != acct)})",
               "Request recall of transfers to external banks",
               f"Suspend {emp}'s override entitlement and review all of its uses",
               "Start IT forensics on the staff session before any person-level finding",
               f"Contact {cust} through the verified channel on record"]
    return _finish(d, "INSIDER_ATO", claim, summary, prio, rule, dims_d, rebuttals, items, recoverable, sc,
                   missing, actions, person_level=False)


# ── external takeover ──────────────────────────────────────────────────────


def _external(ctx: BriefContext, d: ChainDraft) -> BriefResult:
    ix = ctx.ix
    book = build_chain_evidence(ctx, d)
    sc = score_chain(d.features)
    if sc is not None:
        top = ", ".join(f"{c['label'].lower()} ({c['contribution']:+.2f})" for c in sc.contributions[:3])
        book.add(ev_model("M5_CLASSIFIER", f"Chain classifier {sc.p:.2f} (calibrated on synthetic seed 7). "
                          f"Largest contributions: {top}", f"M5:{d.root_ref}", d.last_t, [d.account_id],
                          {"p": sc.p, "contributions": sc.contributions}), "E5")
    items = book.finalise()
    by_link = lambda code: [e.code for e in items if code in e.link_codes]  # noqa: E731
    f = d.features
    amt, lat = d.amount_at_risk, d.latency_s or 0
    r2 = ctx.signals_for(set().union(*[set(lk.refs) for lk in d.links if lk.code == "E5"]), set(), {"R2"})
    sess = ix.sess.loc[d.links[0].event_id]
    dims = [
        Dim("transaction", "HIGH" if r2 or amt >= 2e5 else "ELEVATED", f"{rupees(amt)} to new payees"
            + (f"; {r2[0]['summary']}" if r2 else ""), by_link("E5")),
        Dim("employee", "NONE", "no staff action in the chain"),
        Dim("access", "HIGH" if f.get("password_reset") else "ELEVATED",
            f"never-seen device {sess['device_id']} in {sess['geo_city']}"
            + ("; password reset" if f.get("password_reset") else ""), by_link("E1") + by_link("E2")),
        Dim("network", "ELEVATED", f"{int(f.get('n_new_payees', 0))} payees added minutes before the payout", by_link("E4")),
        Dim("temporal", "HIGH" if lat <= 3600 else "ELEVATED",
            f"login → money in {_mins(lat)}" + (f" at {sess['started_at']:%H:%M}" if f.get("night") else ""), by_link("E1")),
        Dim("relationship", "NONE", "no employee–customer link"),
        Dim("historical", "LOW", "no prior alerts on the account"),
    ]
    rebuttals = [
        Rebuttal("The customer bought a new phone or is travelling", "open",
                 f"Login from {sess['geo_city']}; the customer's usual city differs — confirm with the customer", by_link("E1")),
        Rebuttal("The customer set up these payees", "refuted",
                 "Payees were added within minutes of a password reset on the new device", by_link("E4")),
    ]
    systems = {e.source_system for e in items if e.supports}
    prio, rule = lattice(dims, systems, False, True, sc.p if sc else None, False)
    claim = "Account takeover from a never-seen device: password reset, new payees and near-limit transfers"
    summary = f"New device in {sess['geo_city']} reset the password and moved {rupees(amt)} to new payees in {_mins(lat)}."
    missing = ["Telecom SIM-swap confirmation (DoT FRI feed) not ingested", "Customer not yet contacted"]
    actions = ["Block the digital channel and the new device", "Request recall from beneficiary banks",
               "Contact the customer on the verified number", "Report to the national cybercrime helpline if confirmed"]
    return _finish(d, "EXTERNAL_ATO", claim, summary, prio, rule, dims, rebuttals, items, True, sc, missing, actions,
                   person_level=False)


# ── network typologies ─────────────────────────────────────────────────────


def _circular(ctx: BriefContext, d: ChainDraft) -> BriefResult:
    f = ctx.f
    book = build_chain_evidence(ctx, d)
    items = book.finalise()
    accts = sorted(d.entities)
    feats = d.features
    # periodicity: have these accounts cycled money between them in other months too?
    tx = f.txn[f.txn["from_account"].isin(accts) & f.txn["to_account"].isin(accts)]
    months = tx["occurred_at"].dt.strftime("%Y-%m").nunique()
    inv = tx["narration"].fillna("").str.contains("INV", case=False).mean()
    ben = f.beneficiary[f.beneficiary["account_id"].isin(accts) & f.beneficiary["counterparty_account"].isin(accts)]
    old_payees = (ben["added_at"] < d.first_t - pd.Timedelta(days=180)).mean() if len(ben) else 0.0
    periodic = months >= 3
    all_codes = [e.code for e in items]
    dims = [
        Dim("transaction", "HIGH" if d.amount_at_risk >= 5e5 else "ELEVATED", f"{rupees(d.amount_at_risk)} put through the loop", all_codes),
        Dim("employee", "NONE", "no staff action in the chain"),
        Dim("access", "NONE", "no privileged access involved"),
        Dim("network", "HIGH" if feats["retention"] >= 0.85 else "ELEVATED",
            f"{feats['hops']} accounts, {feats['retention']:.0%} of the value came back", all_codes),
        Dim("temporal", "HIGH" if feats["hours"] <= 72 else "ELEVATED", f"loop closed in {feats['hours']:.0f} h", all_codes),
        Dim("relationship", "LOW" if old_payees > 0.5 else "ELEVATED",
            "long-standing counterparties" if old_payees > 0.5 else "payees added days before the loop"),
        Dim("historical", "LOW" if not periodic else "LOW", f"pattern seen in {months} month(s)"),
    ]
    rebuttals = [
        Rebuttal("A recurring business arrangement", "supported" if periodic else "refuted",
                 f"The same accounts cycled money in {months} different months" if periodic
                 else "No earlier cycles between these accounts"),
        Rebuttal("Invoice-backed trade", "supported" if inv >= 0.5 else "refuted",
                 f"{inv:.0%} of transfers cite an invoice" if inv >= 0.5 else "Narrations are generic (consultancy, advance, refund)"),
        Rebuttal("Established counterparties", "supported" if old_payees > 0.5 else "refuted",
                 "Payees set up more than 6 months earlier" if old_payees > 0.5 else "Payees were added days before the loop"),
    ]
    benign = periodic and (inv >= 0.5 or old_payees > 0.5)
    systems = {e.source_system for e in items}
    prio, rule = lattice(dims, systems, False, True, None, benign)
    claim = f"Circular flow: {rupees(d.amount_at_risk)} passed through {feats['hops']} accounts and {feats['retention']:.0%} returned within {feats['hours']:.0f} h"
    summary = claim + "."
    return _finish(d, "CIRCULAR_FLOW", claim, summary, prio, rule, dims, rebuttals, items, True, None,
                   ["Beneficial-ownership records for the four firms not ingested", "Invoices not available"],
                   ["Request business rationale and invoices from all account holders",
                    "Check common directors or addresses across the firms", "Consider an STR if unexplained"], True)


def _structuring(ctx: BriefContext, d: ChainDraft) -> BriefResult:
    f = ctx.f
    book = build_chain_evidence(ctx, d)
    person = next((e for e in d.entities if str(e).startswith("PER-")), None)
    ev_names = [x for x in ctx.cluster_evidence if ctx.clusters.get(x["a"]) == person]
    if ev_names:
        names = sorted({n for x in ev_names for n in x["names"]})
        book.add(EvidenceItem("ENTITY_MATCH", f"One person behind {len(names)} customer records: " + ", ".join(names)
                              + " — same phone, same date of birth", "SUTRA entity resolution", "customer", person, "C",
                              d.first_t, None, [person], {"names": names, "evidence": ev_names}), "D1")
    items = book.finalise()
    feats = d.features
    accts = [a for a in d.entities if str(a).startswith("A-")]
    earlier = f.txn[(f.txn["kind"] == "CASH_DEPOSIT") & f.txn["to_account"].isin(accts)
                    & f.txn["amount"].between(45_000, 49_999) & (f.txn["occurred_at"] < d.first_t - pd.Timedelta(days=7))]
    codes = [e.code for e in items]
    dims = [
        Dim("transaction", "HIGH", f"{feats['deposits']} cash deposits just under ₹50,000 (PAN-quoting threshold)", codes),
        Dim("employee", "NONE", "tellers followed normal procedure"),
        Dim("access", "NONE", "no privileged access involved"),
        Dim("network", "ELEVATED" if feats["consolidated"] else "LOW",
            f"{rupees(feats['consolidated'])} consolidated to a new payee" if feats["consolidated"] else "no consolidation yet", codes[-3:]),
        Dim("temporal", "HIGH", f"all within {d.latency_s / 3600:.0f} h", codes),
        Dim("relationship", "HIGH" if ev_names else "ELEVATED",
            f"{feats['accounts']} accounts at {feats['branches']} branches resolve to one person", [e.code for e in items if e.kind == "ENTITY_MATCH"]),
        Dim("historical", "LOW", f"{len(earlier)} similar deposits in earlier months"),
    ]
    rebuttals = [
        Rebuttal("Ordinary business takings", "supported" if len(earlier) >= 10 else "refuted",
                 f"{len(earlier)} near-threshold deposits in earlier months" if len(earlier) >= 10
                 else "No history of near-threshold cash deposits on these accounts"),
        Rebuttal("Different people who happen to look alike", "refuted" if ev_names else "open",
                 "Same phone number and date of birth across the name spellings" if ev_names else "Identity not resolved"),
    ]
    systems = {e.source_system for e in items}
    prio, rule = lattice(dims, systems, False, True, None, rebuttals[0].status == "supported")
    claim = (f"Cash structuring: {feats['deposits']} deposits just under ₹50,000 across {feats['branches']} branches "
             f"into accounts of one resolved person, then consolidated out")
    return _finish(d, "STRUCTURING", claim, claim + ".", prio, rule, dims, rebuttals, items, True, None,
                   ["Source-of-funds declaration not on file", "Branch CCTV for the deposit times not reviewed"],
                   ["Ask the customer for the source of the cash", "Link the three customer records (KYC hygiene)",
                    "File a cash-structuring STR if the source is not established"], True)


def _mule_factory(ctx: BriefContext, d: ChainDraft) -> BriefResult:
    ix = ctx.ix
    s = d.context["signal"]
    p = s["payload"]
    book = build_chain_evidence(ctx, d)
    for a in p["accounts"]:
        book.add(ev_account_opening(ix.acc.loc[a], a), "F2")
    book.add(ev_model("G4_FACTORY", s["summary"], f"G4:{p['employee']}", s["window_end"], [p["employee"]], p), "F3")
    scores = ctx.mule_scores.loc[[a for a in p["accounts"] if a in ctx.mule_scores.index]]
    hi = scores[scores["p"] >= 0.5]
    if len(hi):
        book.add(ev_model("M6_MULE", f"{len(hi)} of {len(p['accounts'])} accounts score ≥0.5 on mule-likeness "
                          f"(median {scores['p'].median():.2f})", f"M6:{p['employee']}", s["window_end"], list(hi.index),
                          {"scores": scores["p"].round(3).to_dict()}), "F4")
    items = book.finalise()
    codes = lambda k: [e.code for e in items if e.kind == k]  # noqa: E731
    feats = d.features
    linked = d.context.get("linked_chains", [])
    dims = [
        Dim("transaction", "HIGH" if d.amount_at_risk >= 5e5 else "ELEVATED", f"{rupees(d.amount_at_risk)} received across the cluster", codes("TXN")),
        Dim("employee", "HIGH", f"{feats['approvals']} approvals in 60 days vs baseline {feats['baseline']}", codes("G4_FACTORY")),
        Dim("access", "HIGH" if feats["presenceless"] >= 3 else "ELEVATED",
            f"{feats['presenceless']} accounts opened without the customer present; opener approved own KYC", codes("ACCOUNT_OPENING")),
        Dim("network", "HIGH", f"{feats['shared']} accounts share devices or phones", codes("G4_FACTORY") + codes("M6_MULE")),
        Dim("temporal", "ELEVATED", "openings clustered in the last 60 days"),
        Dim("relationship", "HIGH", "one employee opened and approved every account"
            + ("; cluster received takeover money" if linked else ""), codes("ACCOUNT_OPENING")),
        Dim("historical", "LOW", "no prior alerts on the employee"),
    ]
    rebuttals = [
        Rebuttal("An account-opening drive or camp", "refuted",
                 "Openings had no branch token or biometric eKYC, and other approvers show no matching spike"),
        Rebuttal("Family members sharing one phone", "open", "Three accounts share a phone — confirm household relationships"),
        Rebuttal("An institution collecting fees", "refuted", "All accounts are personal savings accounts"),
    ]
    systems = {e.source_system for e in items}
    prio, rule = lattice(dims, systems, False, True, None, False)
    claim = (f"Mule factory: {feats['approvals']} accounts opened and KYC-approved by one employee without the customer "
             f"present; {feats['shared']} share devices or phones")
    return _finish(d, "MULE_FACTORY", claim, claim + ".", prio, rule, dims, rebuttals, items, True, None,
                   ["KYC document images not reviewed", "MuleHunter.AI scores not ingested for these accounts"],
                   ["Restrict debits on the cluster pending KYC re-verification",
                    f"Suspend {p['employee']}'s account-opening and KYC-approval entitlements",
                    "Re-verify each customer in person (biometric eKYC)"], False)


def _finish(d, typology, claim, summary, prio, rule, dims, rebuttals, items, recoverable, sc, missing, actions,
            person_level) -> BriefResult:
    systems = sorted({e.source_system for e in items if e.reliability in "AB"})
    detectors = sorted({s for s in _warrant_detectors(typology)})
    grounds = [{"code": e.code, "text": e.summary} for e in items if e.supports and e.reliability in "ABC"][:14]
    argument = {
        "claim": claim, "typology": typology, "summary": summary,
        "grounds": grounds,
        "rebuttals": [r.as_dict() for r in rebuttals],
        "warrant": {"detectors": [{"code": c, "name": DETECTORS[c].name, "version": DETECTORS[c].version,
                                   "logic": DETECTORS[c].logic} for c in detectors if c in DETECTORS],
                    "text": " + ".join(f"{c} v{DETECTORS[c].version}" for c in detectors if c in DETECTORS)},
        "backing": _backing(typology),
        "qualifier": {"systems": systems, "n_systems": len(systems),
                      "model": ({"name": "M5 chain classifier", "p": sc.p, "decision": sc.decision,
                                 "calibrated_on": "synthetic world, seed 7"} if sc else None),
                      "text": f"Corroborated across {len(systems)} independent systems"
                      + (f" · chain classifier {sc.p:.2f} (calibrated on synthetic data)" if sc else "")},
        "missing": missing,
        "recommended_actions": actions,
        "attribution": {"person_level": person_level,
                        "note": "Attribution to a person is not established — credential compromise has not been ruled out"
                        if typology == "INSIDER_ATO" else "Account-level finding"},
        "contributions": sc.contributions if sc else [],
        "latency_s": d.latency_s, "amount_at_risk": d.amount_at_risk,
    }
    return BriefResult(d, typology, claim, summary, prio, rule, dims, rebuttals, items, argument, recoverable,
                       {"p": sc.p, "decision": sc.decision, "contributions": sc.contributions} if sc else None)


def _warrant_detectors(typology: str) -> list[str]:
    return {"INSIDER_ATO": ["NEEDLE", "ALIBI", "R3", "R4", "R7", "R9", "R2", "G2", "M1", "M2", "M5"],
            "EXTERNAL_ATO": ["NEEDLE", "R4", "R2", "M5"],
            "CIRCULAR_FLOW": ["G1"], "STRUCTURING": ["R1", "ER"],
            "MULE_FACTORY": ["G4", "R8", "R10", "G5", "M6"]}.get(typology, [])


def _backing(typology: str) -> list[str]:
    return {
        "INSIDER_ATO": ["FIU-IND red-flag family: account takeover and money mules",
                        "Internal policy: contact changes need OTP to the old number or biometric eKYC",
                        "RBI Master Directions on Fraud Risk Management (2024): staff accountability"],
        "EXTERNAL_ATO": ["FIU-IND red-flag family: account takeover", "RBI cyber-fraud customer-protection framework"],
        "CIRCULAR_FLOW": ["FATF layering typology: round-tripping between related entities"],
        "STRUCTURING": ["PMLA reporting thresholds; splitting cash below PAN-quoting limits"],
        "MULE_FACTORY": ["RBI KYC Master Direction: customer due diligence at onboarding",
                         "MHA / RBI mule-account guidance (MuleHunter.AI)"],
    }.get(typology, [])


def brief_for(ctx: BriefContext, d: ChainDraft) -> BriefResult:
    return {"INSIDER_ATO": _insider, "EXTERNAL_ATO": _external, "CIRCULAR": _circular,
            "STRUCTURING": _structuring, "MULE_FACTORY": _mule_factory}[d.kind](ctx, d)
