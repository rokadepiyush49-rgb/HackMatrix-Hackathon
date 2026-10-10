# Architecture Decision Records

Short records of decisions that shape SUTRA, including where the MVP deliberately
differs from the long-term architecture. Format: context → decision → consequences.

| # | Decision | Status |
|---|----------|--------|
| [001](001-modular-monolith.md) | FastAPI modular monolith, not microservices | Accepted |
| [002](002-graph-in-postgres.md) | Keep the evidence graph in PostgreSQL; run graph algorithms in-process | Accepted |
| [003](003-bitemporal-events.md) | Bitemporal event model (valid time + system time) | Accepted |
| [004](004-llm-boundary.md) | The LLM writes language only — cite-or-drop, deterministic fallback | Accepted |
| [005](005-pseudonymous-by-default.md) | Staff pseudonymous by default; two-person unmask | Accepted |
| [006](006-background-work.md) | In-process pipeline and background tasks for the MVP | Accepted |
| [007](007-models-and-leakage.md) | Glass-box chain classifier; train on an independent synthetic world | Accepted |
| [008](008-container-supply-chain.md) | Signed, minimal, reproducible container images | Accepted |
| [009](009-eks-over-ecs.md) | Amazon EKS over ECS or Lambda | Accepted |
| [010](010-gitops-argocd.md) | GitOps with Argo CD; canary releases with Argo Rollouts | Accepted |
| [011](011-region-and-residency.md) | Mumbai primary, Hyderabad DR — data stays in India | Accepted |
| [012](012-evidence-object-lock.md) | Evidence packs in S3 Object Lock (WORM) | Accepted |
| [013](013-observability-otel.md) | OpenTelemetry, structured logs and request IDs | Accepted |
| [014](014-identity-and-secrets.md) | No long-lived credentials anywhere | Accepted |
| [015](015-llm-residency.md) | LLM narration off in production until inference can stay in India | Accepted |
| [016](016-live-feed-demo.md) | A live feed for the end-to-end demo; detection re-runs keep IDs and cases | Accepted |

For every library and service — *why this, not that* — see [`docs/TECH_DECISIONS.md`](../TECH_DECISIONS.md).
