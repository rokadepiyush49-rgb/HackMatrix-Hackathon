# 014 — No long-lived credentials anywhere

**Context.** Leaked static credentials are the most common root cause of cloud breaches.

**Decision.**
- **People → cluster:** EKS access entries mapped to IAM Identity Center roles; private endpoint,
  optional public endpoint restricted to admin CIDRs.
- **CI → AWS:** GitHub OIDC; the role trusts only `main` of this repository and can only push to
  two ECR repositories, for one hour.
- **Pods → AWS:** EKS Pod Identity per service account — API/jobs may write evidence and call
  Bedrock; the web tier has no AWS permissions and no Kubernetes token.
- **App secrets:** AWS Secrets Manager (KMS) → External Secrets Operator → Kubernetes Secret.
  The RDS master password is generated and rotated by RDS itself and never enters Terraform state.

**Consequences.** There is no key file to leak; revoking access is an IAM change.
