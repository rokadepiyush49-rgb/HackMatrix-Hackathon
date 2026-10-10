# Security policy

SUTRA handles (synthetic) banking and staff data, so security reports get priority over features.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting:
*Security → Report a vulnerability* on this repository. Include steps to reproduce, the affected
commit or image digest, and the impact you expect. We acknowledge within 2 working days and agree
a disclosure date with you; fixes for critical issues target 7 days.

## Supported versions

Only the latest release on `main` receives fixes.

## What is in place

| Layer | Control |
|---|---|
| Code | CodeQL (security-extended), ruff, ESLint, gitleaks secret scanning, Dependabot |
| Supply chain | Images built only in CI, signed with Sigstore cosign (keyless OIDC), SBOM (SPDX) and SLSA provenance attached; Kyverno rejects unsigned images at admission; OpenSSF Scorecard |
| Runtime | Non-root, read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`, Pod Security Admission `restricted`, default-deny NetworkPolicies |
| Identity | No long-lived cloud keys: GitHub → AWS via OIDC; pods → AWS via EKS Pod Identity; secrets from AWS Secrets Manager via External Secrets |
| Data | KMS-encrypted RDS, ElastiCache, S3 and Kubernetes Secrets; TLS enforced to the database; evidence packs written once under S3 Object Lock (COMPLIANCE) |
| Application | Pseudonymous staff by default with two-person unmask; four-eyes case decisions; hash-chained audit log; JWTs only server-side (BFF, httpOnly cookies); rate limits; WAF |
| Configuration | The API refuses to start in staging/prod with default secrets, demo personas or non-WORM evidence storage |

See `docs/security/threat-model.md` for the STRIDE analysis behind these controls.
