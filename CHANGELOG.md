# Changelog

All notable changes are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Live Ops** (`/live`): the end-to-end demo. A held-back evening of 247 raw source rows streams
  into Loom (CDC-style, effects applied), the production pipeline runs with real stage timings over
  SSE, and the new P1, Alibi verdicts and ground-truth scoring appear as they are computed. Exact
  reset. CLI: `make live-play`, `make live-reset` (ADR 016).
- **Your input** on Live Ops: a console where a person acts as a member of staff. Choices are turned into the source rows the bank's systems would record (`app.loom.compose`), ingested, detected and judged — a verdict with its reason, the signals raised and Alibi's findings — and can be undone on their own.
- **Kestrel Bank** (`/bank`): a working mock bank to test SUTRA by hand — a staff core-banking console and customer NetBanking with their own sessions, enforcing permissions, balances, transaction limits and payees. Every action is recorded into Loom as it happens (`app.loom.bank`); Live Ops → Kestrel Bank runs detection on demand and undoes the bank's activity exactly.
- Mock bank REST API (accounts, balance, transactions, payments, credits, block/unblock) with error codes, ten predefined test scenarios with a one-click dashboard, and `make bank-check`, which runs them all through SUTRA and verifies each outcome (`docs/mock-bank`).
- **Voice**: the Investigation Council speaks, one voice per agent, advancing as each speaker
  finishes; Live Ops announces new alerts. Browser speech synthesis, offline, Indian-English voices
  preferred.
- On-site demo script with timings, talking points and fallbacks (`docs/demo/DEMO_SCRIPT.md`).
- Production platform: multi-stage non-root images (distroless web), Helm chart with Argo Rollouts
  canary, Argo CD GitOps, External Secrets, default-deny NetworkPolicies, Kyverno signature verification.
- AWS infrastructure in Terraform (ap-south-1, DR in ap-south-2): VPC, EKS + Karpenter (Graviton),
  RDS PostgreSQL 17 Multi-AZ, ElastiCache Valkey, S3 Object Lock evidence vault, KMS, WAF, GitHub OIDC.
- CI/CD: lint/test/build, Helm + Terraform validation, Checkov, Trivy, CodeQL, gitleaks, Scorecard;
  release pipeline with multi-arch builds, SBOM, SLSA provenance and cosign keyless signing.
- Observability: JSON logs with request IDs, OpenTelemetry traces (API + BFF), liveness/readiness split.
- Evidence packs stored through a storage layer (local / S3 Object Lock); tampering is detected on verify.
- Configuration guard: staging/prod refuse default secrets, demo personas and non-WORM evidence storage.
- Every investigator screen: Signal Desk, Case Desk, Chain Explorer, Money Trail, Entity dossiers,
  Alibi Ledger, Risk Network, Mule Factory, Timeline Replay, Investigation Council, Evidence packs,
  Control Lab, Twin Scenario Lab, Governance.

### Fixed
- Detection re-runs no longer wipe cases: `persist` is one transaction, chains keep their IDs by
  `(kind, root_ref)`, human triage state is kept, and a chain with a case is never deleted.
- G1 no longer reports "cycles" where more money returns than left (retention bounded to 70–110%).
- Needle no longer attributes a later night's transfers to an earlier chain (12 h layering window).
- Payout links state each amount when they differ ("₹4.85 L + ₹4.70 L + ₹4.60 L", not "3 × ₹4.85 L").
- Control friction measurement is 18× faster with identical results (indexed lookups).

### Changed
- Claude integration moved to **Claude Opus 5.5** with explicit effort, a reused client, typed error handling,
  token-usage logging (never content), and a prompt-cache breakpoint on the case evidence.
- New `bedrock` provider (Claude in Amazon Bedrock via IAM / Pod Identity); IAM uses `bedrock-mantle:CreateInference`.
- LLM narration off by default in production (ADR 015, India residency); on in staging.
- Training world now includes legitimate look-alikes and colluding approvers; M6 no longer reduces to a single rule.
- Model metadata records artifact SHA-256 and library versions; a CI quality gate guards metrics,
  explanation exactness and single-feature shortcuts.

### Fixed
- ADR 007 said isotonic calibration; M5 uses Platt calibration.
- Only the assigned investigator may propose a case decision; only triage/investigation roles may open cases.
- Alert summaries no longer read "used an expired override to changed".

### Security
- Signing out ends the session: its access and refresh tokens (every refreshed copy too) are refused
  (`revoked_session`, migration `e6b3a9c1d702`). `/auth/refresh` is rate limited.
- The audit trail needs `audit:read` (auditors, admins), Ask SUTRA `copilot:use`, STR drafts `str:draft`,
  approving a reviewed decision `cases:decide`; Live Ops and Lab changes need `cases:investigate`.
- Sign-in rate limits key on each browser's address (the BFF forwards the one the load balancer saw),
  not on the web server's; unknown usernames cost the same as wrong passwords.
- Sign-in only redirects to same-site paths (`?next=`); the BFF refuses `.`/`..` path segments.
- Compiled bytecode, generated evidence packs and model binaries are no longer tracked in Git.
