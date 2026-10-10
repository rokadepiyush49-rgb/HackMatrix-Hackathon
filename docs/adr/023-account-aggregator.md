# 023 — Account Aggregator as a consented evidence source, demoed on a labelled synthetic FIP

**Context.** The team wanted real bank data from India's Account Aggregator (AA) network for the demo.
Live AA data reaches only a Financial Information User regulated by RBI, SEBI, IRDAI or PFRDA, certified
by a Sahamati-empanelled certifier, and listed in the live Central Registry (sahamati.org.in; Setu's
go-live guide). Sandboxes such as Setu's issue credentials quickly, but serve mock FIP data. A
teammate's own statements would contain no fraud, so they could not show detection working, and they
would break the project's all-synthetic privacy position.

**Decision.**
- `app.integrations.aa` implements the whole consumer side:
  - consent request → customer approval → fetch;
  - normalisation of ReBIT DEPOSIT data (field names and enums checked against the ReBIT deposit schema);
  - validation in which every rejected row is listed with its reason;
  - identity data stripped (only a masked account number is kept);
  - idempotent storage with NEW, DUPLICATE and CONFLICT outcomes;
  - revocation that deletes fetched rows, and a data-life expiry;
  - every step in the audit chain.
- **Providers:**
  - **Synthetic** (default; demo mode only; data source `SYNTHETIC_DEMO`): a fictional FIP whose
    statements are generated. Where the customer made cash deposits at Kestrel, the statement shows
    matching cash withdrawals shortly before.
  - **Setu sandbox** (`SANDBOX`): `POST /consents`, `GET /consents/:id`, `POST /sessions`,
    `GET /sessions/:id`. Tested against recorded response shapes only.
- **Where it plugs in:** consented statements answer the Council's "source-of-funds" record, which used
  to be "not ingested". They become evidence items labelled with their data source, so agents can cite
  them and the verifier can check them. They do **not** feed M1–M7, which were fitted on the bank's own
  records.

**Consequences.** Validation: `backend/tests/test_account_aggregator.py` (14 tests), plus an end-to-end
run in the UI on 11 Oct 2026 (consent, approve as the customer, fetch: 44 rows; logged as `aa.*` audit
entries).

**Blocked:** live data (needs a regulated, certified FIU) and a sandbox run against Setu (needs Bridge
credentials). Setu's auth header names and the ReBIT consent purpose code (default 105) must be checked
against Setu's Postman collection and ReBIT's purpose list at onboarding.
