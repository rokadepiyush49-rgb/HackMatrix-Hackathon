# Threat model (STRIDE)

**Assets:** customer and staff data, alert and case decisions, evidence packs, the audit trail,
model artifacts, and the credentials that reach them.
**Adversaries:** a malicious insider (the very person SUTRA investigates), an external attacker
on the internet, a compromised dependency or build, and a curious-but-unauthorised colleague.

| STRIDE | Threat | Control | Where |
|---|---|---|---|
| **Spoofing** | Stolen session token replayed from another machine | Tokens live only in the BFF (httpOnly, `SameSite=Lax`, `Secure` in production); 15-min access tokens; 12-h refresh tokens | `frontend/app/api/session`, `backend/app/core/security.py` |
| | CI or a pod impersonating another workload in AWS | GitHub OIDC trust limited to `main` of this repo; Pod Identity per service account | `infra/terraform/modules/sutra/identity.tf` |
| **Tampering** | Insider edits an evidence pack after issue | S3 Object Lock COMPLIANCE + per-file and per-item SHA-256; `/verify` recomputes | ADR 012, `backend/app/core/storage.py` |
| | Someone rewrites the audit trail | Hash chain: each entry commits to the previous one; verification on every audit view and in tests | `backend/app/core/audit.py` |
| | Malicious image deployed | Images signed in CI (cosign keyless); Kyverno verifies the workflow identity; digests pinned | ADR 008, `deploy/policies/kyverno.yaml` |
| | Prompt injection through ticket text into the LLM | LLM cannot act: language only; every sentence must cite evidence the verifier checks; deterministic fallback | ADR 004, `backend/app/copilot/engine.py` |
| **Repudiation** | "I never approved that closure" | Every view, proposal, review, unmask and pack is an audit entry with actor and timestamp, in the same DB transaction as the action | `backend/app/api/cases.py`, `governance.py` |
| **Information disclosure** | Investigators browsing colleagues' identities | Staff pseudonymous by default; unmask needs a reason and a *different* approver, expires in 4 h, audited | ADR 005 |
| | PII in logs or traces | HMAC-tokenised identifiers at ingest; collector deletes auth headers, cookies, query strings; WAF logs redact cookies | `deploy/observability/otel-collector.yaml` |
| | Database or bucket exposed | Database subnets have no internet route; SGs allow only the cluster; S3 public access blocked; TLS-only bucket policy; KMS everywhere | `network.tf`, `data.tf`, `evidence.tf` |
| | API discovered and called directly | API has no public route — only the web tier is behind the ALB; NetworkPolicy allows only web → api | `deploy/helm/sutra/templates/networkpolicy.yaml` |
| **Denial of service** | Credential stuffing, scraping | WAF rate-based rule + managed rules; slowapi limits (10/min on login) shared via Valkey | `edge.tf`, `backend/app/core/limiter.py` |
| | One heavy detection run starving the API | Separate CronJob pods with their own requests/limits; Karpenter capacity; `concurrencyPolicy: Forbid` | `templates/jobs.yaml` |
| **Elevation of privilege** | An investigator closes their own case | Four-eyes: only the assignee proposes, a *different* person with `cases:review` decides — enforced by the API, tested | `backend/tests/test_api.py` |
| | Container escape / lateral movement | Non-root, read-only root, no capabilities, seccomp, PSA `restricted`, IMDSv2 hop limit 1, distroless web | `docker/`, `templates/_helpers.tpl` |
| | Production running with demo settings | API refuses to start in staging/prod with default secrets, demo personas or non-WORM storage | `backend/app/core/config.py`, `test_platform.py` |

## Residual risks

- Refresh tokens are not yet revocable before expiry (no server-side denylist); production should
  sit behind the bank's SSO (OIDC), which owns session revocation.
- A user with both `cases:review` and the assignee role can't exist today, but a future role change
  could create one — the four-eyes test would catch it in CI.
- Sigstore keyless signing relies on the public Rekor transparency log being available at admission
  (Kyverno caches verification results; a private Rekor is an option).
- Source-system completeness: SUTRA lists gaps (e.g. CCTV, EDR not ingested) rather than inferring
  them; findings are only as complete as the feeds.
