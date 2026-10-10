# Kestrel Bank — the mock bank for testing SUTRA

> **MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY.**
> Synthetic customers only. It never connects to a real bank, a payment network or UPI, never moves real money and
> never asks for real credentials. It exists only when `SUTRA_DEMO_MODE=true`; staging and production refuse to start
> in demo mode.

## Why it looks like this

SUTRA never calls a bank's API. It reads the records a bank's systems already keep and judges them:

| Bank system | Records SUTRA reads (Loom table) |
|---|---|
| VPN gateway / branch SSO | staff sign-ins (`session`) |
| Core-banking audit trail | which employee searched, viewed or changed which account (`access_event`) |
| Core banking | registered mobile, transaction limit, password and status changes (`state_change`) |
| IAM / HRMS | temporary grants such as a mobile-update override (`entitlement`), shifts (`roster`) |
| Service desk / eKYC | tickets and biometric eKYC (`work_item`) |
| NetBanking / device registry | customer sign-ins and new phones (`session`, `device`), payees (`beneficiary`) |
| Payment switch | transfers in and out (`txn`) |

So the mock bank does what a bank does, and every action writes those records into SUTRA as it happens, the way a
change-data-capture feed would. That is the whole integration contract; there is nothing to configure in SUTRA.

Some things in a generic bank checklist are deliberately missing:
- **Email addresses:** SUTRA has no use for them.
- **A "risk" field in responses:** SUTRA judges risk itself, so a bank-supplied label would mean nothing.
- **Failed-transaction records:** SUTRA only ever sees postings that happened. A refused payment returns an error
  code and leaves no record.

## Start it

```bash
make demo        # once: database, synthetic bank (seed 42), models, first detection
make api         # http://localhost:8000
make web         # http://localhost:3000
```

| What | Where |
|---|---|
| Bank screens and test dashboard | http://localhost:3000/bank |
| Staff core banking | http://localhost:3000/bank/staff |
| Customer NetBanking | http://localhost:3000/bank/netbanking |
| Bank REST API | `http://localhost:8000/api/v1/bank/…`, or `http://localhost:3000/api/bank/…` through the web app |
| SUTRA, judging what happened | http://localhost:3000/live, tab **Kestrel Bank** |

## Credentials and test data

- **Bank screens:** no passwords. Pick an employee or a customer (a test system on synthetic data). OTPs are simulated;
  the screen shows which number the OTP goes to.
- **SUTRA:** demo personas such as `ananya` (investigator) and `suresh` (vigilance). The password is
  `SUTRA_DEMO_PASSWORD` in `.env`.

| Account | Holder | What it is | Used by |
|---|---|---|---|
| A-3007 | Anjali Khan (C-83095) | salaried, ₹7.37 L, limit ₹1,00,000, payees X-1510, X-8716 | normal, failed |
| A-6406 | Milind Gupta (C-25655) | business current account, ₹1.02 Cr, limit ₹10,00,000 | large payment |
| A-5661 | Kavita Gupta (C-89006) | dormant pensioner account, ₹8.87 L | insider takeover |
| A-1028 | Rupali Nair (C-79086) | dormant pensioner account, ₹8.57 L | legitimate camp |
| A-8070 | Vishal Nair (C-35868) | salaried, ₹7.18 L, limit ₹1,00,000 | outsider takeover |
| A-5636 | Sandeep Fernandes (C-39423) | salaried, ₹7.14 L | rapid in-and-out |
| A-3341 | Priya Yadav (C-53773) | student, ₹1.77 L, payee X-3545 | insufficient funds |
| A-1832 | Vijay Kulkarni (C-92532) | student, ₹1.49 L, payee X-1209 | blocked account |
| A-7731, A-7768 | Arjun Sathe, Vishal Bapat | accounts of the 21 Sep mule ring | fraud payees |
| X-1003, X-1022 | Vaishali Shah, Yogesh Fernandes | accounts at other banks, never paid by A-3007 | new payees, credits |
| EMP-0258, EMP-0266 | Ops officers, Nashik Road | staff | insider, camp |

The data is deterministic (seed 42), so these IDs are the same on every `make demo`.

## REST API

All responses carry `"environment": "MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY"`.

| Method and path | What it does |
|---|---|
| `GET /accounts/{id}` | Account: number (masked), holder, balance, currency, status, limit, KYC status |
| `GET /accounts/{id}/balance` | Balance and status |
| `GET /accounts/{id}/transactions?limit=20` | Latest transactions, newest first |
| `POST /transactions` | A customer payment from NetBanking (see the body below) |
| `GET /transactions/{id}` | One transaction |
| `POST /accounts/{id}/credit` | Money arriving from another bank: `{"fromAccount": "X-1022", "amount": 25000}` |
| `POST /accounts/{id}/block` · `/unblock` | The branch blocks or unblocks the account (recorded as a status change) |
| `GET /test/scenarios` · `POST /test/scenario/{key}` | Predefined scenarios (below) |
| `POST /test/detect` · `GET /test/runs/{runId}` | Ask SUTRA to run detection now, and follow the run |
| `POST /test/reset` | Undo everything the bank recorded, restore accounts, re-detect, clock back to 20:45 |
| `GET /clock` · `POST /clock {"at": "21:20"}` · `POST /clock/advance {"minutes": 15}` | The bank's clock (within 22 Sep) |
| `GET /activity` | The rows the bank has recorded, newest first |

`POST /transactions` body:

```json
{ "fromAccount": "A-3007", "toAccount": "X-1510", "amount": 500, "channel": "UPI",
  "device": "usual", "addPayee": false, "simulateFailure": false, "city": null }
```

Success:

```json
{ "transactionId": "TX-0222415", "amount": 500.0, "currency": "INR", "status": "SUCCESS",
  "timestamp": "2026-09-22T23:20:50+05:30", "sender": "A-3007", "receiver": "X-1510",
  "channel": "UPI", "type": "TRANSFER", "narration": "UPI transfer",
  "environment": "MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY" }
```

Refusal:

```json
{ "status": "FAILED", "code": "INSUFFICIENT_FUNDS", "message": "Insufficient balance: ₹1,77,439 available.",
  "environment": "MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY" }
```

| Code | HTTP | When |
|---|---|---|
| `ACCOUNT_NOT_FOUND` | 404 | The account does not exist |
| `ACCOUNT_BLOCKED` | 423 | The sending or receiving account is blocked |
| `INSUFFICIENT_FUNDS` | 422 | Amount above the balance |
| `LIMIT_EXCEEDED` | 422 | Amount above the account's transaction limit |
| `PAYEE_NOT_REGISTERED` | 422 | The receiver is not a saved payee (send `"addPayee": true`) |
| `SWITCH_FAILED` | 502 | `"simulateFailure": true`: the receiving bank timed out. Nothing is debited or recorded. |
| `NOT_PERMITTED` | 422 | A staff action the employee's permissions don't allow |
| `INVALID_REQUEST` | 422 | Bad number, amount out of range, … |
| `SCENARIO_ALREADY_RUN` | 409 | Reset before running the same scenario again |
| `BANK_DAY_OVER` | 409 | The bank clock passed 23:59 on 22 Sep: set it back |

Examples:

```bash
B=http://localhost:8000/api/v1/bank
curl -s $B/accounts/A-3007
curl -s -X POST $B/transactions -H 'Content-Type: application/json' \
  -d '{"fromAccount":"A-3007","toAccount":"X-1510","amount":500,"channel":"UPI"}'
curl -s -X POST $B/test/scenario/insider
curl -s -X POST $B/test/detect          # returns {"runId": "LIVE-…"}
curl -s $B/test/runs/LIVE-…             # verdict and new alerts when finished
curl -s -X POST $B/test/reset
```

## Scenarios

| Key | What the bank does | Bank answer | What SUTRA should conclude |
|---|---|---|---|
| `normal` | ₹500 UPI to an existing payee from the usual phone | SUCCESS | No alert |
| `large` | ₹5,00,000 IMPS from a business account to an existing supplier | SUCCESS | No alert: size alone is not a reason |
| `insider` | Officer on VPN at 21:20 uses an override nobody revoked to change a dormant account's mobile and limit; an accomplice on a new phone adds two mule payees and sends ₹4,00,000 to each | SUCCESS | **P1 insider takeover**; Alibi: unexplained |
| `camp` | Rostered camp, ticket, biometric eKYC, mobile changed by biometric; no money | SUCCESS | No alert; Alibi: explained |
| `outsider` | New phone from Kolkata at 23:02, password reset, two new payees, ₹98,500 + ₹97,000 | SUCCESS | **Queued external account takeover** (P1 in testing) |
| `rapid` | Three ₹40,000 credits, then ₹1,14,000 out to a new payee within minutes | SUCCESS | Pass-through signal (G2), no case on its own |
| `failed` | ₹2,000 IMPS times out at the receiving bank | FAILED · SWITCH_FAILED | Nothing recorded, nothing to judge |
| `insufficient` | ₹2,00,000 from an account holding ₹1.77 L | FAILED · INSUFFICIENT_FUNDS | Nothing recorded |
| `blocked` | Branch blocks the account, then a ₹1,000 payment | FAILED · ACCOUNT_BLOCKED | Only the block is recorded; no alert |
| `invalid` | Payment to A-0000 | FAILED · ACCOUNT_NOT_FOUND | Nothing recorded |

The dashboard at `/bank` has a button for each, plus **Run SUTRA detection** and **Reset test data**.

## Check the integration in one command

```bash
make bank-check
```

This runs all ten scenarios in the bank, then SUTRA's real detection once (about 25 s). It compares each outcome with
the table above, prints ✓/✗ per scenario, undoes everything and exits non-zero on any mismatch.

Last run:

```
✓ Normal payment                       no queued alert
✓ Large payment                        no queued alert
✓ Insider takeover (fraud)             P1 INSIDER_ATO (AL-0922-003); Alibi ['UNEXPLAINED']
✓ Legitimate camp update               no queued alert; Alibi ['EXPLAINED']
✓ Account takeover by an outsider      P1 EXTERNAL_ATO (AL-0922-004)
✓ Rapid in-and-out transactions        no queued alert; signals G2
✓ Failed transaction                   bank said SWITCH_FAILED; SUTRA alerts: 0
✓ Insufficient balance                 bank said INSUFFICIENT_FUNDS; SUTRA alerts: 0
✓ Blocked account                      bank said ACCOUNT_BLOCKED; SUTRA alerts: 0
✓ Invalid account                      bank said ACCOUNT_NOT_FOUND; SUTRA alerts: 0
✓ 10/10 scenarios behaved as expected
```

## Test cases to run by hand

1. `GET /accounts/A-3007`: masked number `XXXX3007`, INR, ACTIVE, KYC VERIFIED.
2. `GET /accounts/A-0000`: 404 `ACCOUNT_NOT_FOUND`.
3. Pay ₹500 from A-3007 to X-1510 by UPI: SUCCESS; the balance drops by ₹500; the row appears in SUTRA → Live Ops →
   Kestrel Bank within seconds.
4. Pay ₹500 from A-3007 to X-1003: `PAYEE_NOT_REGISTERED`. Repeat with `"addPayee": true`: SUCCESS.
5. Pay ₹1,50,000 from A-3007: `LIMIT_EXCEEDED` (limit ₹1,00,000).
6. Pay ₹2,00,000 from A-3341: `INSUFFICIENT_FUNDS`; `/activity` gains no rows.
7. Pay with `"simulateFailure": true`: HTTP 502 `SWITCH_FAILED`; the balance is unchanged.
8. Block A-1832, then pay from it: 423 `ACCOUNT_BLOCKED`. Unblock and pay again: SUCCESS.
9. Run `insider`, then **Run SUTRA detection**: a new **P1 insider takeover**. In Live Ops, the chain starts at the
   override granted 16 Sep (never revoked), and all four staff accesses are unexplained.
10. Reset, run `camp`, detect: **no alert**; Alibi shows ticket, customer contact and roster.
11. Run `normal` and `large` together, detect: **no alert** for either. A big payment by the real customer is not
    suspicious on its own.
12. Run `outsider`, detect: a **queued external account-takeover** alert with no employee involved.
13. Run `rapid`, detect: a **G2 rapid pass-through** signal on A-5636 and no case.
14. Do the insider takeover by hand in the bank screens (see `/bank` for the steps), detect: P1 with the bank's
    records highlighted in SUTRA's input panel.
15. `POST /test/reset`: `/activity` is empty, A-1832 is ACTIVE again, balances are back, and SUTRA's 14 scenario
    checks still pass.

## Where it lives

| Piece | File |
|---|---|
| Bank actions and records | `backend/app/loom/bank.py` |
| Scenarios and the integration check | `backend/app/loom/bank_scenarios.py`, `python -m app.cli bank-check` |
| HTTP API | `backend/app/api/bank.py` |
| Screens and dashboard | `frontend/app/(bank)/bank/*`, `frontend/components/bank/*` |
| Tests | `backend/tests/test_bank.py` |
