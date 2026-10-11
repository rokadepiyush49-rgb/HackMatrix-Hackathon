"""Account Aggregator providers — where consented statements come from.

  SyntheticAAProvider   DATA SOURCE: SYNTHETIC_DEMO. A fictional FIP ("Deccan Synthetic Bank") that answers
                        offline, only in demo mode. Its statements are generated, never real: monthly credits,
                        everyday debits and, where the customer made cash deposits at Kestrel, cash withdrawals
                        at the other bank shortly before them. Consent approval is an explicit demo step that
                        stands in for the customer approving in their AA app.
  SetuSandboxProvider   DATA SOURCE: SANDBOX. Setu's FIU APIs (POST /consents → customer approves at the
                        returned URL → POST /sessions → GET /sessions/:id). Setu's sandbox serves mock FIP data.
                        Needs credentials from Setu's Bridge; not exercised against Setu from this repository
                        (no credentials), so it is tested against recorded response shapes only.

Neither provider can reach real customer data: that needs a regulated FIU certified by Sahamati.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.council.llm import Transport, urllib_transport


class AAError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class AAProvider(Protocol):
    name: str
    data_source: str

    def create_consent(self, customer_ref: str, date_from: date, date_to: date, purpose: str) -> dict: ...

    def consent_status(self, consent_id: str) -> str: ...

    def fetch(self, consent_id: str, date_from: date, date_to: date) -> dict: ...


# ── synthetic (demo) ────────────────────────────────────────────────────────


class SyntheticAAProvider:
    name = "synthetic"
    data_source = "SYNTHETIC_DEMO"
    FIP = "SYN-FIP-DECCAN"

    def __init__(self, conn=None):
        self.conn = conn  # reads the customer's Kestrel activity so the other bank's statement is consistent

    def create_consent(self, customer_ref: str, date_from: date, date_to: date, purpose: str) -> dict:
        return {"id": f"SYN-{uuid.uuid4().hex[:12].upper()}", "status": "PENDING", "url": None,
                "note": "Synthetic AA: approve the consent from SUTRA to stand in for the customer's AA app."}

    def consent_status(self, consent_id: str) -> str:
        raise AAError("unsupported", "the synthetic provider's consent state lives in SUTRA's aa_consent table")

    def fetch(self, consent_id: str, date_from: date, date_to: date, customer_id: str | None = None) -> dict:
        if not customer_id:
            raise AAError("bad_request", "customer_id required")
        rng = random.Random(int(hashlib.sha256(customer_id.encode()).hexdigest()[:12], 16))
        masked = "XXXXXXXX" + f"{rng.randint(0, 9999):04d}"
        start = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
        end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, tzinfo=UTC)
        txs: list[dict] = []
        bal = rng.randint(80, 600) * 1000.0

        def add(t: datetime, typ: str, mode: str, amount: float, narration: str) -> None:
            nonlocal bal
            if not start <= t <= end:
                return
            bal += amount if typ == "CREDIT" else -amount
            n = len(txs) + 1
            tid = hashlib.sha256(f"{customer_id}|{t.isoformat()}|{typ}|{amount:.2f}".encode()).hexdigest()[:12].upper()
            txs.append({"txnId": f"SYN{tid}", "type": typ, "mode": mode,
                        "amount": round(amount, 2), "currentBalance": f"{bal:.2f}",
                        "transactionTimestamp": t.isoformat(), "valueDate": t.date().isoformat(),
                        "narration": narration, "reference": f"REF{n:06d}"})

        salary = rng.randint(25, 140) * 1000.0
        employer = rng.choice(["DECCAN TEXTILES PAYROLL", "PUNE AUTO PARTS SALARY", "SAHYADRI FOODS PAYROLL"])
        d = date(start.year, start.month, 1)
        while d <= date_to:
            add(datetime(d.year, d.month, 1, 4, 30, tzinfo=UTC), "CREDIT", "FT", salary, f"NEFT {employer}")
            for k in range(rng.randint(4, 9)):
                day = min(28, 2 + k * 3 + rng.randint(0, 2))
                add(datetime(d.year, d.month, day, rng.randint(3, 15), rng.randint(0, 59), tzinfo=UTC), "DEBIT",
                    rng.choice(["UPI", "UPI", "CARD"]), round(rng.uniform(150, 4500), 2),
                    rng.choice(["UPI/GROCERY", "UPI/FUEL", "CARD/PHARMACY", "UPI/ELECTRICITY BILL", "UPI/MOBILE RECHARGE"]))
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        for t, amount in self._kestrel_cash_deposits(customer_id, start, end):
            # the cash that was deposited at Kestrel left this account shortly before, in one or two draws
            parts = [amount] if amount < 30_000 else [round(amount * 0.6, -2), amount - round(amount * 0.6, -2)]
            for j, a in enumerate(parts):
                add(t - timedelta(hours=3, minutes=10 * (j + 1)), "DEBIT", "CASH" if a >= 20_000 else "ATM", a,
                    "CASH WDL SELF" if a >= 20_000 else "ATM WDL")
        txs.sort(key=lambda x: x["transactionTimestamp"])
        return {"id": f"SES-{consent_id}", "consentId": consent_id, "status": "COMPLETED", "format": "json",
                "DataRange": {"from": start.isoformat(), "to": end.isoformat()},
                "Payload": [{"fipID": self.FIP, "data": [{"maskedAccNumber": masked, "linkRefNumber": f"LNK-{masked[-4:]}",
                            "decryptedFI": {"account": {
                                "linkedAccRef": f"LNK-{masked[-4:]}", "maskedAccNumber": masked, "type": "deposit",
                                "version": "1.1",
                                "summary": {"currentBalance": f"{bal:.2f}", "currency": "INR", "type": "SAVINGS",
                                            "status": "ACTIVE", "branch": "Deccan Synthetic Bank, Pune (fictional)",
                                            "balanceDateTime": end.isoformat(), "ifscCode": "SYNT0000001",
                                            "micrCode": "000000000", "openingDate": "2019-04-01", "facility": "OD",
                                            "currentODLimit": "0", "drawingLimit": "0"},
                                "transactions": {"startDate": date_from.isoformat(), "endDate": date_to.isoformat(),
                                                 "transaction": txs}}}}]}]}

    def _kestrel_cash_deposits(self, customer_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        if self.conn is None:
            return []
        from sqlalchemy import text

        rows = self.conn.execute(text("""
            SELECT t.occurred_at, t.amount_paise FROM txn t JOIN account a ON a.id = t.to_account
            WHERE a.customer_id = :c AND t.kind = 'CASH_DEPOSIT' AND t.occurred_at BETWEEN :s AND :e
            ORDER BY t.occurred_at"""), {"c": customer_id, "s": start, "e": end}).all()
        return [(r.occurred_at, r.amount_paise / 100) for r in rows]


# ── Setu FIU sandbox ────────────────────────────────────────────────────────


class SetuSandboxProvider:
    """Setu's FIU API. Header names follow Setu's v2 API conventions (x-client-id, x-client-secret,
    x-product-instance-id); confirm them against the Postman collection Setu issues with sandbox access."""

    name = "setu"
    data_source = "SANDBOX"

    def __init__(self, base_url: str, client_id: str, client_secret: str, product_instance_id: str,
                 transport: Transport | None = None, timeout_s: float = 20.0):
        if not (base_url and client_id and client_secret and product_instance_id):
            raise AAError("config", "Setu sandbox credentials are not configured")
        if not base_url.startswith("https://"):
            raise AAError("config", "Setu base URL must be https")
        self.base_url = base_url.rstrip("/")
        self._headers = {"x-client-id": client_id, "x-client-secret": client_secret,
                         "x-product-instance-id": product_instance_id, "Content-Type": "application/json"}
        self._transport = transport or urllib_transport
        self.timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"SetuSandboxProvider(base_url={self.base_url!r})"

    def _call(self, path: str, body: dict | None) -> dict:
        try:
            status, _h, raw = self._transport(f"{self.base_url}{path}", json.dumps(body).encode() if body is not None
                                              else None, self._headers, self.timeout_s)
        except (TimeoutError, OSError) as e:
            raise AAError("network", f"Setu unreachable ({type(e).__name__})") from None
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise AAError("malformed", f"unreadable Setu response (HTTP {status})") from None
        if status in (401, 403):
            raise AAError("auth", "Setu refused the credentials")
        if status >= 400:
            raise AAError("provider", f"Setu HTTP {status} {data.get('errorCode', '')}: {str(data.get('errorMsg', ''))[:160]}")
        return data

    def create_consent(self, customer_ref: str, date_from: date, date_to: date, purpose: str,
                       redirect_url: str = "http://localhost:3000/aa/return", purpose_code: str = "105") -> dict:
        """`purpose_code` is the ReBIT consent purpose; 105 is understood to be "explicit one-time consent for
        accessing data from the accounts" — confirm it against ReBIT's purpose list before onboarding."""
        now = datetime.now(UTC)
        body = {"Detail": {"consentStart": now.isoformat(), "consentExpiry": (now + timedelta(days=30)).isoformat(),
                           "Customer": {"id": customer_ref},
                           "FIDataRange": {"from": f"{date_from.isoformat()}T00:00:00Z", "to": f"{date_to.isoformat()}T23:59:59Z"},
                           "consentMode": "VIEW", "consentTypes": ["TRANSACTIONS", "PROFILE", "SUMMARY"],
                           "fetchType": "ONETIME", "Frequency": {"value": 1, "unit": "MONTH"},
                           "DataLife": {"value": 1, "unit": "MONTH"}, "DataConsumer": {"id": "SUTRA-FIU"},
                           "Purpose": {"Category": {"type": "string"}, "code": purpose_code, "text": purpose[:120],
                                       "refUri": f"https://api.rebit.org.in/aa/purpose/{purpose_code}.xml"},
                           "fiTypes": ["DEPOSIT"]},
                "context": [], "redirectUrl": redirect_url}
        data = self._call("/consents", body)
        return {"id": data.get("id"), "status": data.get("status", "PENDING"), "url": data.get("url")}

    def consent_status(self, consent_id: str) -> str:
        return str(self._call(f"/consents/{consent_id}", None).get("status", "UNKNOWN"))

    def fetch(self, consent_id: str, date_from: date, date_to: date, customer_id: str | None = None) -> dict:
        session = self._call("/sessions", {"consentId": consent_id, "format": "json",
                                           "DataRange": {"from": f"{date_from.isoformat()}T00:00:00Z",
                                                         "to": f"{date_to.isoformat()}T23:59:59Z"}})
        return self._call(f"/sessions/{session['id']}", None)


def provider(conn=None) -> AAProvider:
    from app.core.config import get_settings

    s = get_settings()
    if s.aa_provider == "setu":
        return SetuSandboxProvider(s.aa_setu_base_url, s.aa_setu_client_id, s.aa_setu_client_secret,
                                   s.aa_setu_product_instance_id)
    return SyntheticAAProvider(conn)
