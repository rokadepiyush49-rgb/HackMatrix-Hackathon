"""Kestrel Bank — the mock bank's own HTTP surface (demo mode only).

This is the *bank*, not SUTRA: its screens sign people in with bank sessions of their own, carried
in an `X-Bank-Token` header, and never see SUTRA's alerts. Everything they do is recorded into Loom
by app.loom.bank, where SUTRA's next detection run will find it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import _encode, decode
from app.loom import bank, bank_scenarios

router = APIRouter(prefix="/bank", tags=["bank (mock)"])


def _enabled() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _session(kind: str):
    def dep(x_bank_token: Annotated[str | None, Header()] = None) -> dict:
        _enabled()
        if not x_bank_token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to the bank first.")
        claims = decode(x_bank_token, "bank")
        if claims.get("kind") != kind:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This bank session is for a different portal.")
        return claims
    return dep


Staff = Annotated[dict, Depends(_session("staff"))]
Customer = Annotated[dict, Depends(_session("customer"))]
Db = Annotated[Session, Depends(get_db)]


def _do(db: Session, fn, *args):
    """Run one bank action in one transaction; bank refusals come back as 422 with the bank's own words."""
    try:
        out = fn(db.connection(), *args)
    except bank.BankError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    db.commit()
    return out


# ── the clock ───────────────────────────────────────────────────────────────


class ClockIn(BaseModel):
    at: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/clock")
def get_clock() -> dict:
    _enabled()
    return bank.clock()


@router.post("/clock")
def set_clock(body: ClockIn) -> dict:
    _enabled()
    return bank.set_clock(body.at)


class AdvanceIn(BaseModel):
    minutes: int = Field(15, ge=1, le=240)


@router.post("/clock/advance")
def advance_clock(body: AdvanceIn) -> dict:
    _enabled()
    return bank.advance(body.minutes)


@router.get("/activity")
def get_activity(db: Db) -> list[dict]:
    _enabled()
    return bank.activity(db.connection())


# ── staff console ───────────────────────────────────────────────────────────


class StaffLogin(BaseModel):
    employee_id: str = Field(..., max_length=16)
    channel: Literal["BRANCH", "VPN"] = "BRANCH"


@router.get("/staff/directory")
def staff_directory(db: Db) -> list[dict]:
    _enabled()
    return bank.staff_directory(db.connection())


@router.post("/staff/login")
def staff_login(body: StaffLogin, db: Db) -> dict:
    _enabled()
    out = _do(db, bank.staff_login, body.employee_id, body.channel)
    token = _encode(body.employee_id, "bank", 180, {"kind": "staff", "sid": out["session_id"], "channel": body.channel})
    return {**out, "token": token}


@router.get("/staff/me")
def staff_me(s: Staff, db: Db) -> dict:
    return {**bank.staff_overview(db.connection(), s["sub"]), "session_id": s["sid"], "channel": s["channel"]}


class GrantIn(BaseModel):
    mode: Literal["expired", "today"] = "expired"


@router.post("/staff/setup/override")
def setup_override(body: GrantIn, s: Staff, db: Db) -> dict:
    return _do(db, bank.grant_override, s["sub"], body.mode)


class RosterIn(BaseModel):
    start: str = Field("17:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field("22:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.post("/staff/setup/roster")
def setup_roster(body: RosterIn, s: Staff, db: Db) -> dict:
    return _do(db, bank.roster_camp, s["sub"], body.start, body.end)


@router.get("/staff/search")
def staff_search(q: str, s: Staff, db: Db) -> list[dict]:
    return bank.search(db.connection(), q)


class CustomerIn(BaseModel):
    customer_id: str = Field(..., max_length=16)


@router.post("/staff/customer")
def staff_open_customer(body: CustomerIn, s: Staff, db: Db) -> dict:
    return _do(db, bank.open_customer, s["sub"], s["sid"], body.customer_id)


class AccountIn(BaseModel):
    account_id: str = Field(..., max_length=16)


@router.post("/staff/account")
def staff_open_account(body: AccountIn, s: Staff, db: Db) -> dict:
    return _do(db, bank.open_account, s["sub"], s["sid"], body.account_id)


@router.get("/staff/account-view")
def staff_account_view(account_id: str, s: Staff, db: Db) -> dict:
    """Refresh an account already on screen. Not an access in its own right, so nothing is recorded."""
    return _do(db, bank.account_view, account_id)


class TicketIn(AccountIn):
    note: str = Field("Update registered mobile number — customer request", max_length=200)


@router.post("/staff/ticket")
def staff_ticket(body: TicketIn, s: Staff, db: Db) -> dict:
    return _do(db, bank.raise_ticket, s["sub"], body.account_id, body.note)


@router.post("/staff/ekyc")
def staff_ekyc(body: AccountIn, s: Staff, db: Db) -> dict:
    return _do(db, bank.capture_ekyc, s["sub"], body.account_id)


class MobileIn(AccountIn):
    new_mobile: str = Field(..., max_length=16)
    auth: Literal["OTP_OLD_NUMBER", "BIOMETRIC", "OVERRIDE"]


@router.post("/staff/mobile")
def staff_mobile(body: MobileIn, s: Staff, db: Db) -> list[dict]:
    return _do(db, bank.update_mobile, s["sub"], s["sid"], body.account_id, body.new_mobile, body.auth)


class LimitIn(AccountIn):
    limit: int
    use_override: bool = False


@router.post("/staff/limit")
def staff_limit(body: LimitIn, s: Staff, db: Db) -> list[dict]:
    return _do(db, bank.change_limit, s["sub"], s["sid"], body.account_id, body.limit, body.use_override)


# ── customer NetBanking ─────────────────────────────────────────────────────


@router.get("/customers")
def customers(db: Db, q: str = "") -> list[dict]:
    _enabled()
    return bank.customer_directory(db.connection(), q)


class CustomerLogin(BaseModel):
    customer_id: str = Field(..., max_length=16)
    new_device: bool = False
    city: str | None = Field(None, max_length=40, description="Where the sign-in comes from; the customer's own city if omitted")


@router.post("/customer/login")
def customer_login(body: CustomerLogin, db: Db) -> dict:
    _enabled()
    out = _do(db, bank.customer_login, body.customer_id, body.new_device, body.city)
    token = _encode(body.customer_id, "bank", 120, {"kind": "customer", "sid": out["session_id"], "device": out["device"]})
    return {**out, "token": token}


@router.get("/customer/me")
def customer_me(c: Customer, db: Db) -> dict:
    return {**bank.customer_overview(db.connection(), c["sub"]), "session_id": c["sid"], "device": c["device"]}


@router.post("/customer/password")
def customer_password(c: Customer, db: Db) -> dict:
    return _do(db, bank.reset_password, c["sub"], c["sid"])


@router.get("/customer/payee-directory")
def payee_directory(c: Customer, db: Db, q: str = "") -> list[dict]:
    return bank.payee_directory(db.connection(), q)


class PayeeIn(AccountIn):
    counterparty: str = Field(..., max_length=16)


@router.post("/customer/payees")
def customer_payee(body: PayeeIn, c: Customer, db: Db) -> dict:
    return _do(db, bank.add_payee, c["sub"], c["sid"], body.account_id, body.counterparty)


class TransferIn(AccountIn):
    to: str = Field(..., max_length=16)
    amount: int
    channel: Literal["IMPS", "NEFT", "UPI"] = "IMPS"


@router.post("/customer/transfer")
def customer_transfer(body: TransferIn, c: Customer, db: Db) -> dict:
    return _do(db, bank.transfer, c["sub"], c["sid"], body.account_id, body.to, body.amount, body.channel)


# ── plain REST API for scripted tests (MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY) ─────────────

HTTP_FOR = {"ACCOUNT_NOT_FOUND": 404, "TRANSACTION_NOT_FOUND": 404, "CUSTOMER_NOT_FOUND": 404, "NOT_FOUND": 404,
            "ACCOUNT_BLOCKED": 423, "SWITCH_FAILED": 502, "SCENARIO_ALREADY_RUN": 409, "BANK_DAY_OVER": 409}


def _api(db: Session, fn, *args):
    """One action, one transaction. Refusals come back as {status: FAILED, code, message} with a fitting HTTP status."""
    _enabled()
    try:
        out = fn(db.connection(), *args)
    except bank.BankError as e:
        db.rollback()
        return JSONResponse({"status": "FAILED", "code": e.code, "message": str(e), "environment": bank.LABEL},
                            status_code=HTTP_FOR.get(e.code, 422))
    db.commit()
    return out


@router.get("/accounts/{account_id}", response_model=None)
def api_account(account_id: str, db: Db):
    return _api(db, bank.account_json, account_id)


@router.get("/accounts/{account_id}/balance", response_model=None)
def api_balance(account_id: str, db: Db):
    def balance(c, a):
        acct = bank.account_json(c, a)
        return {"accountId": acct["accountId"], "balance": acct["balance"], "currency": "INR", "status": acct["status"],
                "asOf": bank.now().isoformat(), "environment": bank.LABEL}
    return _api(db, balance, account_id)


@router.get("/accounts/{account_id}/transactions", response_model=None)
def api_transactions(account_id: str, db: Db, limit: int = 20):
    return _api(db, bank.transactions_json, account_id, max(1, min(limit, 200)))


class PaymentIn(BaseModel):
    fromAccount: str = Field(..., max_length=16)
    toAccount: str = Field(..., max_length=16)
    amount: int = Field(..., ge=1, le=25_00_000, description="Rupees")
    channel: Literal["IMPS", "NEFT", "UPI", "RTGS"] = "IMPS"
    device: Literal["usual", "new"] = "usual"
    addPayee: bool = False
    simulateFailure: bool = False
    city: str | None = Field(None, max_length=40, description="Where the NetBanking sign-in comes from")


@router.post("/transactions", response_model=None)
def api_pay(body: PaymentIn, db: Db):
    """A customer-initiated payment from NetBanking: sign-in, optional payee registration, transfer."""
    return _api(db, bank.pay, body.fromAccount, body.toAccount, body.amount, body.channel, body.device == "new",
                body.addPayee, body.simulateFailure, body.city)


@router.get("/transactions/{txn_id}", response_model=None)
def api_transaction(txn_id: str, db: Db):
    return _api(db, bank.get_transaction, txn_id)


class CreditIn(BaseModel):
    fromAccount: str = Field(..., max_length=16, description="An account at another bank (X-…)")
    amount: int = Field(..., ge=1, le=25_00_000)
    channel: Literal["IMPS", "NEFT", "UPI", "RTGS"] = "IMPS"


@router.post("/accounts/{account_id}/credit", response_model=None)
def api_credit(account_id: str, body: CreditIn, db: Db):
    def credit(c, a):
        rec = bank.receive(c, a, body.fromAccount, body.amount, body.channel)
        return bank.get_transaction(c, rec["ref"])
    return _api(db, credit, account_id)


@router.post("/accounts/{account_id}/block", response_model=None)
def api_block(account_id: str, db: Db):
    return _api(db, lambda c, a: (bank.set_blocked(c, a, True), bank.account_json(c, a))[1], account_id)


@router.post("/accounts/{account_id}/unblock", response_model=None)
def api_unblock(account_id: str, db: Db):
    return _api(db, lambda c, a: (bank.set_blocked(c, a, False), bank.account_json(c, a))[1], account_id)


@router.get("/test/scenarios")
def api_scenarios() -> list[dict]:
    _enabled()
    return bank_scenarios.catalogue()


@router.post("/test/scenario/{key}", response_model=None)
def api_scenario(key: str, db: Db):
    return _api(db, lambda c, k: bank_scenarios.run(c, k)[0], key)


@router.post("/test/detect", response_model=None)
def api_detect(db: Db):
    """Ask SUTRA to run detection now over what the bank recorded (the scheduled job would, every 15 minutes)."""
    _enabled()
    from app.api import live
    from app.loom import feed

    if not feed.status(db)["bank"]["ingested"]:
        return JSONResponse({"status": "FAILED", "code": "NOTHING_RECORDED", "message": "The bank has recorded nothing yet."},
                            status_code=409)
    try:
        run = live._start("feed", "bank", "mock-bank", lambda r: live.play_feed(r, 0, True, "bank"))
    except HTTPException as e:
        return JSONResponse({"status": "FAILED", "code": "BUSY", "message": e.detail}, status_code=409)
    return {"runId": run.id, "status": "STARTED"}


@router.post("/test/reset", response_model=None)
def api_reset(db: Db):
    """Undo everything the bank recorded (balances, numbers, limits and blocks restored) and re-run detection."""
    _enabled()
    from app.api import live
    from app.loom import feed

    bank.set_clock("20:45")  # a fresh evening for the next test
    if not feed.status(db)["bank"]["total"]:
        return {"runId": None, "status": "NOTHING_TO_RESET"}
    try:
        run = live._start("reset", "bank", "mock-bank", lambda r: live.reset_feed(r, "bank"))
    except HTTPException as e:
        return JSONResponse({"status": "FAILED", "code": "BUSY", "message": e.detail}, status_code=409)
    return {"runId": run.id, "status": "STARTED"}


@router.get("/test/runs/{run_id}", response_model=None)
def api_run(run_id: str):
    _enabled()
    from app.api import live

    run = live._runs.get(run_id)
    if run is None:
        return JSONResponse({"status": "FAILED", "code": "NOT_FOUND", "message": f"No run {run_id}."}, status_code=404)
    stages = [d for e, d in run.log if e == "stage" and d["status"] == "done"]
    alerts = [d for e, d in run.log if e == "alert"]
    return {**run.summary(), "stagesDone": len(stages),
            "newAlerts": [{"id": a["id"], "priority": a["priority"], "typology": a["typology"], "claim": a["claim"]}
                          for a in alerts if a["new"]]}
