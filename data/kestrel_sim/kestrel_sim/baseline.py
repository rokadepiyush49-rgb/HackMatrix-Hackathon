"""Legitimate day-to-day life of Kestrel Urban Co-operative Bank (fictional).

Everything here is *normal* behaviour — including the awkward-but-legitimate patterns
that fool naive detectors: month-end overtime, salary-day fan-out, limit increases for
property payments, vague tickets, curiosity look-ups, new phones after a mobile change.
Suspicious behaviour is injected separately (scenarios.py).
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from datetime import date, datetime, timedelta

from kestrel_sim import names
from kestrel_sim.clock import (
    IST,
    WINDOW_START,
    at,
    days,
    is_bank_holiday,
    last_working_day_of_month,
    month_ends,
    working_days,
)
from kestrel_sim.world import World

RUPEE = 100  # paise

BRANCHES = [("BR-014", "Kothrud", "Pune"), ("BR-021", "Hadapsar", "Pune"),
            ("BR-033", "Nashik Road", "Nashik")]

ROLE_PLAN = [("BRANCH_MANAGER", 1), ("OPS_OFFICER", 5), ("TELLER", 6), ("RM", 5),
             ("KYC_APPROVER", 2), ("IT_ADMIN", 1)]

ROLE_LABEL = {"BRANCH_MANAGER": "Branch Manager", "OPS_OFFICER": "Ops Officer",
              "TELLER": "Teller", "RM": "Relationship Mgr", "KYC_APPROVER": "KYC Approver",
              "IT_ADMIN": "IT Admin"}

PERMISSIONS = {
    "ACCT_VIEW": ("View account & customer profile", "LOW"),
    "CUST_SEARCH": ("Search customers", "LOW"),
    "CASH_DEPOSIT": ("Post cash deposits / withdrawals", "MED"),
    "MOBILE_UPDATE": ("Update registered mobile (OTP / biometric)", "HIGH"),
    "MOBILE_UPDATE_OVERRIDE": ("Update registered mobile without OTP (override)", "HIGH"),
    "ADDRESS_UPDATE": ("Update address", "MED"),
    "LIMIT_CHANGE": ("Change transfer limits", "HIGH"),
    "CARD_ISSUE": ("Issue / reissue debit cards", "HIGH"),
    "KYC_APPROVE": ("Approve KYC for new accounts", "HIGH"),
    "ACCT_OPEN": ("Open new accounts", "MED"),
    "USER_ADMIN": ("Administer staff user accounts", "HIGH"),
}

ROLE_PERMS = {
    "TELLER": ["ACCT_VIEW", "CUST_SEARCH", "CASH_DEPOSIT", "ACCT_OPEN"],
    "OPS_OFFICER": ["ACCT_VIEW", "CUST_SEARCH", "MOBILE_UPDATE", "ADDRESS_UPDATE",
                    "LIMIT_CHANGE", "CARD_ISSUE"],
    "RM": ["ACCT_VIEW", "CUST_SEARCH"],
    "KYC_APPROVER": ["ACCT_VIEW", "CUST_SEARCH", "KYC_APPROVE", "ACCT_OPEN"],
    "BRANCH_MANAGER": ["ACCT_VIEW", "CUST_SEARCH", "LIMIT_CHANGE", "MOBILE_UPDATE",
                       "MOBILE_UPDATE_OVERRIDE", "KYC_APPROVE"],
    "IT_ADMIN": ["USER_ADMIN", "ACCT_VIEW"],
}

SEGMENTS = [("SALARIED", 0.33), ("PENSIONER", 0.15), ("SHOPKEEPER", 0.08), ("SME", 0.05),
            ("STUDENT", 0.12), ("HOMEMAKER", 0.15), ("SELF_EMPLOYED", 0.12)]

TICKET_TEXT = {
    "MOBILE_UPDATE": [
        "Update registered mobile number — customer visited with Aadhaar",
        "Change of registered mobile number (form MU-12), old SIM discontinued",
        "Customer lost phone; requests new registered mobile number",
    ],
    "ADDRESS_UPDATE": ["Address change request with electricity bill as proof",
                       "Update communication address after house shift"],
    "LIMIT_CHANGE": ["Increase IMPS transfer limit for property booking payment",
                     "Raise per-transaction limit to pay vehicle dealer",
                     "Increase transfer limit for tuition fee payment"],
    "CARD_ISSUE": ["Debit card reissue — card damaged", "New debit card, previous card expired"],
    "STATEMENT": ["Account statement for visa application", "Interest certificate for tax filing",
                  "Passbook update and statement for loan application"],
}
VAGUE_TEXT = ["General service request", "Customer query", "Branch request — see file"]

# per-transaction limit (stored in account.daily_limit_paise for historical reasons)
LIMIT_BY_SEGMENT = {"SME": 10_00_000, "SHOPKEEPER": 2_00_000}
DEFAULT_LIMIT = 1_00_000


def _norm(s: str) -> str:
    return " ".join(s.lower().replace(",", " ").replace(".", " ").split())


# ── organisation ──────────────────────────────────────────────────────────────


def build_org(w: World, fixed_staff: dict[str, dict]) -> None:
    for code, (name, sens) in PERMISSIONS.items():
        w.add("permission", code=code, name=name, sensitivity=sens)
    for bid, locality, city in BRANCHES:
        w.add("branch", id=bid, name=f"{locality} Branch", city=city)

    w.reserve(*fixed_staff.keys())
    for bid, _locality, city in BRANCHES:
        staff: list[tuple[str, str]] = []
        fixed_here = {k: v for k, v in fixed_staff.items() if v["branch"] == bid}
        for role, count in ROLE_PLAN:
            fixed_roles = [k for k, v in fixed_here.items() if v["role"] == role]
            for i in range(count):
                eid = fixed_roles[i] if i < len(fixed_roles) else emp_id(w)
                staff.append((eid, role))
        manager_id = next(e for e, r in staff if r == "BRANCH_MANAGER")
        for eid, role in staff:
            fx = fixed_staff.get(eid, {})
            loc, pin = w.rng.choice(names.LOCALITIES[city])
            full = fx.get("name") or f"{w.rng.choice(names.FIRST)} {w.rng.choice(names.LAST)}"
            address = fx.get("address") or (
                f"flat {w.rng.randint(1, 400)}{w.rng.choice('ABCD')} {w.rng.choice(names.BUILDINGS)} {loc} {city} {pin}")
            hire = fx.get("hire") or date(w.rng.randint(2010, 2024), w.rng.randint(1, 12), 1)
            emp = w.add("employee", id=eid, pseudonym=f"{ROLE_LABEL[role]} · {bid}",
                        full_name=full, branch_id=bid, role=role,
                        manager_id=None if eid == manager_id else manager_id, hire_date=hire,
                        status="ACTIVE", address_norm=_norm(address),
                        pincode=fx.get("pincode") or pin, _raw_phone=w.phone(),
                        declared_relations=[], _city=city, _laptop_id=fx.get("laptop"))
            w.employees[eid] = emp
            since = datetime(max(hire.year, 2024), 1, 2, 10, 0, tzinfo=IST)
            for perm in ROLE_PERMS[role] + fx.get("extra_perms", []):
                w.add("entitlement", id=w.seq("ENT", 5), employee_id=eid, permission_code=perm,
                      granted_by=manager_id if eid != manager_id else None,
                      reason="Role baseline" if perm in ROLE_PERMS[role] else "Cross-training",
                      request_ref=None, valid_from=since, intended_expiry=None, revoked_at=None)


def emp_id(w: World) -> str:
    while True:
        eid = f"EMP-{w.rng.randint(100, 999):04d}"
        if eid not in w._used:
            w.reserve(eid)
            return eid


def assign_staff_devices(w: World) -> None:
    """Branch terminal for everyone; VPN laptops for ops officers, managers and IT."""
    for n, (_eid, emp) in enumerate(sorted(w.employees.items())):
        emp["_terminal"] = new_device(w, "BRANCH_TERMINAL", datetime(2024, 1, 2, tzinfo=IST),
                                      did=f"BT-{emp['branch_id'][-3:]}-{n:02d}")
        if emp["role"] in ("OPS_OFFICER", "BRANCH_MANAGER", "IT_ADMIN"):
            emp["_laptop"] = new_device(w, "LAPTOP", datetime(2024, 3, 1, tzinfo=IST),
                                        did=emp.get("_laptop_id") or f"LAP-{w.rng.randint(100, 999)}")


def staff(w: World, branch: str, role: str) -> list[str]:
    return [e for e, r in w.employees.items() if r["branch_id"] == branch and r["role"] == role]


def build_rosters(w: World) -> dict[tuple[str, date], tuple[datetime, datetime]]:
    """Regular shifts plus month-end overtime. Returns (employee, day) → shift window."""
    shifts: dict[tuple[str, date], tuple[datetime, datetime]] = {}
    for d in working_days():
        for eid, emp in w.employees.items():
            if w.rng.random() < 0.04:  # leave
                continue
            start, end = (at(d, 11), at(d, 20)) if emp["role"] == "IT_ADMIN" else (at(d, 9, 30), at(d, 18, 30))
            w.add("roster", id=w.seq("RS", 6), employee_id=eid, shift_start=start,
                  shift_end=end, duty_type="REGULAR")
            shifts[(eid, d)] = (start, end)
    for d in month_ends():
        for bid, _, _ in BRANCHES:
            for eid in w.rng.sample(staff(w, bid, "OPS_OFFICER"), 2):
                if (eid, d) in shifts:
                    w.add("roster", id=w.seq("RS", 6), employee_id=eid, shift_start=at(d, 18, 30),
                          shift_end=at(d, 21, 30), duty_type="OVERTIME")
                    s, _ = shifts[(eid, d)]
                    shifts[(eid, d)] = (s, at(d, 21, 30))
    return shifts


# ── external counterparties ───────────────────────────────────────────────────


def build_externals(w: World) -> dict[str, list[str]]:
    pools: dict[str, list[str]] = defaultdict(list)

    def ext(holder: str, bank: str, pool: str, xid: str | None = None) -> str:
        xid = xid or w.rid("X", 4)
        acct = w.add("account", id=xid, customer_id=None, kind="EXTERNAL", holder_name=holder,
                     bank_name=bank, branch_id=None, status="ACTIVE", status_since=None,
                     opened_at=None, opened_by=None, kyc_approved_by=None, opening_mode=None,
                     daily_limit_paise=0, balance_paise=0, _raw_mobile=None)
        w.accounts[xid] = acct
        pools[pool].append(xid)
        return xid

    w.reserve("X-CASH", "X-ATM", "X-TRSY")
    ext("Cash — branch counter", "Kestrel UCB", "cash", "X-CASH")
    ext("ATM network withdrawal", "ATM network", "atm", "X-ATM")
    ext("State Treasury — pension disbursal", "Treasury", "treasury", "X-TRSY")
    for e in names.EMPLOYERS:
        ext(f"{e} Pvt Ltd — payroll", w.rng.choice(names.BANKS), "employer")
    for m in names.MERCHANTS:
        ext(m, w.rng.choice(names.BANKS), "merchant")
    for _ in range(420):
        ext(f"{w.rng.choice(names.FIRST)} {w.rng.choice(names.LAST)}", w.rng.choice(names.BANKS), "person")
    for _ in range(60):
        ext(f"{w.rng.choice(names.LAST)} {w.rng.choice(names.TRADE_WORDS)}",
            w.rng.choice(names.BANKS), "business")
    for _ in range(12):
        ext(f"{w.rng.choice(names.LAST)} Builders & Developers", w.rng.choice(names.BANKS), "builder")
    return pools


# ── customers & accounts ──────────────────────────────────────────────────────


def _dob(w: World, segment: str) -> date:
    lo, hi = {"PENSIONER": (60, 84), "STUDENT": (18, 24)}.get(segment, (24, 58))
    return date(2026 - w.rng.randint(lo, hi), w.rng.randint(1, 12), w.rng.randint(1, 28))


def new_customer(w: World, branch: str, segment: str, t_created: datetime,
                 cid: str | None = None, name: str | None = None, address: str | None = None,
                 pincode: str | None = None, phone: str | None = None) -> dict:
    city = next(c for b, _, c in BRANCHES if b == branch)
    loc, pin = w.rng.choice(names.LOCALITIES[city])
    name = name or f"{w.rng.choice(names.FIRST)} {w.rng.choice(names.LAST)}"
    addr = address or f"{w.rng.randint(1, 400)}{w.rng.choice('ABCD')} {w.rng.choice(names.BUILDINGS)} {loc} {city} {pin}"
    rms = staff(w, branch, "RM")
    cust = w.add("customer", id=cid or w.rid("C", 5), full_name=name, name_norm=_norm(name),
                 dob=_dob(w, segment), segment=segment, address_norm=_norm(addr),
                 pincode=pincode or pin, _raw_phone=phone or w.phone(),
                 _raw_kyc=f"XXXX{w.rng.randint(1000, 9999)}{w.rng.randint(1000, 9999)}",
                 rm_employee_id=w.rng.choice(rms) if rms else None, branch_id=branch,
                 created_at=t_created, _city=city)
    w.customers[cust["id"]] = cust
    return cust


def new_account(w: World, cust: dict, kind: str, opened_at: datetime, opened_by: str | None,
                approver: str | None, mode: str, balance_rupees: int, aid: str | None = None,
                status: str = "ACTIVE", status_since: datetime | None = None,
                limit_rupees: int | None = None) -> dict:
    limit = limit_rupees or LIMIT_BY_SEGMENT.get(cust["segment"], DEFAULT_LIMIT)
    acct = w.add("account", id=aid or w.rid("A", 4), customer_id=cust["id"], kind=kind,
                 holder_name=cust["full_name"], bank_name="Kestrel UCB", branch_id=cust["branch_id"],
                 status=status, status_since=status_since, opened_at=opened_at, opened_by=opened_by,
                 kyc_approved_by=approver, opening_mode=mode, daily_limit_paise=limit * RUPEE,
                 balance_paise=0, _raw_mobile=cust["_raw_phone"])
    w.accounts[acct["id"]] = acct
    w.balance[acct["id"]] = balance_rupees * RUPEE
    return acct


def new_device(w: World, kind: str, first_seen: datetime, did: str | None = None) -> str:
    while did is None or (did in w.devices):
        did = f"D-{w.rng.randint(0x1000, 0xFFFF):04X}"
    w.reserve(did)
    dev = w.add("device", id=did, fingerprint=f"{w.rng.getrandbits(64):016x}", kind=kind,
                first_seen=first_seen)
    w.devices[did] = dev
    return did


OPENING_BALANCE = {"SALARIED": (20_000, 300_000), "PENSIONER": (60_000, 900_000),
                   "SHOPKEEPER": (60_000, 500_000), "SME": (300_000, 2_500_000),
                   "STUDENT": (2_000, 30_000), "HOMEMAKER": (5_000, 120_000),
                   "SELF_EMPLOYED": (20_000, 400_000)}


def build_customers(w: World, n: int, pools: dict[str, list[str]],
                    historic_approver_bias: dict[str, float]) -> None:
    segs, weights = zip(*SEGMENTS, strict=True)
    for _ in range(n):
        branch = w.rng.choices([b for b, _, _ in BRANCHES], weights=[0.4, 0.35, 0.25])[0]
        seg = w.rng.choices(segs, weights=weights)[0]
        created = datetime(w.rng.randint(2008, 2026), w.rng.randint(1, 12), w.rng.randint(1, 28),
                           w.rng.randint(10, 17), w.rng.randint(0, 59), tzinfo=IST)
        created = min(created, WINDOW_START - timedelta(days=30))
        cust = new_customer(w, branch, seg, created)
        approver = _historic_approver(w, branch, created, historic_approver_bias)
        opener = w.rng.choice(staff(w, branch, "TELLER"))
        kind = "CURRENT" if seg in ("SME", "SHOPKEEPER") else "SAVINGS"
        lo, hi = OPENING_BALANCE[seg]
        status, since = "ACTIVE", None
        if kind == "SAVINGS" and w.rng.random() < 0.03:
            status = "INOPERATIVE"
            since = WINDOW_START - timedelta(days=w.rng.randint(760, 1200))
        acct = new_account(w, cust, kind, created, opener, approver, "BRANCH_BIOMETRIC",
                           int(w.rng.uniform(lo, hi)), status=status, status_since=since)
        if w.rng.random() < 0.18:  # second account
            second = min(created + timedelta(days=w.rng.randint(30, 900)), WINDOW_START - timedelta(days=2))
            new_account(w, cust, "SAVINGS", second,
                        opener, approver, "BRANCH_BIOMETRIC", int(w.rng.uniform(lo, hi) / 4))
        # devices & payees
        w.customer_device[cust["id"]] = new_device(
            w, w.rng.choice(["ANDROID", "ANDROID", "IOS"]), created + timedelta(days=5))
        for _ in range(w.rng.randint(1, 4)):
            cp = w.rng.choice(pools["person"])
            w.beneficiary(acct["id"], cp, w.accounts[cp]["holder_name"],
                          WINDOW_START - timedelta(days=w.rng.randint(40, 900)))
        cust["_employer"] = w.rng.choice(pools["employer"]) if seg == "SALARIED" else None
        cust["_landlord"] = w.rng.choice(pools["person"]) if seg == "SALARIED" and w.rng.random() < 0.5 else None
        if cust["_landlord"]:
            w.beneficiary(acct["id"], cust["_landlord"], w.accounts[cust["_landlord"]]["holder_name"],
                          WINDOW_START - timedelta(days=w.rng.randint(60, 700)))


def _historic_approver(w: World, branch: str, t: datetime, bias: dict[str, float]) -> str:
    """KYC approver for historic openings. `bias` lets cross-trained staff approve a small share."""
    if t >= WINDOW_START - timedelta(days=365):
        for eid, share in bias.items():
            if w.employees[eid]["branch_id"] == branch and w.rng.random() < share:
                return eid
    return w.rng.choice(staff(w, branch, "KYC_APPROVER"))


def primary_account(w: World, cid: str) -> dict:
    return next(a for a in w.accounts.values() if a["customer_id"] == cid)


# ── staff behaviour ───────────────────────────────────────────────────────────


class StaffDay:
    """Helper for one employee's working day: a branch session and task timestamps."""

    def __init__(self, w: World, eid: str, d: date, shift: tuple[datetime, datetime]):
        self.w, self.eid, self.d = w, eid, d
        self.start, self.end = shift
        emp = w.employees[eid]
        self.branch = emp["branch_id"]
        self.terminal = emp["_terminal"]
        self.session = w.session("EMPLOYEE", eid, self.terminal, "BRANCH",
                                 self.start + timedelta(minutes=4),
                                 int((self.end - self.start).total_seconds() / 60) - 8,
                                 geo=emp["_city"], ip=f"10.14.{int(self.branch[-2:])}.{w.rng.randint(10, 99)}")["id"]

    def slot(self) -> datetime:
        span = (self.end - self.start).total_seconds() - 1800
        return self.start + timedelta(seconds=900 + self.w.rng.random() * span)


def run_staff(w: World, shifts: dict, branch_customers: dict[str, list[str]]) -> None:
    for (eid, d), shift in sorted(shifts.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        role = w.employees[eid]["role"]
        if role == "IT_ADMIN":
            continue
        day = StaffDay(w, eid, d, shift)
        pool = branch_customers[day.branch]
        if role == "TELLER":
            for _ in range(w.rng.randint(8, 14)):
                walk_in(w, day, w.rng.choice(pool))
        elif role == "OPS_OFFICER":
            for _ in range(w.rng.randint(4, 8)):
                service_request(w, day, w.rng.choice(pool))
        elif role == "RM":
            portfolio = [c for c in pool if w.customers[c]["rm_employee_id"] == eid]
            for _ in range(w.rng.randint(3, 7)):
                if portfolio and w.rng.random() < 0.9:
                    cid = w.rng.choice(portfolio)
                    acct = primary_account(w, cid)
                    w.access(eid, day.session, "ACCT_VIEW", day.slot(), acct["id"], cid,
                             ["balance", "transactions"])
                else:
                    service_request(w, day, w.rng.choice(pool), kinds=["STATEMENT"])
        elif role == "BRANCH_MANAGER":
            for _ in range(w.rng.randint(1, 3)):
                manager_approval(w, day, w.rng.choice(pool))
        elif role == "KYC_APPROVER":
            for _ in range(w.rng.randint(0, 3)):
                cid = w.rng.choice(pool)
                acct = primary_account(w, cid)
                t = day.slot()
                w.work_item("QUEUE", w.seq("KQ", 5), t - timedelta(minutes=20), cid, acct["id"],
                            eid, day.branch, "Periodic KYC re-verification queue")
                w.access(eid, day.session, "ACCT_VIEW", t, acct["id"], cid, ["kyc_documents"])
        # curiosity look-ups: benign but unexplained (no work item)
        if role in ("TELLER", "OPS_OFFICER", "RM") and w.rng.random() < 0.12:
            cid = w.rng.choice(pool)
            w.access(eid, day.session, "ACCT_VIEW", day.slot(), primary_account(w, cid)["id"],
                     cid, ["balance"])


def walk_in(w: World, day: StaffDay, cid: str) -> None:
    cust = w.customers[cid]
    acct = primary_account(w, cid)
    if acct["status"] != "ACTIVE":
        return
    t = day.slot()
    w.work_item("TOKEN", f"TKN-{w.rng.randint(100, 999)}", t - timedelta(minutes=6), cid,
                acct["id"], day.eid, day.branch, "Counter token — walk-in customer", 15)
    w.access(day.eid, day.session, "CUST_SEARCH", t, None, cid)
    w.access(day.eid, day.session, "ACCT_VIEW", t + timedelta(seconds=40), acct["id"], cid,
             ["balance"])
    r = w.rng.random()
    if r < 0.55:
        amt = int(w.np_rng.lognormal(9.4, 0.8)) // 100 * 100
        amt = max(500, min(amt, 45_000 if cust["segment"] != "SHOPKEEPER" else 49_000))
        w.access(day.eid, day.session, "CASH_DEPOSIT", t + timedelta(minutes=2), acct["id"], cid)
        w.txn("X-CASH", acct["id"], amt * RUPEE, "CASH", "CASH_DEPOSIT", t + timedelta(minutes=2),
              "Cash deposit at counter", branch_id=day.branch)
    elif r < 0.8:
        amt = max(500, int(w.np_rng.lognormal(8.6, 0.6)) // 100 * 100)
        w.access(day.eid, day.session, "CASH_DEPOSIT", t + timedelta(minutes=2), acct["id"], cid)
        w.txn(acct["id"], "X-CASH", amt * RUPEE, "CASH", "CASH_WITHDRAWAL", t + timedelta(minutes=2),
              "Cash withdrawal at counter", branch_id=day.branch)


def service_request(w: World, day: StaffDay, cid: str, kinds: list[str] | None = None,
                    t: datetime | None = None, force_vague: bool | None = None) -> None:
    acct = primary_account(w, cid)
    if acct["status"] != "ACTIVE":
        return
    kind = w.rng.choices(kinds or ["MOBILE_UPDATE", "ADDRESS_UPDATE", "LIMIT_CHANGE",
                                   "CARD_ISSUE", "STATEMENT"],
                         weights=None if kinds else [0.22, 0.18, 0.14, 0.2, 0.26])[0]
    t = t or day.slot()
    vague = (w.rng.random() < 0.06) if force_vague is None else force_vague
    text = w.rng.choice(VAGUE_TEXT if vague else TICKET_TEXT[kind])
    if w.rng.random() < 0.3:
        w.work_item("CALL", f"IVR-{w.rng.randint(10000, 99999)}", t - timedelta(hours=w.rng.randint(1, 20)),
                    cid, acct["id"], None, day.branch, f"Call centre: customer asked about {kind.lower().replace('_', ' ')}", 10)
    wrong_link = w.rng.random() < 0.03
    ticket_acct = (primary_account(w, w.rng.choice(list(w.customers)))["id"] if wrong_link else acct["id"])
    w.work_item("TICKET", f"SR-{w.rng.randint(1000, 9999)}", t - timedelta(minutes=w.rng.randint(5, 50)),
                None if wrong_link else cid, ticket_acct, day.eid, day.branch, text, 45)
    w.access(day.eid, day.session, "ACCT_VIEW", t, acct["id"], cid, ["profile", "contact"])
    t2 = t + timedelta(minutes=w.rng.randint(2, 6))
    if kind == "MOBILE_UPDATE":
        new_phone = w.phone()
        auth = w.rng.choice(["OTP_OLD_NUMBER", "OTP_OLD_NUMBER", "BIOMETRIC"])
        w.access(day.eid, day.session, "MOBILE_UPDATE", t2, acct["id"], cid, ["registered_mobile"])
        w.state_change(acct["id"], "REGISTERED_MOBILE", acct["_raw_mobile"], new_phone, "EMPLOYEE",
                       day.eid, auth, t2, day.session)
        w.customers[cid]["_raw_phone"] = new_phone
        if w.rng.random() < 0.7:  # new handset follows
            w.customers[cid]["_pending_new_device"] = t2 + timedelta(hours=w.rng.randint(2, 60))
    elif kind == "ADDRESS_UPDATE":
        w.access(day.eid, day.session, "ADDRESS_UPDATE", t2, acct["id"], cid, ["address"])
        w.state_change(acct["id"], "ADDRESS", "previous address", "new address", "EMPLOYEE",
                       day.eid, "DOCUMENT", t2, day.session)
    elif kind == "LIMIT_CHANGE":
        old = acct["daily_limit_paise"]
        new = old * w.rng.choice([2, 3, 5])
        w.access(day.eid, day.session, "LIMIT_CHANGE", t2, acct["id"], cid, ["txn_limit"])
        w.state_change(acct["id"], "TXN_LIMIT", str(old), str(new), "EMPLOYEE", day.eid,
                       "MAKER_CHECKER", t2, day.session)
        w.customers[cid]["_big_payment"] = (t2 + timedelta(hours=w.rng.randint(6, 70)), new)
    elif kind == "CARD_ISSUE":
        w.access(day.eid, day.session, "CARD_ISSUE", t2, acct["id"], cid, ["debit_card"])


def manager_approval(w: World, day: StaffDay, cid: str) -> None:
    acct = primary_account(w, cid)
    t = day.slot()
    w.work_item("QUEUE", w.seq("AQ", 5), t - timedelta(minutes=30), cid, acct["id"], day.eid,
                day.branch, "Approval queue — limit / service exception")
    w.access(day.eid, day.session, "ACCT_VIEW", t, acct["id"], cid, ["profile"])
    if w.rng.random() < 0.05 and acct["status"] == "ACTIVE":
        # legitimate override: biometric failed for an elderly customer, documented in a ticket
        new_phone = w.phone()
        w.work_item("TICKET", f"SR-{w.rng.randint(1000, 9999)}", t - timedelta(minutes=15), cid,
                    acct["id"], day.eid, day.branch,
                    "Update registered mobile number: biometric mismatch for senior citizen, manager override, ID verified in person")
        w.access(day.eid, day.session, "MOBILE_UPDATE", t + timedelta(minutes=3), acct["id"], cid,
                 ["registered_mobile"], override=True)
        w.state_change(acct["id"], "REGISTERED_MOBILE", acct["_raw_mobile"], new_phone, "EMPLOYEE",
                       day.eid, "OVERRIDE", t + timedelta(minutes=3), day.session)
        w.customers[cid]["_raw_phone"] = new_phone


def evening_vpn_approvals(w: World, shifts: dict) -> None:
    """Managers occasionally clear approval queues from home: purpose explained, timing not."""
    for d in working_days():
        for bid, _, _ in BRANCHES:
            if w.rng.random() > 0.18:
                continue
            mgr = staff(w, bid, "BRANCH_MANAGER")[0]
            emp = w.employees[mgr]
            start = at(d, 20, w.rng.randint(0, 50))
            sess = w.session("EMPLOYEE", mgr, emp["_laptop"], "VPN", start, 25, geo=emp["_city"])["id"]
            for i in range(w.rng.randint(1, 3)):
                cid = w.rng.choice([c for c in w.customers if w.customers[c]["branch_id"] == bid])
                acct = primary_account(w, cid)
                if acct["status"] != "ACTIVE":
                    continue
                t = start + timedelta(minutes=3 + 6 * i)
                w.work_item("TICKET", f"SR-{w.rng.randint(1000, 9999)}", t - timedelta(hours=5), cid,
                            acct["id"], mgr, bid, w.rng.choice(TICKET_TEXT["LIMIT_CHANGE"]))
                w.access(mgr, sess, "ACCT_VIEW", t, acct["id"], cid, ["profile"])
                old = acct["daily_limit_paise"]
                new = old * w.rng.choice([2, 3, 5])
                w.access(mgr, sess, "LIMIT_CHANGE", t + timedelta(minutes=2), acct["id"], cid, ["txn_limit"])
                w.state_change(acct["id"], "TXN_LIMIT", str(old), str(new), "EMPLOYEE", mgr,
                               "MAKER_CHECKER", t + timedelta(minutes=2), sess)
                w.customers[cid]["_big_payment"] = (t + timedelta(hours=w.rng.randint(10, 60)), new)


def new_accounts_in_window(w: World, shifts: dict) -> None:
    """Legitimate account openings: customer present (token + biometric eKYC), queue, approval."""
    for d in working_days():
        for bid, _, _ in BRANCHES:
            for _ in range(int(w.np_rng.poisson(0.9))):
                approvers = [e for e in staff(w, bid, "KYC_APPROVER") if (e, d) in shifts]
                openers = [e for e in staff(w, bid, "TELLER") if (e, d) in shifts]
                if not approvers or not openers:
                    continue
                t = at(d, w.rng.randint(10, 16), w.rng.randint(0, 59))
                seg = w.rng.choice(["SALARIED", "STUDENT", "HOMEMAKER", "SELF_EMPLOYED"])
                cust = new_customer(w, bid, seg, t)
                opener, approver = w.rng.choice(openers), w.rng.choice(approvers)
                w.work_item("TOKEN", f"TKN-{w.rng.randint(100, 999)}", t - timedelta(minutes=10),
                            cust["id"], None, opener, bid, "Counter token — account opening", 20)
                w.work_item("EKYC", f"EKYC-{w.rng.randint(100000, 999999)}", t, cust["id"], None,
                            opener, bid, "Aadhaar biometric eKYC — success", 2)
                acct = new_account(w, cust, "SAVINGS", t + timedelta(minutes=20), opener, approver,
                                   "BRANCH_BIOMETRIC", 0)
                w.work_item("QUEUE", w.seq("KQ", 5), t + timedelta(minutes=22), cust["id"],
                            acct["id"], approver, bid, "KYC review queue — new savings account")
                w.access(opener, None, "ACCT_OPEN", t + timedelta(minutes=20), acct["id"], cust["id"])
                w.access(approver, None, "KYC_APPROVE", t + timedelta(minutes=55), acct["id"],
                         cust["id"], ["kyc_documents"])
                w.txn("X-CASH", acct["id"], w.rng.randint(1, 20) * 1000 * RUPEE, "CASH",
                      "CASH_DEPOSIT", t + timedelta(minutes=58), "Initial deposit", branch_id=bid)
                w.customer_device[cust["id"]] = new_device(w, "ANDROID", t + timedelta(days=1))


# ── customer money behaviour ─────────────────────────────────────────────────


class CustomerSessions:
    """Groups a customer's digital transactions into sessions (per 6-hour block)."""

    def __init__(self, w: World):
        self.w = w
        self.cache: dict[tuple[str, date, int], str] = {}

    def get(self, cid: str, t: datetime, channel: str = "MOBILE") -> str:
        cust = self.w.customers[cid]
        pending = cust.get("_pending_new_device")
        if pending and t >= pending:
            self.w.customer_device[cid] = new_device(self.w, self.w.rng.choice(["ANDROID", "IOS"]), t)
            cust["_pending_new_device"] = None
        key = (cid, t.date(), t.hour // 6)
        if key not in self.cache:
            self.cache[key] = self.w.session("CUSTOMER", cid, self.w.customer_device.get(cid), channel,
                                             t - timedelta(minutes=2), 12, geo=cust["_city"])["id"]
        return self.cache[key]


def run_customers(w: World, pools: dict[str, list[str]]) -> None:
    sess = CustomerSessions(w)
    intents: list[tuple[datetime, int, object]] = []
    k = 0

    def plan(t: datetime, fn) -> None:
        nonlocal k
        k += 1
        heapq.heappush(intents, (t, k, fn))

    festival = (date(2026, 9, 10), date(2026, 9, 16))
    all_days = days()
    ends = {(d.year, d.month): last_working_day_of_month(d) for d in all_days}

    for cid, cust in list(w.customers.items()):
        accts = [a for a in w.accounts.values() if a["customer_id"] == cid]
        if not accts or accts[0]["status"] != "ACTIVE":
            continue
        a = accts[0]["id"]
        seg = cust["segment"]
        for d in all_days:
            fest = 2.3 if festival[0] <= d <= festival[1] else 1.0
            # income
            if seg == "SALARIED" and d == ends[(d.year, d.month)] and cust.get("_employer"):
                amt = cust.setdefault("_salary", w.rng.randint(22, 160) * 1000)
                plan(at(d, 10, w.rng.randint(0, 59)),
                     lambda a=a, amt=amt, e=cust["_employer"], d=d: w.txn(
                         e, a, amt * RUPEE, "NEFT", "SALARY", at(d, 10), f"SALARY {d:%b %Y}".upper()))
            if seg == "PENSIONER" and d.day == 1:
                amt = cust.setdefault("_pension", w.rng.randint(12, 55) * 1000)
                plan(at(d, 9, 5), lambda a=a, amt=amt, d=d: w.txn(
                    "X-TRSY", a, amt * RUPEE, "NEFT", "PENSION", at(d, 9, 5), f"PENSION {d:%b %Y}".upper()))
            if seg == "SME" and d.weekday() < 5 and w.rng.random() < 0.3:
                src = w.rng.choice(pools["business"])
                amt = w.rng.randint(50, 500) * 1000
                t = at(d, w.rng.randint(10, 17), w.rng.randint(0, 59))
                plan(t, lambda a=a, src=src, amt=amt, t=t: w.txn(src, a, amt * RUPEE, "NEFT",
                                                                  "CREDIT", t, "Client payment"))
            if seg in ("HOMEMAKER", "STUDENT") and w.rng.random() < 0.035:
                src = w.rng.choice(pools["person"])
                amt = w.rng.randint(2, 25) * 1000
                t = at(d, w.rng.randint(9, 21), w.rng.randint(0, 59))
                plan(t, lambda a=a, src=src, amt=amt, t=t: w.txn(src, a, amt * RUPEE, "UPI",
                                                                  "CREDIT", t, "Transfer from family"))
            if seg == "SELF_EMPLOYED" and w.rng.random() < 0.08:
                src = w.rng.choice(pools["business"] + pools["person"])
                amt = w.rng.randint(5, 90) * 1000
                t = at(d, w.rng.randint(9, 20), w.rng.randint(0, 59))
                plan(t, lambda a=a, src=src, amt=amt, t=t: w.txn(src, a, amt * RUPEE, "IMPS",
                                                                  "CREDIT", t, "Professional fees"))
            if seg == "SHOPKEEPER" and not is_bank_holiday(d):
                for _ in range(w.rng.randint(1, 4)):
                    t = at(d, w.rng.randint(8, 21), w.rng.randint(0, 59))
                    src = w.rng.choice(pools["person"])
                    amt = w.rng.randint(80, 2500)
                    plan(t, lambda a=a, src=src, amt=amt, t=t: w.txn(src, a, amt * RUPEE, "UPI",
                                                                      "UPI_CREDIT", t, "UPI collect"))
            # spending
            p_spend = {"SALARIED": 0.45, "PENSIONER": 0.12, "SHOPKEEPER": 0.25, "SME": 0.2,
                       "STUDENT": 0.35, "HOMEMAKER": 0.3, "SELF_EMPLOYED": 0.3,
                       "INSTITUTION": 0.0}[seg] * fest
            if w.rng.random() < p_spend:
                m = w.rng.choice(pools["merchant"])
                t = at(d, w.rng.randint(8, 22), w.rng.randint(0, 59))
                amt = max(40, int(w.np_rng.lognormal(6.4, 0.9)))
                plan(t, lambda a=a, m=m, amt=amt, t=t, cid=cid: w.txn(
                    a, m, amt * RUPEE, "UPI", "UPI_PAY", t, "UPI merchant", sess.get(cid, t)))
            if seg == "SALARIED" and cust.get("_landlord") and d.day == 5:
                rent = cust.setdefault("_rent", w.rng.randint(8, 35) * 1000)
                t = at(d, w.rng.randint(9, 21), w.rng.randint(0, 59))
                plan(t, lambda a=a, r=rent, ll=cust.get("_landlord"), t=t, cid=cid: w.txn(
                    a, ll, r * RUPEE, "IMPS", "TRANSFER", t, "Rent", sess.get(cid, t)))
            if w.rng.random() < 0.02 and seg != "SME":
                t = at(d, w.rng.randint(8, 22), w.rng.randint(0, 59))
                amt = w.rng.choice([2000, 3000, 5000, 10000])
                plan(t, lambda a=a, amt=amt, t=t: w.txn(a, "X-ATM", amt * RUPEE, "ATM",
                                                         "ATM_WITHDRAWAL", t, "ATM cash"))
            if w.rng.random() < 0.012:
                payees = sorted(w.payees[a])
                if payees:
                    cp = w.rng.choice(payees)
                    t = at(d, w.rng.randint(8, 22), w.rng.randint(0, 59))
                    amt = w.rng.randint(1, 30) * 1000
                    plan(t, lambda a=a, cp=cp, amt=amt, t=t, cid=cid: w.txn(
                        a, cp, amt * RUPEE, "IMPS", "TRANSFER", t, "Family transfer", sess.get(cid, t)))
            if seg == "SME" and d == ends[(d.year, d.month)]:
                crew = cust.setdefault("_crew", w.rng.sample(pools["person"], w.rng.randint(10, 42)))
                for i, emp in enumerate(crew):
                    t = at(d, 16, 0) + timedelta(minutes=i)
                    amt = w.rng.randint(12, 35) * 1000
                    plan(t, lambda a=a, e=emp, amt=amt, t=t, cid=cid: w.txn(
                        a, e, amt * RUPEE, "IMPS", "PAYROLL", t, "Staff salary", sess.get(cid, t)))
            if seg == "SHOPKEEPER" and d.weekday() == 1:
                sup = cust.setdefault("_supplier", w.rng.choice(pools["business"]))
                t = at(d, 12, w.rng.randint(0, 59))
                amt = w.rng.randint(15, 90) * 1000
                plan(t, lambda a=a, s=sup, amt=amt, t=t, cid=cid: w.txn(
                    a, s, amt * RUPEE, "IMPS", "TRANSFER", t, "Supplier payment", sess.get(cid, t)))
        # occasional new payee + first payment days later (legitimate)
        if w.rng.random() < 0.2:
            d = w.rng.choice(all_days[:-12])
            cp = w.rng.choice(pools["person"] + pools["business"])
            t = at(d, w.rng.randint(9, 21), w.rng.randint(0, 59))
            lag = timedelta(hours=w.rng.randint(1, 240))
            amt = w.rng.randint(2, 60) * 1000

            def add_and_pay(a=a, cp=cp, t=t, lag=lag, amt=amt, cid=cid):
                s = sess.get(cid, t)
                w.beneficiary(a, cp, w.accounts[cp]["holder_name"], t, s)
                plan(t + lag, lambda: w.txn(a, cp, amt * RUPEE, "IMPS", "TRANSFER", t + lag,
                                            "Payment", sess.get(cid, t + lag)))
            plan(t, add_and_pay)

    # big payments after legitimate limit increases (property / vehicle / fees)
    for cid, cust in w.customers.items():
        big = cust.get("_big_payment")
        if not big:
            continue
        t, limit_paise = big
        acct = primary_account(w, cid)
        builder = w.rng.choice(pools["builder"] + pools["business"])
        amt = int(min(limit_paise * w.rng.uniform(0.6, 0.99), w.balance[acct["id"]] * 0.9))

        def pay(a=acct["id"], b=builder, t=t, amt=amt, cid=cid):
            s = sess.get(cid, t - timedelta(minutes=20))
            w.beneficiary(a, b, w.accounts[b]["holder_name"], t - timedelta(minutes=20), s)
            w.txn(a, b, amt, "IMPS", "TRANSFER", t, "Booking amount", s)
        plan(t, pay)

    # execute in time order; callbacks may schedule further intents
    horizon = datetime(2026, 9, 22, 23, 59, tzinfo=IST)
    while intents:
        t, _, fn = heapq.heappop(intents)
        if t <= horizon:
            fn()
