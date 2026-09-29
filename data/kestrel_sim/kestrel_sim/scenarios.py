"""Scenario injection: suspicious variants and their legitimate twins.

`inject_demo` writes the canonical story used in the live demo (fixed IDs, fixed times).
`inject_training` writes many randomised instances of the same typologies into an
independent world (seed 7) for model training — see docs/adr/007.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from kestrel_sim import names
from kestrel_sim.baseline import (
    RUPEE,
    new_account,
    new_customer,
    new_device,
    primary_account,
    staff,
)
from kestrel_sim.clock import IST, WINDOW_START, at, working_days
from kestrel_sim.world import World

CATALOGUE = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "scenarios" / "scenarios.yaml").read_text())

DEMO_STAFF = {
    "EMP-0417": {"branch": "BR-014", "role": "OPS_OFFICER", "name": "Rohan Kulkarni",
                 "hire": date(2022, 8, 1), "pincode": "411052", "laptop": "LAP-221",
                 "address": "Flat 12, Shivkrupa Apartments, Karve Nagar, Pune 411052",
                 "extra_perms": ["KYC_APPROVE", "ACCT_OPEN"]},
    "EMP-0233": {"branch": "BR-014", "role": "OPS_OFFICER", "name": "Snehal Joshi",
                 "hire": date(2016, 6, 1)},
    "EMP-0112": {"branch": "BR-021", "role": "RM", "name": "Vikas Shinde",
                 "hire": date(2014, 3, 1)},
}
DEMO_APPROVER_BIAS = {"EMP-0417": 0.2}

DEMO_RESERVED = ["C-88213", "A-5520", "A-7731", "A-7768", "A-6604", "X-8120", "X-9901",
                 "C-77120", "A-4410", "D-9F2", "S-5591"]


def _label(w: World, sid: str, variant: str, entities: list[str], events: list[str],
           instance: str | None = None, **extra) -> None:
    meta = CATALOGUE[sid]
    part = meta.get(variant) or {}
    w.label(scenario=sid, variant=variant, key=instance or f"{sid}-{variant}",
            title=meta["title"], typology=meta["typology"],
            description=part.get("description", ""), differing_fact=part.get("differing_fact"),
            expected=part.get("expected", {}), entities=sorted(set(entities)),
            events=list(dict.fromkeys(events)), **extra)


def _ext(w: World, holder: str, xid: str | None = None, bank: str | None = None) -> str:
    xid = xid or w.rid("X", 4)
    w.reserve(xid)
    acct = w.add("account", id=xid, customer_id=None, kind="EXTERNAL", holder_name=holder,
                 bank_name=bank or w.rng.choice(names.BANKS), branch_id=None, status="ACTIVE",
                 status_since=None, opened_at=None, opened_by=None, kyc_approved_by=None,
                 opening_mode=None, daily_limit_paise=0, balance_paise=0, _raw_mobile=None)
    w.accounts[xid] = acct
    return xid


# ── S7 building block: the mule factory ───────────────────────────────────────


def mule_factory(w: World, pools, insider: str, n: int, start: date, end: date,
                 fixed: dict[int, tuple[str, date]] | None = None,
                 instance: str | None = None) -> tuple[list[str], list[str], list[str]]:
    """Accounts opened + KYC-approved by `insider` without the customer present.

    Returns (account_ids, shared_device_ids, event_ids).
    """
    fixed = fixed or {}
    emp = w.employees[insider]
    branch = emp["branch_id"]
    shared_devices = [new_device(w, "ANDROID", at(start, 9)) for _ in range(2)]
    shared_phone = w.phone()
    accts, events = [], []
    span = (end - start).days
    for i in range(n):
        aid, open_day = fixed.get(i, (None, start + timedelta(days=int(span * i / max(1, n - 1)))))
        t = at(open_day, w.rng.randint(11, 16), w.rng.randint(0, 59))
        cust = new_customer(w, branch, w.rng.choice(["SELF_EMPLOYED", "HOMEMAKER", "STUDENT"]), t,
                            phone=shared_phone if i < 3 else None)
        acct = new_account(w, cust, "SAVINGS", t, insider, insider, "BRANCH_DOCS", 0, aid=aid)
        accts.append(acct["id"])
        # self-created queue item → Alibi sees a "queue" reason; structure must catch this
        wi = w.work_item("QUEUE", w.seq("KQ", 5), t + timedelta(minutes=3), cust["id"], acct["id"],
                         insider, branch, "KYC review queue — new savings account")
        e1 = w.access(insider, None, "ACCT_OPEN", t, acct["id"], cust["id"])
        e2 = w.access(insider, None, "KYC_APPROVE", t + timedelta(minutes=9), acct["id"],
                      cust["id"], ["kyc_documents"])
        events += [e1["id"], e2["id"], wi["id"]]
        dev = shared_devices[i % 2] if i < 7 else new_device(w, "ANDROID", t + timedelta(days=2))
        w.customer_device[cust["id"]] = dev
        cust["_mule"] = True
    return accts, shared_devices, events


def mule_activity(w: World, pools, mule_accts: list[str], consolidator: str,
                  start: date, end: date) -> list[str]:
    """Fan-in from scam victims, then fast cash-out / forward to the consolidator."""
    events: list[str] = []
    for aid in mule_accts:
        acct = w.accounts[aid]
        opened = acct["opened_at"].date()
        d = max(start, opened + timedelta(days=4))
        while d <= end:
            if w.rng.random() < 0.18:
                t = at(d, w.rng.randint(10, 21), w.rng.randint(0, 59))
                cid = acct["customer_id"]
                dev = w.customer_device[cid]
                s = w.session("CUSTOMER", cid, dev, "MOBILE", t, 50, geo="Pune")["id"]
                total = 0
                for k in range(w.rng.randint(1, 3)):
                    victim = w.rng.choice(pools["person"])
                    amt = w.rng.randint(15, 140) * 1000
                    tx = w.txn(victim, aid, amt * RUPEE, "IMPS", "CREDIT", t + timedelta(minutes=5 * k),
                               "Transfer", force=True)
                    total += amt
                    events.append(tx["id"])
                keep = w.rng.uniform(0.02, 0.06)
                out = int(total * (1 - keep))
                if w.rng.random() < 0.55:
                    if consolidator not in w.payees[aid]:
                        w.beneficiary(aid, consolidator, w.accounts[consolidator]["holder_name"],
                                      t + timedelta(minutes=12), s)
                    tx = w.txn(aid, consolidator, int(out * 0.8) * RUPEE, "IMPS", "TRANSFER",
                               t + timedelta(minutes=w.rng.randint(15, 45)), "Settlement", s, force=True)
                    events.append(tx["id"])
                    out = int(out * 0.2)
                for j in range(max(1, out // 10000)):
                    tx = w.txn(aid, "X-ATM", min(10000, out) * RUPEE, "ATM", "ATM_WITHDRAWAL",
                               t + timedelta(minutes=50 + 3 * j), "ATM cash", force=True)
                    if tx:
                        events.append(tx["id"])
            d += timedelta(days=1)
    return events


# ── S4: insider privilege misuse → dormant takeover (+S5 relationship) ───────


def insider_chain(w: World, pools, *, insider: str, t_login: datetime, mule_targets: list[str],
                  consolidator: str, amounts: list[int], override: bool = True,
                  raise_limit: bool = True, grant_days_before: int | None = 9,
                  accomplice_delay_min: int = 19, payout_delay_min: int = 47,
                  fixed: dict | None = None, instance: str | None = None) -> dict:
    fixed = fixed or {}
    emp = w.employees[insider]
    branch = emp["branch_id"]
    events: list[str] = []

    if override and grant_days_before is not None:
        g = t_login - timedelta(days=grant_days_before)
        g = g.replace(hour=11, minute=5, second=0)
        ent = w.add("entitlement", id=w.seq("ENT", 5), employee_id=insider,
                    permission_code="MOBILE_UPDATE_OVERRIDE", granted_by=emp["manager_id"],
                    reason="Pension camp — bulk mobile updates for senior citizens",
                    request_ref=fixed.get("request_ref", f"REQ-{w.rng.randint(1000, 9999)}"),
                    valid_from=g, intended_expiry=(g + timedelta(days=2)).replace(hour=23, minute=59),
                    revoked_at=None)
        events.append(ent["id"])

    # the victim: a pensioner whose savings account has been inoperative for > 2 years
    victim = new_customer(w, branch, "PENSIONER",
                          datetime(2009, 5, 12, 11, 0, tzinfo=IST), cid=fixed.get("victim_cust"),
                          name=fixed.get("victim_name"))
    since = fixed.get("dormant_since", t_login - timedelta(days=w.rng.randint(760, 1100)))
    victim_acct = new_account(w, victim, "SAVINGS", datetime(2009, 5, 12, 11, 30, tzinfo=IST),
                              w.rng.choice(staff(w, branch, "TELLER")),
                              w.rng.choice(staff(w, branch, "KYC_APPROVER")), "BRANCH_BIOMETRIC",
                              fixed.get("balance", w.rng.randint(9, 25) * 100_000),
                              aid=fixed.get("victim_acct"), status="INOPERATIVE", status_since=since)
    va = victim_acct["id"]
    victim["_scenario"] = True

    s = w.session("EMPLOYEE", insider, emp.get("_laptop") or emp["_terminal"], "VPN", t_login, 11,
                  geo=emp["_city"], sid=fixed.get("session"))["id"]
    ts = [t_login + timedelta(seconds=x) for x in (31, 115, 297, 500)]
    events.append(w.access(insider, s, "CUST_SEARCH", ts[0], None, victim["id"])["id"])
    events.append(w.access(insider, s, "ACCT_VIEW", ts[1], va, victim["id"],
                           ["balance", "registered_mobile", "nominee"])["id"])
    new_mobile = w.phone()
    events.append(w.access(insider, s, "MOBILE_UPDATE", ts[2], va, victim["id"],
                           ["registered_mobile"], override=override)["id"])
    events.append(w.state_change(va, "REGISTERED_MOBILE", victim_acct["_raw_mobile"], new_mobile,
                                 "EMPLOYEE", insider, "OVERRIDE" if override else "OTP_NEW_NUMBER",
                                 ts[2], s)["id"])
    limit_paise = victim_acct["daily_limit_paise"]
    if raise_limit:
        new_limit = 5_00_000 * RUPEE
        events.append(w.access(insider, s, "LIMIT_CHANGE", ts[3], va, victim["id"], ["txn_limit"],
                               override=override)["id"])
        events.append(w.state_change(va, "TXN_LIMIT", str(limit_paise), str(new_limit), "EMPLOYEE",
                                     insider, "OVERRIDE" if override else "MAKER_ONLY", ts[3], s)["id"])
        limit_paise = new_limit

    # the accomplice takes over the digital channel from a never-seen device
    t_acc = t_login + timedelta(minutes=accomplice_delay_min, seconds=2)
    dev = new_device(w, "ANDROID", t_acc, did=fixed.get("device"))
    cs = w.session("CUSTOMER", victim["id"], dev, "NETBANKING", t_acc, 40, geo="Pune")["id"]
    events.append(w.state_change(va, "PASSWORD", "—", "reset", "CUSTOMER", victim["id"],
                                 "OTP_NEW_NUMBER", t_acc + timedelta(seconds=28), cs)["id"])
    for k, target in enumerate(mule_targets):
        b = w.beneficiary(va, target, w.accounts[target]["holder_name"],
                          t_acc + timedelta(minutes=5 + k, seconds=53 + 17 * k), cs)
        events.append(b["id"])

    t_pay = t_login + timedelta(minutes=payout_delay_min, seconds=-8)
    offsets = [0, 136, 343, 520, 700]
    for k, target in enumerate(mule_targets):
        amt = amounts[k % len(amounts)]
        tx = w.txn(va, target, amt * RUPEE, "IMPS", "TRANSFER", t_pay + timedelta(seconds=offsets[k]),
                   "IMPS transfer", cs, force=True)
        events.append(tx["id"])

    # layering: internal mules forward ~96% to the consolidator, cash out the rest,
    # and the consolidator closes a loop back into the first mule
    internal = [m for m in mule_targets if w.accounts[m]["kind"] != "EXTERNAL"]
    fwd_times = [t_pay + timedelta(minutes=24, seconds=8), t_pay + timedelta(minutes=40, seconds=28)]
    for k, m in enumerate(internal):
        cid = w.accounts[m]["customer_id"]
        ms = w.session("CUSTOMER", cid, w.customer_device.get(cid), "MOBILE",
                       fwd_times[k % 2] - timedelta(minutes=3), 30, geo="Pune")["id"]
        recv = amounts[mule_targets.index(m) % len(amounts)]
        fwd = int(recv * (0.959 + 0.004 * k)) // 1000 * 1000
        if consolidator not in w.payees[m]:
            w.beneficiary(m, consolidator, w.accounts[consolidator]["holder_name"],
                          fwd_times[k % 2] - timedelta(minutes=2), ms)
        events.append(w.txn(m, consolidator, fwd * RUPEE, "IMPS", "TRANSFER", fwd_times[k % 2],
                            "Settlement", ms, force=True)["id"])
        tx = w.txn(m, "X-ATM", (recv - fwd) * RUPEE, "ATM", "ATM_WITHDRAWAL",
                   fwd_times[k % 2] + timedelta(minutes=6, seconds=52), "ATM cash", force=True)
        if tx:
            events.append(tx["id"])
    exit_acct = fixed.get("exit") or _ext(w, "Shree Bullion House")
    t_exit = t_pay + timedelta(minutes=66)
    events.append(w.txn(consolidator, exit_acct, 5_00_000 * RUPEE, "RTGS", "TRANSFER", t_exit,
                        "Purchase", force=True)["id"])
    if internal:
        events.append(w.txn(consolidator, internal[0], 2_10_000 * RUPEE, "IMPS", "TRANSFER",
                            t_exit + timedelta(minutes=18), "Refund", force=True)["id"])

    return {"victim_cust": victim["id"], "victim_acct": va, "events": events,
            "entities": [insider, victim["id"], va, consolidator, *mule_targets, dev, exit_acct]}


def consolidator_account(w: World, insider: str, aid: str | None = None) -> str:
    """A current account whose registered address matches the insider's HR record."""
    emp = w.employees[insider]
    surname = emp["full_name"].split()[-1]
    first = w.rng.choice([f for f in names.FIRST if f[0] == "R"] or names.FIRST)
    raw = emp["address_norm"]
    variant = (raw.replace("flat ", "").replace("apartments", "apts").replace("karve nagar", "karvenagar")
               if "apartments" in raw else raw.replace("flat ", ""))
    cust = new_customer(w, emp["branch_id"], "SME", datetime(2025, 11, 18, 12, 0, tzinfo=IST),
                        name=f"{surname} {first}", address=variant, pincode=emp["pincode"])
    cust["full_name"] = f"{surname} {first}"
    acct = new_account(w, cust, "CURRENT", datetime(2025, 11, 18, 12, 30, tzinfo=IST),
                       w.rng.choice(staff(w, emp["branch_id"], "TELLER")),
                       w.rng.choice(staff(w, emp["branch_id"], "KYC_APPROVER")),
                       "BRANCH_BIOMETRIC", 40_000, aid=aid)
    acct["holder_name"] = f"{first[0]}{surname[0]} Traders"
    cust["_scenario"] = True
    return acct["id"]


def camp_twin(w: World, twin_emp: str, d: date, highlight: dict | None = None,
              n_extra: int = 5, instance: str | None = None) -> dict:
    """Legitimate evening pension camp: roster + tickets + biometric eKYC for every update."""
    emp = w.employees[twin_emp]
    branch = emp["branch_id"]
    w.add("roster", id=w.seq("RS", 6), employee_id=twin_emp, shift_start=at(d, 17, 30),
          shift_end=at(d, 22, 30), duty_type="CAMP")
    sess = w.session("EMPLOYEE", twin_emp, emp["_terminal"], "BRANCH", at(d, 17, 35), 290,
                     geo=emp["_city"])["id"]
    pensioners = [c for c, v in w.customers.items()
                  if v["branch_id"] == branch and v["segment"] == "PENSIONER"
                  and primary_account(w, c)["status"] == "ACTIVE" and not v.get("_scenario")]
    picks = w.rng.sample(pensioners, n_extra)
    events, entities, key = [], [twin_emp], None
    slots = [at(d, 18, 5) + timedelta(minutes=33 * i) for i in range(n_extra)]
    jobs = [(c, t, None) for c, t in zip(picks, slots, strict=True)]
    if highlight:
        hc = new_customer(w, branch, "PENSIONER", datetime(2011, 2, 3, 11, tzinfo=IST),
                          cid=highlight.get("cust"))
        new_account(w, hc, "SAVINGS", datetime(2011, 2, 3, 11, 20, tzinfo=IST),
                    w.rng.choice(staff(w, branch, "TELLER")),
                    w.rng.choice(staff(w, branch, "KYC_APPROVER")), "BRANCH_BIOMETRIC",
                    3_40_000, aid=highlight.get("acct"))
        hc["_scenario"] = True
        jobs.append((hc["id"], highlight["t"], highlight.get("ref")))
        key = hc["id"]
    for cid, t, ref in jobs:
        acct = primary_account(w, cid)
        tk = w.work_item("TICKET", ref or f"SR-{w.rng.randint(1000, 9999)}", t - timedelta(minutes=45),
                         cid, acct["id"], twin_emp, branch,
                         "Pension camp: update registered mobile number — customer present, "
                         "Aadhaar biometric verified")
        ek = w.work_item("EKYC", f"EKYC-{w.rng.randint(100000, 999999)}", t - timedelta(minutes=2),
                         cid, acct["id"], twin_emp, branch, "Aadhaar biometric eKYC — success", 2)
        a1 = w.access(twin_emp, sess, "ACCT_VIEW", t - timedelta(minutes=1), acct["id"], cid,
                      ["profile", "registered_mobile"])
        a2 = w.access(twin_emp, sess, "MOBILE_UPDATE", t, acct["id"], cid, ["registered_mobile"])
        sc = w.state_change(acct["id"], "REGISTERED_MOBILE", acct["_raw_mobile"], w.phone(),
                            "EMPLOYEE", twin_emp, "BIOMETRIC", t, sess)
        if cid == key or not highlight:
            events += [tk["id"], ek["id"], a1["id"], a2["id"], sc["id"]]
            entities += [cid, acct["id"]]
            # next morning: new handset, son added as payee, a modest transfer
            nt = t + timedelta(hours=11, minutes=35)
            dev = new_device(w, "ANDROID", nt)
            w.customer_device[cid] = dev
            cs = w.session("CUSTOMER", cid, dev, "MOBILE", nt, 12, geo=emp["_city"])["id"]
            son = w.rng.choice([p for p in w.accounts if p.startswith("X-") and len(p) == 6])
            b = w.beneficiary(acct["id"], son, f"{w.rng.choice(names.FIRST)} {w.customers[cid]['full_name'].split()[-1]}",
                              nt + timedelta(minutes=3), cs)
            w.balance[acct["id"]] = max(w.balance[acct["id"]], 1_00_000 * RUPEE)
            tx = w.txn(acct["id"], son, 60_000 * RUPEE, "IMPS", "TRANSFER", nt + timedelta(minutes=9),
                       "To son", cs)
            events += [b["id"]] + ([tx["id"]] if tx else [])
            entities += [dev]
    return {"events": events, "entities": entities}


# ── S2 circular flow, S3 structuring, S6 ATO, twins ──────────────────────────


def _business(w: World, branch: str, label: str, opened: datetime, bal: int) -> str:
    cust = new_customer(w, branch, "SME", opened)
    cust["full_name"] = label
    cust["name_norm"] = label.lower()
    cust["_scenario"] = True
    acct = new_account(w, cust, "CURRENT", opened, w.rng.choice(staff(w, branch, "TELLER")),
                       w.rng.choice(staff(w, branch, "KYC_APPROVER")), "BRANCH_BIOMETRIC", bal)
    acct["holder_name"] = label
    w.customer_device[cust["id"]] = new_device(w, "ANDROID", opened + timedelta(days=3))
    return acct["id"]


def circular(w: World, d0: date, amount: int = 8_00_000, retention: float = 0.92,
             instance: str | None = None) -> dict:
    branches = ["BR-021", "BR-033", "BR-021", "BR-014"]
    labels = [f"{w.rng.choice(names.LAST)} {w.rng.choice(names.TRADE_WORDS)}" for _ in range(4)]
    accts = [_business(w, b, lbl, datetime(2025, w.rng.randint(1, 12), 10, 12, tzinfo=IST), 1_00_000)
             for b, lbl in zip(branches, labels, strict=True)]
    keep = retention ** (1 / 4)  # per-hop share kept so the loop returns `retention` overall
    events, amt, t = [], amount, at(d0, 11, 0)
    hop_gaps = [timedelta(hours=6, minutes=30), timedelta(hours=18, minutes=45),
                timedelta(hours=21, minutes=25)]
    for k in range(4):
        src, dst = accts[k], accts[(k + 1) % 4]
        cid = w.accounts[src]["customer_id"]
        s = w.session("CUSTOMER", cid, w.customer_device[cid], "NETBANKING",
                      t - timedelta(minutes=4), 15)["id"]
        if dst not in w.payees[src]:
            w.beneficiary(src, dst, w.accounts[dst]["holder_name"], at(d0, 10) - timedelta(days=4 - k), None)
        events.append(w.txn(src, dst, int(amt) * RUPEE, "RTGS" if amt > 2_00_000 else "IMPS",
                            "TRANSFER", t, w.rng.choice(["Consultancy fees", "Advance", "Service charges",
                                                         "Refund of advance"]), s, force=True)["id"])
        amt = int(amt * keep // 1000 * 1000) if k < 3 else amt
        if k < 3:
            t = t + hop_gaps[k]
    return {"events": events, "entities": accts}


def periodic_loan_twin(w: World, instance: str | None = None) -> dict:
    a = _business(w, "BR-033", f"{w.rng.choice(names.LAST)} Packaging Pvt Ltd",
                  datetime(2019, 4, 2, 11, tzinfo=IST), 12_00_000)
    b = _business(w, "BR-033", f"{w.rng.choice(names.LAST)} Distributors",
                  datetime(2018, 8, 20, 11, tzinfo=IST), 9_00_000)
    w.beneficiary(a, b, w.accounts[b]["holder_name"], datetime(2021, 5, 1, tzinfo=IST))
    w.beneficiary(b, a, w.accounts[a]["holder_name"], datetime(2021, 5, 1, tzinfo=IST))
    events = []
    for m in (6, 7, 8, 9):
        d = date(2026, m, 3)
        if at(d, 12) < WINDOW_START:
            continue
        events.append(w.txn(a, b, 5_00_000 * RUPEE, "RTGS", "TRANSFER", at(d, 11, 30),
                            f"Working capital loan INV-2026-{m:02d}-14", force=True)["id"])
        events.append(w.txn(b, a, 4_90_000 * RUPEE, "RTGS", "TRANSFER", at(d + timedelta(days=1), 15, 10),
                            f"Loan repayment INV-2026-{m:02d}-14 less interest", force=True)["id"])
    return {"events": events, "entities": [a, b]}


def structuring(w: World, d0: date, instance: str | None = None) -> dict:
    first, last = w.rng.choice(names.FIRST), w.rng.choice(names.LAST)
    spellings = [f"{first} S {last}", f"{last} {first}", f"{first[0]}. {last}"]
    phone = w.phone()
    dob = date(1984, 3, 17)
    branches = ["BR-014", "BR-021", "BR-033"]
    accts, custs = [], []
    for sp, br in zip(spellings, branches, strict=True):
        c = new_customer(w, br, "SELF_EMPLOYED", datetime(2024, w.rng.randint(1, 12), 5, 12, tzinfo=IST),
                         name=sp, phone=phone)
        c["dob"] = dob
        c["_scenario"] = True
        a = new_account(w, c, "SAVINGS", c["created_at"] + timedelta(minutes=20),
                        w.rng.choice(staff(w, br, "TELLER")), w.rng.choice(staff(w, br, "KYC_APPROVER")),
                        "BRANCH_BIOMETRIC", 8_000)
        accts.append(a["id"])
        custs.append(c["id"])
    events = []
    plan = [(0, 0, 11, 20), (1, 0, 15, 5), (2, 1, 11, 45), (0, 1, 16, 30), (1, 2, 10, 50),
            (2, 2, 13, 15), (0, 2, 17, 10)]
    for i, day_off, hh, mm in plan:
        br = branches[i]
        t = at(d0 + timedelta(days=day_off), hh, mm)
        teller = w.rng.choice(staff(w, br, "TELLER"))
        amt = w.rng.randint(455, 498) * 100
        w.work_item("TOKEN", f"TKN-{w.rng.randint(100, 999)}", t - timedelta(minutes=6), custs[i],
                    accts[i], teller, br, "Counter token — walk-in customer", 15)
        w.access(teller, None, "CASH_DEPOSIT", t, accts[i], custs[i])
        events.append(w.txn("X-CASH", accts[i], amt * RUPEE, "CASH", "CASH_DEPOSIT", t,
                            "Cash deposit at counter", branch_id=br)["id"])
    sink = _ext(w, f"{w.rng.choice(names.LAST)} Land Developers")
    for i, a in enumerate(accts):
        t = at(d0 + timedelta(days=3), 11, 20 + 4 * i)
        cid = w.accounts[a]["customer_id"]
        dev = new_device(w, "ANDROID", t - timedelta(days=30))
        s = w.session("CUSTOMER", cid, dev, "MOBILE", t - timedelta(minutes=3), 10)["id"]
        w.beneficiary(a, sink, w.accounts[sink]["holder_name"], t - timedelta(minutes=2), s)
        events.append(w.txn(a, sink, int(w.balance[a] * 0.97) // RUPEE // 100 * 100 * RUPEE, "IMPS",
                            "TRANSFER", t, "Plot booking", s, force=True)["id"])
    return {"events": events, "entities": accts + custs + [sink]}


def kirana_twin(w: World, instance: str | None = None) -> dict:
    br = "BR-033"
    c = new_customer(w, br, "SHOPKEEPER", datetime(2017, 6, 1, 11, tzinfo=IST))
    c["full_name"] = "Sai Kirana Stores"
    c["name_norm"] = "sai kirana stores"
    c["_scenario"] = True
    a = new_account(w, c, "CURRENT", datetime(2017, 6, 1, 11, 30, tzinfo=IST),
                    w.rng.choice(staff(w, br, "TELLER")), w.rng.choice(staff(w, br, "KYC_APPROVER")),
                    "BRANCH_BIOMETRIC", 2_40_000)["id"]
    events = []
    for d in working_days():
        teller = w.rng.choice(staff(w, br, "TELLER"))
        t = at(d, 18, w.rng.randint(0, 20))
        w.work_item("TOKEN", f"TKN-{w.rng.randint(100, 999)}", t - timedelta(minutes=5), c["id"], a,
                    teller, br, "Counter token — walk-in customer", 15)
        w.access(teller, None, "CASH_DEPOSIT", t, a, c["id"])
        tx = w.txn("X-CASH", a, w.rng.randint(450, 495) * 100 * RUPEE, "CASH", "CASH_DEPOSIT", t,
                   "Daily takings", branch_id=br)
        events.append(tx["id"])
    return {"events": events[-10:], "entities": [a, c["id"]]}


def external_ato(w: World, pools, t0: datetime, instance: str | None = None) -> dict:
    cands = [c for c, v in w.customers.items() if v["segment"] == "SALARIED" and not v.get("_scenario")
             and primary_account(w, c)["status"] == "ACTIVE" and w.customers[c]["_city"] == "Pune"]
    cid = w.rng.choice(cands)
    w.customers[cid]["_scenario"] = True
    acct = primary_account(w, cid)
    a = acct["id"]
    w.balance[a] = max(w.balance[a], 3_20_000 * RUPEE)
    dev = new_device(w, "ANDROID", t0)
    s = w.session("CUSTOMER", cid, dev, "NETBANKING", t0, 35, geo="Kolkata")["id"]
    events = [w.state_change(a, "PASSWORD", "—", "reset", "CUSTOMER", cid, "OTP_REGISTERED",
                             t0 + timedelta(minutes=1), s)["id"]]
    targets = [w.rng.choice(pools["person"]) for _ in range(2)]
    for k, cp in enumerate(targets):
        events.append(w.beneficiary(a, cp, w.accounts[cp]["holder_name"],
                                    t0 + timedelta(minutes=5 + k), s)["id"])
    limit = acct["daily_limit_paise"] // RUPEE
    for k, (cp, frac) in enumerate(zip(targets, (0.985, 0.97), strict=True)):
        events.append(w.txn(a, cp, int(limit * frac) * RUPEE, "IMPS", "TRANSFER",
                            t0 + timedelta(minutes=17 + 2 * k), "IMPS transfer", s, force=True)["id"])
    events.append(w.txn(a, targets[0], 48_000 * RUPEE, "UPI", "UPI_PAY", t0 + timedelta(minutes=27),
                        "UPI", s, force=True)["id"])
    return {"events": events, "entities": [cid, a, dev, *targets]}


def new_phone_twin(w: World, t0: datetime, instance: str | None = None) -> dict:
    cands = [c for c, v in w.customers.items() if v["segment"] == "SALARIED" and not v.get("_scenario")
             and primary_account(w, c)["status"] == "ACTIVE" and w.payees[primary_account(w, c)["id"]]]
    cid = w.rng.choice(cands)
    w.customers[cid]["_scenario"] = True
    a = primary_account(w, cid)["id"]
    dev = new_device(w, "IOS", t0)
    w.customer_device[cid] = dev
    s = w.session("CUSTOMER", cid, dev, "MOBILE", t0, 10, geo=w.customers[cid]["_city"])["id"]
    events = [w.state_change(a, "DEVICE_BINDING", "old handset", "new handset", "CUSTOMER", cid,
                             "OTP_OLD_NUMBER", t0 + timedelta(minutes=1), s)["id"]]
    cp = sorted(w.payees[a])[0]
    w.balance[a] = max(w.balance[a], 30_000 * RUPEE)
    tx = w.txn(a, cp, 8_000 * RUPEE, "IMPS", "TRANSFER", t0 + timedelta(minutes=6), "Family transfer", s)
    if tx:
        events.append(tx["id"])
    return {"events": events, "entities": [cid, a, dev]}


def declared_relative_twin(w: World, rm: str) -> dict:
    emp = w.employees[rm]
    brother = new_customer(w, emp["branch_id"], "SALARIED", datetime(2015, 7, 1, 12, tzinfo=IST),
                           name=f"Anil {emp['full_name'].split()[-1]}", address=emp["address_norm"],
                           pincode=emp["pincode"])
    brother["_scenario"] = True
    brother["_employer"] = w.rng.choice([a for a, v in w.accounts.items() if "payroll" in v["holder_name"]])
    brother["_landlord"] = None
    acct = new_account(w, brother, "SAVINGS", datetime(2015, 7, 1, 12, 20, tzinfo=IST),
                       w.rng.choice(staff(w, emp["branch_id"], "TELLER")),
                       w.rng.choice(staff(w, emp["branch_id"], "KYC_APPROVER")), "BRANCH_BIOMETRIC",
                       85_000)
    emp["declared_relations"] = [brother["id"]]
    w.add("relationship", id=w.seq("REL", 5), src_type="EMPLOYEE", src_id=rm, dst_type="CUSTOMER",
          dst_id=brother["id"], rel_type="DECLARED_RELATIVE", source="DECLARED", confidence=1.0,
          detail={"relation": "brother", "register": "Conflict-of-interest register 2025"},
          valid_from=datetime(2025, 4, 1, tzinfo=IST))
    return {"events": [], "entities": [rm, brother["id"], acct["id"]]}


def college_twin(w: World, pools) -> dict:
    br = "BR-014"
    c = new_customer(w, br, "INSTITUTION", datetime(2012, 6, 1, 11, tzinfo=IST))
    c["full_name"] = "Vidya Vardhini Commerce College"
    c["name_norm"] = c["full_name"].lower()
    c["_scenario"] = True
    a = new_account(w, c, "CURRENT", datetime(2012, 6, 1, 11, 30, tzinfo=IST),
                    w.rng.choice(staff(w, br, "TELLER")), w.rng.choice(staff(w, br, "KYC_APPROVER")),
                    "BRANCH_BIOMETRIC", 6_00_000, limit_rupees=25_00_000)
    a["holder_name"] = c["full_name"]
    students = [p for p in pools["person"]][:180] + [
        primary_account(w, s)["id"] for s, v in w.customers.items()
        if v["segment"] == "STUDENT" and primary_account(w, s)["status"] == "ACTIVE"][:120]
    events = []
    for i, src in enumerate(students):
        t = at(date(2026, 8, 1) + timedelta(days=i % 10), w.rng.randint(9, 21), w.rng.randint(0, 59))
        tx = w.txn(src, a["id"], 18_500 * RUPEE, "UPI", "FEE", t, "Term fee FY26-27", force=True)
        events.append(tx["id"])
    for m in (7, 8, 9):
        for k, p in enumerate(pools["person"][200:236]):
            w.txn(a["id"], p, w.rng.randint(28, 60) * 1000 * RUPEE, "NEFT", "PAYROLL",
                  at(date(2026, m, 1), 11) + timedelta(minutes=k), "Faculty salary")
    return {"events": events[:25], "entities": [a["id"], c["id"]]}


# ── entry points ──────────────────────────────────────────────────────────────


def inject_demo(w: World, pools) -> None:
    insider = "EMP-0417"
    x8120 = _ext(w, "Deepak Traders", "X-8120", "Meridian Bank")
    x9901 = _ext(w, "Shree Bullion House", "X-9901", "Konkan Coastal Bank")
    fixed_mules = {1: ("A-7731", date(2026, 8, 3)), 4: ("A-7768", date(2026, 8, 19))}
    mules, devices, fac_events = mule_factory(w, pools, insider, 11, date(2026, 7, 24),
                                              date(2026, 9, 19), fixed_mules)
    consolidator = consolidator_account(w, insider, "A-6604")
    act_events = mule_activity(w, pools, mules, consolidator, date(2026, 7, 28), date(2026, 9, 20))

    story = insider_chain(
        w, pools, insider=insider, t_login=at(date(2026, 9, 21), 21, 47, 10),
        mule_targets=["A-7731", "A-7768", x8120], consolidator=consolidator,
        amounts=[4_90_000], fixed={"victim_cust": "C-88213", "victim_acct": "A-5520",
                                   "victim_name": "Vimala Deshpande", "balance": 18_60_000,
                                   "dormant_since": datetime(2024, 7, 15, 10, tzinfo=IST),
                                   "session": "S-5591", "device": "D-9F2",
                                   "request_ref": "REQ-3391", "exit": x9901})
    _label(w, "S4", "suspicious", story["entities"], story["events"], chain_root=insider,
           demo=True)
    _label(w, "S5", "suspicious", [insider, consolidator], [], note="Address/surname match (see S4)")
    _label(w, "S7", "suspicious", [insider, *mules, *devices], fac_events + act_events[:40])

    twin = camp_twin(w, "EMP-0233", date(2026, 9, 21),
                     highlight={"cust": "C-77120", "acct": "A-4410", "ref": "SR-5521",
                                "t": at(date(2026, 9, 21), 21, 40, 12)})
    _label(w, "S4", "twin", twin["entities"], twin["events"])

    rel = declared_relative_twin(w, "EMP-0112")
    _label(w, "S5", "twin", rel["entities"], rel["events"])

    circ = circular(w, date(2026, 9, 8))
    _label(w, "S2", "suspicious", circ["entities"], circ["events"])
    loop = periodic_loan_twin(w)
    _label(w, "S2", "twin", loop["entities"], loop["events"])

    st = structuring(w, date(2026, 9, 15))
    _label(w, "S3", "suspicious", st["entities"], st["events"])
    kt = kirana_twin(w)
    _label(w, "S3", "twin", kt["entities"], kt["events"])

    ato = external_ato(w, pools, at(date(2026, 9, 17), 2, 14))
    _label(w, "S6", "suspicious", ato["entities"], ato["events"])
    np_ = new_phone_twin(w, at(date(2026, 9, 12), 10, 15))
    _label(w, "S6", "twin", np_["entities"], np_["events"])

    col = college_twin(w, pools)
    _label(w, "S7", "twin", col["entities"], col["events"])

    _label(w, "S1", "twin", [], [])
    sme = [a for a, v in w.accounts.items() if v["customer_id"]
           and w.customers[v["customer_id"]]["segment"] == "SME"
           and not w.customers[v["customer_id"]].get("_scenario")][:25]
    _label(w, "S8", "twin", sme, [])


def inject_training(w: World, pools) -> None:
    """Randomised instances for model training (independent world, no fixed IDs)."""
    rng = w.rng
    ops = [e for e, v in w.employees.items() if v["role"] == "OPS_OFFICER"]
    insiders = rng.sample(ops, 5)
    for n, insider in enumerate(insiders):
        emp = w.employees[insider]
        for perm in ("KYC_APPROVE", "ACCT_OPEN"):
            w.add("entitlement", id=w.seq("ENT", 5), employee_id=insider, permission_code=perm,
                  granted_by=emp["manager_id"], reason="Cross-training", request_ref=None,
                  valid_from=datetime(2025, 1, 2, tzinfo=IST), intended_expiry=None, revoked_at=None)
        day = rng.choice(working_days()[30:-3])
        mules, devs, fev = mule_factory(w, pools, insider, rng.randint(4, 9), day - timedelta(days=50),
                                        day - timedelta(days=3))
        _label(w, "S7", "suspicious", [insider, *mules, *devs], fev, instance=f"S7-s{n}")
        cons = consolidator_account(w, insider)
        mule_activity(w, pools, mules, cons, day - timedelta(days=45), day)
        targets = rng.sample(mules, 2) + ([_ext(w, "Trader")] if rng.random() < 0.6 else [])
        t_login = at(day, rng.randint(19, 23), rng.randint(0, 59)) if rng.random() < 0.7 else at(
            day, rng.randint(10, 17), rng.randint(0, 59))
        story = insider_chain(w, pools, insider=insider, t_login=t_login, mule_targets=targets,
                              consolidator=cons, amounts=[rng.randint(40, 99) * 1000 if rng.random() < 0.4
                                                          else rng.randint(300, 495) * 1000],
                              override=rng.random() < 0.7, raise_limit=rng.random() < 0.75,
                              grant_days_before=rng.choice([None, 3, 9, 20]),
                              accomplice_delay_min=rng.randint(8, 240),
                              payout_delay_min=rng.randint(25, 1500))
        _label(w, "S4", "suspicious", story["entities"], story["events"], instance=f"S4-s{n}",
               chain_root=insider)
    twins = [e for e in ops if e not in insiders]
    for n in range(6):
        d = rng.choice(working_days()[10:-2])
        tw = camp_twin(w, rng.choice(twins), d, n_extra=4)
        _label(w, "S4", "twin", tw["entities"], tw["events"], instance=f"S4-t{n}")
    for n in range(5):
        d = rng.choice(working_days()[5:-2])
        ato = external_ato(w, pools, at(d, rng.choice([1, 2, 3, 23]), rng.randint(0, 59)))
        _label(w, "S6", "suspicious", ato["entities"], ato["events"], instance=f"S6-s{n}")
        npt = new_phone_twin(w, at(rng.choice(working_days()[5:-2]), rng.randint(9, 20), 10))
        _label(w, "S6", "twin", npt["entities"], npt["events"], instance=f"S6-t{n}")
    for n in range(3):
        c = circular(w, rng.choice(working_days()[20:-4]), rng.randint(3, 12) * 100_000,
                     rng.uniform(0.85, 0.97))
        _label(w, "S2", "suspicious", c["entities"], c["events"], instance=f"S2-s{n}")
        t = periodic_loan_twin(w)
        _label(w, "S2", "twin", t["entities"], t["events"], instance=f"S2-t{n}")
    for n in range(3):
        s = structuring(w, rng.choice(working_days()[20:-5]))
        _label(w, "S3", "suspicious", s["entities"], s["events"], instance=f"S3-s{n}")
