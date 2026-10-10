# 009 — Amazon EKS over ECS or Lambda

**Context.** SUTRA runs an API, a Next.js BFF, a migration step that must precede every release,
and a scheduled detection job that needs several GiB of memory for minutes at a time. Banks often
also run their own Kubernetes (OpenShift, Tanzu) on-premises.

**Options.**
- *Lambda*: 15-minute limit and cold starts with pandas/LightGBM; the detection job doesn't fit.
- *ECS Fargate*: simplest to operate, but no NetworkPolicy, no admission control (signature
  verification), no GitOps controller ecosystem, and AWS-only.
- *EKS*: Kubernetes-native NetworkPolicy (VPC CNI, eBPF), Pod Security Admission, Kyverno,
  Argo CD, Argo Rollouts, External Secrets, Karpenter; the same Helm chart runs on any conformant cluster.

**Decision.** EKS, with a small managed Graviton node group for add-ons and Karpenter for
application capacity. Pod Identity for AWS permissions; access entries (API mode) for humans.

**Consequences.** Higher operational surface than Fargate, paid back by policy enforcement and
portability: a bank can take `deploy/helm/sutra` to its own cluster unchanged.
