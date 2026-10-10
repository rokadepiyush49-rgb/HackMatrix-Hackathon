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
| [017](017-learned-prioritisation.md) | Connected cases, a learned prioritiser (M7) and a documented rule baseline | Accepted |
| [018](018-incremental-ingest-and-case-revisions.md) | Order-independent incremental ingest; append-only case revisions | Accepted |
| [019](019-council-agents-and-harness.md) | Council agents on Groq inside a harness that enforces grounding | Accepted |
| [020](020-context-budgets.md) | Context budgets: batch whole items, never truncate, report coverage | Accepted |
| [021](021-behavioural-baselines-m1-m2.md) | Keep M1/M2; M2 signal threshold 0.5% → 2% on held-out evidence | Accepted |
| [022](022-model-lifecycle.md) | Train globally; promote only validated candidates; roll back | Accepted |
| [023](023-account-aggregator.md) | Account Aggregator as consented evidence; synthetic FIP for the demo | Accepted |

For every library and service — *why this, not that* — see [`docs/TECH_DECISIONS.md`](../TECH_DECISIONS.md).
