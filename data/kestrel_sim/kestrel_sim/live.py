"""The live feed: the evening of 22 Sep, held back from the initial load and streamed in during a demo.

`build_live_feed` adds three things to a finished demo world. It uses its own random stream and runs
after everything else, so every row of the base world (and every number the demo shows before the
feed starts) is unchanged:

  • a new insider takeover by a different employee at another branch — an expired override, an
    after-hours VPN session, a dormant pensioner's mobile number and limit changed, an accomplice on
    a never-seen phone, payouts into the *same* mule ring and exit as the 21 Sep case;
  • a legitimate pension camp at a third branch — two mobile-number changes, each with a ticket, a
    biometric eKYC and a camp roster (Alibi should explain them and nothing should alert);
  • routine evening traffic — UPI payments, shop collections, family transfers, ATM cash, credits.

Rows timestamped before FEED_START stay in the world: the bank already knew them (the override
grant, the victim's 2009 account, the camp roster). Rows from FEED_START on move out of
`world.tables` into `world.live_feed`, in time order, for the ingest API to replay. Master data the
feed changes (the victim's mobile and limit) is reset to its value before the feed; each feed entry
carries the effect to apply when it is ingested.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import numpy as np

from kestrel_sim.baseline import RUPEE, primary_account, staff
from kestrel_sim.clock import IST, at
from kestrel_sim.scenarios import DEMO_STAFF, insider_chain
from kestrel_sim.world import World

LIVE_DAY = date(2026, 9, 22)
FEED_START = at(LIVE_DAY, 20, 0)
FEED_END = at(LIVE_DAY, 22, 45)
VICTIM_BALANCE = 21_40_000  # rupees

# When each kind of row happened — decides history vs. live feed.
TIME_KEY = {
    "entitlement": "valid_from", "roster": "shift_start", "customer": "created_at", "account": "opened_at",
    "device": "first_seen", "session": "started_at", "access_event": "occurred_at",
    "state_change": "occurred_at", "beneficiary": "added_at", "txn": "occurred_at", "work_item": "created_at",
}
# Insert order for rows with the same timestamp: a device before the session that uses it, and so on.
TABLE_RANK = {t: i for i, t in enumerate(["device", "session", "work_item", "access_event", "state_change",
                                          "beneficiary", "txn"])}
SOURCE_SYSTEM = {"access_event": "CBS application audit", "state_change": "Core banking",
                 "beneficiary": "Digital banking", "device": "Device registry"}


def _mask(phone: str | None) -> str:
    return f"+91 ••••• {phone[-4:]}" if phone else "—"


def _rupees(paise: int) -> str:
    r = paise / RUPEE
    return f"₹{r / 1e5:.2f} L" if r >= 1e5 else f"₹{r:,.0f}"


def _system(table: str, row: dict) -> str:
    if table == "session":
        if row["actor_type"] == "EMPLOYEE":
            return "VPN gateway" if row["channel"] == "VPN" else "Branch SSO"
        return "Digital banking"
    if table == "txn":
        return "ATM switch" if row["channel"] == "ATM" else f"{row['channel']} switch"
    if table == "work_item":
        return {"TICKET": "Service desk", "EKYC": "UIDAI eKYC"}.get(row["kind"], "Workflow")
    return SOURCE_SYSTEM.get(table, table)


def _summary(w: World, table: str, r: dict) -> str:
    def party(a: str) -> str:
        acct = w.accounts.get(a)
        return f"{a} · {acct['holder_name']}" if acct and acct["kind"] == "EXTERNAL" and a != "X-ATM" else a

    if table == "session":
        if r["actor_type"] == "EMPLOYEE":
            return f"{r['channel']} login · {r['actor_id']} on {r['device_id']} · {r['geo_city']}"
        return f"{r['channel'].title()} login · customer {r['actor_id']} · device {r['device_id'] or '—'}"
    if table == "access_event":
        target = r["account_id"] or r["customer_id"]
        fields = f" [{', '.join(r['fields'])}]" if r["fields"] else ""
        return f"{r['employee_id']} {r['action']} on {target}{fields}{' · OVERRIDE' if r['override_used'] else ''}"
    if table == "state_change":
        old, new = r["old_value"], r["new_value"]
        if r["field"] == "REGISTERED_MOBILE":
            old, new = _mask(old), _mask(new)
        elif r["field"] == "TXN_LIMIT":
            old, new = _rupees(int(old)), _rupees(int(new))
        what = r["field"].replace("_", " ").lower()
        return f"{r['account_id']} {what}: {old} → {new} · by {r['actor_id']} ({r['auth_method']})"
    if table == "beneficiary":
        return f"Payee added on {r['account_id']}: {r['counterparty_name']} ({r['counterparty_account']})"
    if table == "txn":
        if r["channel"] == "ATM":
            return f"ATM cash {_rupees(r['amount_paise'])} from {r['from_account']}"
        return (f"{r['channel']} {_rupees(r['amount_paise'])} · {party(r['from_account'])} → "
                f"{party(r['to_account'])} · {r['narration'] or r['kind']}")
    if table == "device":
        return f"New {r['kind'].lower()} device {r['id']} first seen"
    if table == "work_item":
        return f"{r['kind']} {r['ref']} · {r['text']}"
    return f"{table} {r.get('id')}"


# ── the three strands ─────────────────────────────────────────────────────────


def _attack(w: World, pools) -> dict:
    """A second insider at another branch; the same mule ring, consolidator and exit as 21 Sep."""
    ops = sorted(e for e, v in w.employees.items()
                 if v["role"] == "OPS_OFFICER" and v.get("_laptop") and v["branch_id"] != "BR-014"
                 and e not in DEMO_STAFF and staff(w, v["branch_id"], "TELLER")
                 and staff(w, v["branch_id"], "KYC_APPROVER"))
    insider = w.rng.choice(ops)
    courier = w.rng.choice(sorted(pools["business"]))
    story = insider_chain(
        w, pools, insider=insider, t_login=at(LIVE_DAY, 20, 31, 15),
        mule_targets=["A-7731", "A-7768", courier], consolidator="A-6604",
        amounts=[4_85_000, 4_70_000, 4_60_000], override=True, raise_limit=True, grant_days_before=6,
        accomplice_delay_min=14, payout_delay_min=41,
        fixed={"balance": VICTIM_BALANCE, "dormant_since": datetime(2023, 11, 2, 10, tzinfo=IST),
               "exit": "X-9901"},
    )
    return {"insider": insider, "courier": courier, **story}


def _camp(w: World, avoid_branches: set[str]) -> dict:
    """Legitimate: a scheduled evening pension camp. Every update has a ticket, an eKYC and a roster."""
    officers = sorted(e for e, v in w.employees.items()
                      if v["role"] == "OPS_OFFICER" and v["branch_id"] not in avoid_branches and e not in DEMO_STAFF)
    officer = w.rng.choice(officers)
    emp = w.employees[officer]
    branch = emp["branch_id"]
    w.add("roster", id=w.seq("RS", 6), employee_id=officer, shift_start=at(LIVE_DAY, 17, 30),
          shift_end=at(LIVE_DAY, 22, 30), duty_type="CAMP")
    sess = w.session("EMPLOYEE", officer, emp["_terminal"], "BRANCH", at(LIVE_DAY, 17, 35), 290, geo=emp["_city"])["id"]
    pensioners = sorted(c for c, v in w.customers.items()
                        if v["branch_id"] == branch and v["segment"] == "PENSIONER" and not v.get("_scenario")
                        and not v.get("_mule") and primary_account(w, c)["status"] == "ACTIVE")
    picks = w.rng.sample(pensioners, 2)
    for cid, t in zip(picks, [at(LIVE_DAY, 20, 24, 40), at(LIVE_DAY, 21, 18, 5)], strict=True):
        acct = primary_account(w, cid)
        w.work_item("TICKET", f"SR-{w.rng.randint(6000, 6999)}", t - timedelta(minutes=12), cid, acct["id"], officer,
                    branch, "Pension camp: update registered mobile number — customer present, "
                            "Aadhaar biometric verified")
        w.work_item("EKYC", f"EKYC-{w.rng.randint(100000, 999999)}", t - timedelta(minutes=2), cid, acct["id"],
                    officer, branch, "Aadhaar biometric eKYC — success", 2)
        w.access(officer, sess, "ACCT_VIEW", t - timedelta(minutes=1), acct["id"], cid, ["profile", "registered_mobile"])
        w.access(officer, sess, "MOBILE_UPDATE", t, acct["id"], cid, ["registered_mobile"])
        w.state_change(acct["id"], "REGISTERED_MOBILE", acct["_raw_mobile"], w.phone(), "EMPLOYEE", officer,
                       "BIOMETRIC", t, sess)
    return {"officer": officer, "branch": branch, "customers": picks}


def _routine(w: World, pools, avoid: set[str], n: int = 140) -> None:
    """Ordinary evening traffic, shaped like the baseline customer simulation."""
    primary: dict[str, dict] = {}
    for a in w.accounts.values():
        if a["customer_id"] and a["customer_id"] not in primary:
            primary[a["customer_id"]] = a
    people = sorted(c for c, v in w.customers.items()
                    if not v.get("_scenario") and not v.get("_mule") and c not in avoid
                    and c in primary and primary[c]["status"] == "ACTIVE")
    by_seg: dict[str, list[str]] = {}
    for c in people:
        by_seg.setdefault(w.customers[c]["segment"], []).append(c)
    span = int((FEED_END - FEED_START).total_seconds()) - 300
    kinds = ["merchant"] * 7 + ["collect"] * 3 + ["family"] + ["atm"] * 2 + ["credit"] * 2

    def mobile(cid: str, t: datetime) -> str:
        cust = w.customers[cid]
        return w.session("CUSTOMER", cid, w.customer_device.get(cid), "MOBILE", t - timedelta(seconds=w.rng.randint(25, 90)),
                         6, geo=cust["_city"])["id"]

    for _ in range(n):
        t = FEED_START + timedelta(seconds=w.rng.randint(90, span))
        kind = w.rng.choice(kinds)
        if kind == "collect" and by_seg.get("SHOPKEEPER"):
            a = primary[w.rng.choice(by_seg["SHOPKEEPER"])]["id"]
            w.txn(w.rng.choice(pools["person"]), a, w.rng.randint(80, 2500) * RUPEE, "UPI", "UPI_CREDIT", t, "UPI collect")
            continue
        cid = w.rng.choice(people)
        a = primary[cid]["id"]
        if kind == "merchant":
            amt = max(40, int(w.np_rng.lognormal(6.4, 0.9)))
            w.txn(a, w.rng.choice(pools["merchant"]), amt * RUPEE, "UPI", "UPI_PAY", t, "UPI merchant", mobile(cid, t))
        elif kind == "family" and w.payees.get(a):
            w.txn(a, w.rng.choice(sorted(w.payees[a])), w.rng.randint(1, 30) * 1000 * RUPEE, "IMPS", "TRANSFER", t,
                  "Family transfer", mobile(cid, t))
        elif kind == "atm":
            w.txn(a, "X-ATM", w.rng.choice([2000, 3000, 5000, 10000]) * RUPEE, "ATM", "ATM_WITHDRAWAL", t, "ATM cash")
        else:
            w.txn(w.rng.choice(pools["person"]), a, w.rng.randint(2, 25) * 1000 * RUPEE, "UPI", "CREDIT", t,
                  "Transfer from family")


# ── assembly ──────────────────────────────────────────────────────────────────


def build_live_feed(w: World, pools) -> None:
    saved = (w.rng, w.np_rng)
    w.rng, w.np_rng = random.Random(w.seed + 7919), np.random.default_rng(w.seed + 7919)

    def mark() -> dict[str, int]:
        return {t: len(rows) for t, rows in w.tables.items()}

    try:
        m0 = mark()
        attack = _attack(w, pools)
        m1 = mark()
        insider_branch = w.employees[attack["insider"]]["branch_id"]
        camp = _camp(w, {insider_branch, "BR-014"})
        m2 = mark()
        _routine(w, pools, avoid=set(camp["customers"]) | {attack["victim_cust"]})
    finally:
        w.rng, w.np_rng = saved

    def strand(table: str, i: int) -> str:
        if i < m1.get(table, 0):
            return "attack"
        return "camp" if i < m2.get(table, 0) else "routine"

    feed: list[dict] = []
    for table, rows in list(w.tables.items()):
        start = m0.get(table, 0)
        keep = rows[:start]
        for i in range(start, len(rows)):
            r = rows[i]
            t = r.get(TIME_KEY.get(table, ""))
            if t is None or t < FEED_START:
                keep.append(r)
                continue
            effect = None
            if table == "state_change" and r["field"] in ("REGISTERED_MOBILE", "TXN_LIMIT"):
                effect = {"account_id": r["account_id"], "field": r["field"], "old": r["old_value"], "new": r["new_value"]}
            feed.append({"table": table, "row": r, "t": t, "system": _system(table, r),
                         "summary": _summary(w, table, r), "effect": effect, "strand": strand(table, i)})
        w.tables[table] = keep

    feed.sort(key=lambda e: (e["t"], TABLE_RANK.get(e["table"], 99), e["row"]["id"]))
    # Master data as the bank knew it before tonight: undo the feed's changes, latest first.
    for e in reversed(feed):
        if e["effect"]:
            acct = w.accounts[e["effect"]["account_id"]]
            if e["effect"]["field"] == "REGISTERED_MOBILE":
                acct["_raw_mobile"] = e["effect"]["old"]
            else:
                acct["daily_limit_paise"] = int(e["effect"]["old"])
    # The victim's account is new to the world, so its snapshot balance is still the opening one.
    w.accounts[attack["victim_acct"]]["balance_paise"] = VICTIM_BALANCE * RUPEE

    for i, e in enumerate(feed, start=1):
        e["seq"] = i
    w.live_feed = feed
    w.live_meta = {
        "feed_start": FEED_START.isoformat(), "feed_end": feed[-1]["t"].isoformat() if feed else None,
        "rows": len(feed), "insider": attack["insider"], "insider_branch": insider_branch,
        "victim_customer": attack["victim_cust"], "victim_account": attack["victim_acct"],
        "camp_officer": camp["officer"], "camp_branch": camp["branch"], "camp_customers": camp["customers"],
        "mule_targets": ["A-7731", "A-7768", attack["courier"]], "consolidator": "A-6604", "exit": "X-9901",
    }
