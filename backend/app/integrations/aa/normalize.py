"""ReBIT DEPOSIT FI data → SUTRA's normalised statement rows, validated, with every rejection explained.

Input is the decrypted FI payload as an FIU receives it from its AA (Setu returns
`Payload[].data[].decryptedFI.account`). Field names follow the ReBIT Deposit schema: each Transaction
carries `type` (CREDIT | DEBIT), `mode` (CASH | ATM | CARD | UPI | FT | OTHERS), `amount`, `currentBalance`,
`transactionTimestamp`, `valueDate`, `txnId`, `narration` and `reference`, all required
(specifications.rebit.org.in, deposit schema). JSON renderings vary in case (`Account`/`account`,
`Transaction`/`transaction`), so both are accepted.

What is kept: the FIP, the masked account number (never a full one), and each transaction's fields.
What is not: holder name, mobile, email, PAN, date of birth and address from the Profile — an
investigation needs the money, not the identity data the bank already holds.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

TYPES = frozenset({"CREDIT", "DEBIT"})
MODES = frozenset({"CASH", "ATM", "CARD", "UPI", "FT", "OTHERS"})
MAX_NARRATION = 200
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_FULL_ACCOUNT = re.compile(r"\b\d{9,18}\b")


@dataclass(frozen=True)
class StatementRow:
    id: str
    fip_id: str
    masked_account: str
    txn_id: str
    txn_type: str
    mode: str
    amount_paise: int
    balance_paise: int | None
    occurred_at: datetime
    value_date: date | None
    narration: str
    reference: str
    content_sha256: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["occurred_at"] = self.occurred_at.isoformat()
        d["value_date"] = self.value_date.isoformat() if self.value_date else None
        return d


def _get(d: dict, *names):
    for n in names:
        if n in d:
            return d[n]
    return None


def _paise(x) -> int | None:
    if x is None or x == "":
        return None
    v = float(x)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("not a finite number")
    return round(v * 100)


def _clean(text: str | None) -> str:
    t = _CONTROL.sub(" ", str(text or "")).strip()
    t = _FULL_ACCOUNT.sub(lambda m: "X" * (len(m.group()) - 4) + m.group()[-4:], t)  # never keep a full account number
    return t[:MAX_NARRATION]


def _mask(acc: str | None) -> str:
    a = str(acc or "")
    return a if not re.search(r"\d{5,}", a.replace("X", "")) else "X" * max(len(a) - 4, 0) + a[-4:]


def accounts(payload) -> list[tuple[str, dict]]:
    """(fip_id, Account) pairs from a Setu-style session response, a bare Payload list or one Account."""
    if isinstance(payload, dict) and ("Payload" in payload or "payload" in payload):
        payload = _get(payload, "Payload", "payload")
    out = []
    if isinstance(payload, dict) and _get(payload, "account", "Account"):
        return [(payload.get("fipID", "UNKNOWN-FIP"), _get(payload, "account", "Account"))]
    for fip in payload or []:
        fip_id = _get(fip, "fipID", "fipId", "fip_id") or "UNKNOWN-FIP"
        for item in _get(fip, "data", "Data") or []:
            fi = _get(item, "decryptedFI", "decryptedFi") or item
            acct = _get(fi, "account", "Account")
            if acct:
                out.append((fip_id, acct))
    return out


def normalise(payload) -> tuple[list[StatementRow], list[dict], list[dict]]:
    """Rows, account summaries and rejections. A row that fails validation is rejected with its reason."""
    rows: list[StatementRow] = []
    rejected: list[dict] = []
    summaries: list[dict] = []
    for fip_id, acct in accounts(payload):
        masked = _mask(_get(acct, "maskedAccNumber", "maskedAccountNumber"))
        summary = _get(acct, "summary", "Summary") or {}
        summaries.append({"fip_id": fip_id, "masked_account": masked, "type": summary.get("type"),
                          "status": summary.get("status"), "current_balance": summary.get("currentBalance"),
                          "branch": summary.get("branch"), "opening_date": summary.get("openingDate")})
        txs = _get(acct, "transactions", "Transactions") or {}
        items = _get(txs, "transaction", "Transaction") or []
        if isinstance(items, dict):
            items = [items]
        for i, t in enumerate(items):
            try:
                rows.append(_row(fip_id, masked, t))
            except (ValueError, TypeError, KeyError) as e:
                rejected.append({"fip_id": fip_id, "index": i, "txn_id": str(t.get("txnId", ""))[:40] if isinstance(t, dict)
                                 else "", "reason": str(e)[:200]})
    return rows, summaries, rejected


def _row(fip_id: str, masked: str, t: dict) -> StatementRow:
    if not isinstance(t, dict):
        raise TypeError("transaction is not an object")
    txn_id = str(t.get("txnId") or "").strip()
    if not txn_id:
        raise ValueError("txnId missing")
    typ = str(t.get("type") or "").upper()
    if typ not in TYPES:
        raise ValueError(f"type {typ!r} is not CREDIT or DEBIT")
    mode = str(t.get("mode") or "").upper()
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is not a ReBIT transaction mode")
    amount = _paise(t.get("amount"))
    if amount is None or amount <= 0:
        raise ValueError("amount missing or not positive")
    ts = t.get("transactionTimestamp")
    when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("transactionTimestamp has no time zone")
    vd = t.get("valueDate")
    value_date = date.fromisoformat(str(vd)[:10]) if vd else None
    body = {"fip": fip_id, "acct": masked, "txnId": txn_id, "type": typ, "mode": mode, "amount": amount,
            "ts": when.isoformat(), "valueDate": str(value_date), "narration": _clean(t.get("narration")),
            "reference": _clean(t.get("reference"))}
    sha = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    rid = "AAT-" + hashlib.sha256(f"{fip_id}|{masked}|{txn_id}".encode()).hexdigest()[:16].upper()
    return StatementRow(rid, fip_id, masked, txn_id, typ, mode, amount, _paise(t.get("currentBalance")), when,
                        value_date, body["narration"], body["reference"], sha)
