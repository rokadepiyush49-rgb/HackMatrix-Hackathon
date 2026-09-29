"""The simulated world: table rows, ID allocation, balances and ground-truth labels.

Rows are plain dicts whose keys match the Loom table columns. Raw PII (phone numbers,
KYC numbers) is kept in `_raw` keys; the loader tokenises it before anything reaches
the database.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from kestrel_sim.clock import IST


@dataclass
class World:
    seed: int
    mode: str  # "demo" (canonical story, fixed IDs) | "train" (randomised instances)
    rng: random.Random = field(init=False)
    np_rng: np.random.Generator = field(init=False)
    tables: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    labels: list[dict] = field(default_factory=list)
    balance: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _used: set[str] = field(default_factory=set)
    _seq: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # convenience indexes (filled by the baseline generator)
    employees: dict[str, dict] = field(default_factory=dict)
    customers: dict[str, dict] = field(default_factory=dict)
    accounts: dict[str, dict] = field(default_factory=dict)
    devices: dict[str, dict] = field(default_factory=dict)
    payees: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    customer_device: dict[str, str] = field(default_factory=dict)
    reserved_for_scenarios: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.np_rng = np.random.default_rng(self.seed)

    # ── IDs ──────────────────────────────────────────────────────────────────
    def reserve(self, *ids: str) -> None:
        self._used.update(ids)

    def rid(self, prefix: str, digits: int = 4) -> str:
        lo, hi = 10 ** (digits - 1), 10**digits - 1
        for _ in range(10_000):
            candidate = f"{prefix}-{self.rng.randint(lo, hi)}"
            if candidate not in self._used:
                self._used.add(candidate)
                return candidate
        raise RuntimeError(f"ID space exhausted for {prefix}")

    def seq(self, prefix: str, width: int = 6) -> str:
        self._seq[prefix] += 1
        return f"{prefix}-{self._seq[prefix]:0{width}d}"

    # ── generic row adders ───────────────────────────────────────────────────
    def add(self, table: str, **row) -> dict:
        self.tables[table].append(row)
        return row

    def ingest_lag(self) -> timedelta:
        return timedelta(seconds=self.rng.randint(4, 90))

    # ── event helpers ────────────────────────────────────────────────────────
    def session(self, actor_type: str, actor_id: str, device_id: str | None, channel: str,
                start: datetime, minutes: int, geo: str = "Pune", ip: str | None = None,
                sid: str | None = None) -> dict:
        sid = sid or self.seq("S", 6)
        return self.add("session", id=sid, actor_type=actor_type, actor_id=actor_id,
                        device_id=device_id, ip=ip or self.ip(), geo_city=geo, channel=channel,
                        started_at=start, ended_at=start + timedelta(minutes=minutes))

    def access(self, employee_id: str, session_id: str | None, action: str, t: datetime,
               account_id: str | None = None, customer_id: str | None = None,
               fields: list[str] | None = None, override: bool = False,
               aid: str | None = None) -> dict:
        return self.add("access_event", id=aid or self.seq("AE", 7), session_id=session_id,
                        employee_id=employee_id, action=action, account_id=account_id,
                        customer_id=customer_id, fields=fields or [], override_used=override,
                        occurred_at=t, ingested_at=t + self.ingest_lag())

    def state_change(self, account_id: str, fld: str, old, new, actor_type: str, actor_id: str,
                     auth: str, t: datetime, session_id: str | None = None,
                     scid: str | None = None) -> dict:
        row = self.add("state_change", id=scid or self.seq("SC", 6), account_id=account_id,
                       field=fld, old_value=old, new_value=new, actor_type=actor_type,
                       actor_id=actor_id, auth_method=auth, session_id=session_id,
                       occurred_at=t, ingested_at=t + self.ingest_lag())
        acct = self.accounts.get(account_id)
        if acct is not None:
            if fld == "REGISTERED_MOBILE":
                acct["_raw_mobile"] = new
            elif fld == "TXN_LIMIT":
                acct["daily_limit_paise"] = int(new)
        return row

    def work_item(self, kind: str, ref: str, t: datetime, customer_id: str | None,
                  account_id: str | None, employee_id: str | None, branch_id: str | None,
                  text: str, minutes_open: int = 30) -> dict:
        return self.add("work_item", id=self.seq("WI", 6), kind=kind, ref=ref,
                        customer_id=customer_id, account_id=account_id, employee_id=employee_id,
                        branch_id=branch_id, text=text, created_at=t,
                        closed_at=t + timedelta(minutes=minutes_open))

    def beneficiary(self, account_id: str, cp: str, name: str, t: datetime,
                    session_id: str | None = None) -> dict:
        self.payees[account_id].add(cp)
        return self.add("beneficiary", id=self.seq("BN", 6), account_id=account_id,
                        counterparty_account=cp, counterparty_name=name, session_id=session_id,
                        added_at=t)

    def txn(self, frm: str, to: str, amount_paise: int, channel: str, kind: str, t: datetime,
            narration: str | None = None, session_id: str | None = None,
            branch_id: str | None = None, force: bool = False, tid: str | None = None) -> dict | None:
        """Record a transfer. Internal debits need funds unless `force` (scenario injections)."""
        amount_paise = int(amount_paise)
        if amount_paise <= 0:
            return None
        src = self.accounts.get(frm)
        internal = src is not None and src["kind"] != "EXTERNAL"
        if internal and not force and self.balance[frm] < amount_paise:
            return None
        self.balance[frm] -= amount_paise
        self.balance[to] += amount_paise
        return self.add("txn", id=tid or self.seq("TX", 7), from_account=frm, to_account=to,
                        amount_paise=amount_paise, channel=channel, kind=kind, narration=narration,
                        branch_id=branch_id, session_id=session_id, occurred_at=t,
                        ingested_at=t + self.ingest_lag())

    # ── misc ─────────────────────────────────────────────────────────────────
    def ip(self) -> str:
        return f"49.36.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}"

    def phone(self) -> str:
        return f"+91{self.rng.choice('6789')}{self.rng.randint(100_000_000, 999_999_999)}"

    def label(self, **row) -> None:
        self.labels.append(row)

    def now_ist(self, d, hh, mm=0, ss=0) -> datetime:
        return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=IST)
