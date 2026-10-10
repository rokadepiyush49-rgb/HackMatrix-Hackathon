# Why this, not that — SUTRA's technology decisions

Every component in SUTRA is here for a reason we can state. Each row says what we chose, why,
what we rejected, and the trade-off we knowingly accepted. Bigger decisions have a full ADR in
[`docs/adr/`](adr/README.md).

The three constraints behind almost every choice:

1. **Explainability is a requirement, not a feature.** An investigator, a regulator and a court must
   be able to see *why* an alert exists. That rules out black boxes wherever a glass box will do.
2. **Evidence must be provable.** Anything SUTRA asserts must trace to a system-of-record entry,
   and exported evidence must be demonstrably untampered.
3. **It runs inside a bank.** Data stays in India (RBI localisation), nothing runs with
   long-lived credentials, and every privileged action leaves an audit trail.

---

## 1. Backend

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **Python 3.12** | Detection is pandas/NetworkX/LightGBM work; the API shares those models and dataclasses, so one language means no translation layer between "what detection found" and "what the API serves". 3.12 for its faster interpreter and better error messages. | Go/Java for the API with Python only for ML — two codebases describing the same domain objects. | Python is slower per request than Go; irrelevant at investigator traffic, and hot paths are vectorised pandas. |
| **FastAPI** | Type-driven: Pydantic models are the request/response contract *and* the OpenAPI schema the frontend types come from. Dependency injection gives us `require("cases:review")` per endpoint — RBAC is visible in the route signature. | Django (ORM and admin we don't need; heavier), Flask (validation and OpenAPI bolted on). | Fewer batteries than Django; we add rate limiting (slowapi) and auth ourselves. |
| **Modular monolith** ([ADR 001](adr/001-modular-monolith.md)) | Loom, Needle, Alibi, Brief, Mend and the Council share one domain model. Hard module boundaries, one deployable. | Microservices per engine — network hops and distributed transactions for no scaling benefit at a bank's volume. | One image scales as a unit; `needle` is the first candidate to split into a stream processor if volume demands. |
| **Pydantic v2 + pydantic-settings** | Configuration is validated at startup. Staging and prod *refuse to start* with default secrets, demo personas or non-WORM evidence storage. A misconfiguration fails the deploy, not an audit. | Plain `os.environ` lookups — errors surface at 2 a.m., not at boot. | — |
| **SQLAlchemy 2 (typed ORM + Core)** | Typed models for the OLTP side (cases, audit, packs); Core and raw `COPY` for bulk loads. Testability: the same session can be bound to a rolled-back transaction in tests. | Raw SQL everywhere (no typing), Django ORM (couples us to Django). | ORM learning curve; we drop to Core where it matters. |
| **psycopg 3** | Native `COPY` for loading ~300k synthetic rows in seconds, server-side binding, maintained successor to psycopg2. | asyncpg — fast, but the pipeline is CPU-bound pandas work; async buys nothing there. | Sync driver; the API runs sync endpoints in a thread pool, which is plenty here. |
| **Alembic** | Versioned, reviewable schema changes; runs as a Helm pre-upgrade hook so the schema is migrated before new pods start. Migrations are written expand-then-contract so old pods keep working. | `create_all()` — no history, no rollback story. | Migrations must be written carefully for zero-downtime. |
| **uv (workspace + lockfile)** | One lockfile for the API and the simulator package, resolves in seconds, reproducible installs in CI and Docker (`uv sync --frozen`). | pip + requirements.txt (no lock of transitive deps), Poetry (slower, weaker workspace support). | Newer tool; pinned version in the Dockerfile. |
| **Sync detection pipeline as a CLI** (`python -m app.cli detect`) | The same entry point runs locally, in CI, as a Kubernetes CronJob and as a one-off Job. Idempotent, so retries are safe. | Celery + broker — another stateful system to run for a job that runs every 15 minutes. | No sub-minute latency; the roadmap moves Needle to streaming when that matters. |
| **SSE for the live replay and Live Ops runs** | One-way server → browser stream; works through the BFF, proxies and the ALB with no extra protocol. Live Ops events carry ids, so a reconnecting browser resumes (`Last-Event-ID`) instead of starting over. | WebSockets — bidirectional, which we don't need, and harder through proxies. | Run progress is held in API memory; a restart loses the log, not the data. |
| **Held-back feed with CDC-style ingest for the live demo** ([ADR 016](adr/016-live-feed-demo.md)) | The demo runs the real pipeline on rows that are genuinely not in the database before Play; ingest applies each row's effects (balances, mobile, limits) and reset reverses them exactly. | Pre-computed results behind an animation — a slideshow, not a demo; a second "demo" code path — would prove nothing about production. | ~25 s per reset, because it re-detects. |
| **Stable alert identity across runs** | `(kind, root_ref)` keys a chain; IDs, human triage and cases survive every scheduled run, in one transaction. | Delete-and-rebuild — what we had, and it silently wiped open cases every 15 minutes. | A chain whose root changes gets a new ID (rare; the old one is kept if it has a case). |
| **PyJWT, short-lived access + refresh tokens, held only by the BFF** | Tokens never reach browser JavaScript (httpOnly cookies on the Next.js side), so XSS cannot steal a session token. | Tokens in localStorage — readable by any injected script. | The BFF is in the request path for every call. |
| **bcrypt** | Slow-by-design password hashing with a mature implementation. | SHA-256 for passwords — fast, hence brute-forceable. | Production uses the bank's SSO (OIDC) instead; bcrypt protects the demo personas. |
| **HMAC-SHA256 tokenisation of PII at ingest** | Phones and ID numbers can still be *compared* (shared-identifier detection) without being stored in clear text. | Encryption with a reversible key (decryptable by anyone with the key), plain hashing (rainbow-table-able for phone numbers). | Tokens can't be reversed even by us — by design. |
| **slowapi rate limiting, Valkey-backed in prod** | Per-client limits on login and the API; a shared counter across replicas. | Per-process limits only — N replicas = N× the limit. | One more dependency (Valkey) in prod; optional locally. |
| **ReportLab** | Deterministic PDF generation in-process, no headless browser in the image. | Puppeteer/Chromium — a 300 MB browser in a security-sensitive container. | Layout is code, not HTML/CSS. |

## 2. Detection and machine learning

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **Rules + graph detectors + two small models, combined by an explicit priority lattice** | Each signal is explainable on its own. The lattice is readable rules over 7 named dimensions, so "why P1?" has a sentence for an answer. | One end-to-end risk score from a deep model — unexplainable to an investigator or a court. | Rules need maintenance; the scenario twins catch regressions. |
| **Chain assembly (Needle) before alerting** | Alerts are time-ordered privilege → access → change → payment chains, not single events. This is the core idea: no team sees the thread alone. | Alerting on single detector hits — the 772 raw access signals Alibi removes. | More logic to maintain than a threshold. |
| **Alibi (explanation-based auditing)** | Look for the *ordinary* reason first: ticket, portfolio, queue, customer presence, roster. 98.4% of staff accesses clear here. | Anomaly detection on access logs alone — flags every pension camp and month-end. | Depends on those sources being ingested; gaps are listed, not guessed. |
| **pandas + NumPy** | Vectorised joins over hundreds of thousands of events in seconds; the team knows it. | Spark — cluster overhead for single-machine data; Polars — faster, but LightGBM/scikit-learn interop and team familiarity favoured pandas for the MVP. | Single-node memory bound; sized at 3–6 GiB per detection job. |
| **NetworkX** | Cycles (G1), pass-through (G2), fan-in/out (G3), Louvain communities (G4) in a few lines, in-process. | Neo4j — a second database and sync problem for graphs we can compute per run ([ADR 002](adr/002-graph-in-postgres.md)). | Not for billion-edge graphs; fine per window. |
| **M5: logistic regression + Platt calibration** | Exact per-feature contributions (coefficient × standardised value) — a glass box. It can move a chain between watch-list and queue, never raise one alone. | Gradient boosting for M5 — marginally better AUC, worse explanations for the decisive model. | Linear decision boundary. |
| **M6: LightGBM with native TreeSHAP** | Mule-likeness is genuinely non-linear (age × presence × pass-through). LightGBM's `pred_contrib` gives exact Shapley values. | Neural nets — no gain on tabular data, no exact attributions. | Graded as model evidence (C); cannot carry a case alone. |
| **Train on an independent synthetic world (seed 7), evaluate on the demo world (seed 42)** ([ADR 007](adr/007-models-and-leakage.md)) | Prevents the classic leak of testing on the scenarios you trained on. | Training on the demo data — inflated metrics. | Metrics are labelled "not real-bank accuracy". |
| **Models built in the image, not committed** | `docker build` trains M5/M6 deterministically from code + seed; the model card records seed and metrics. Git holds source, not binaries. | Committed `.joblib` files — unreviewable binary diffs, provenance unclear. | Image builds take ~1 minute longer. |
| **RapidFuzz** for entity resolution | Fast fuzzy matching for names and addresses (employee ↔ customer links). | Exact matching — misses "Kulkarni R." vs "Rohan Kulkarni". | Tuned thresholds; false links rejected unless address *and* surname or phone agree. |
| **Scenario twins as tests** | Every suspicious scenario has a legitimate look-alike differing by one fact. CI fails if the twin fires or the suspicious one is missed. | Precision/recall on a labelled set only — doesn't test the *reason* the system stays quiet. | Scenarios must be authored with care. |

## 3. AI layer

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **Claude (Opus 5.5) for language only** ([ADR 004](adr/004-llm-boundary.md)) | Drafting narratives, STR text and cited answers is where an LLM is strong. Detection, scoring and closing stay deterministic and auditable. | LLM-driven detection — non-deterministic, unexplainable, and prompt-injectable through evidence text. | Answers are only as rich as the evidence book. |
| **Structured JSON output + cite-or-drop verifier** | Every sentence must cite evidence codes; the verifier checks codes, ₹ amounts, times and IDs against the cited records and drops anything it can't tie down. | Free-text answers — impossible to verify automatically. | Some correct-but-uncited sentences get dropped (shown to the user as dropped). |
| **Deterministic fallback engine** | Without a key or network, answers are composed from the evidence book by rules. The demo never depends on an external call. | Hard dependency on the API. | Fallback prose is plainer. |
| **Opus 5.5 at `medium` effort** | The current Opus: 20% cheaper than Opus 5 at the same capability tier; effort set explicitly because Opus 5.5 defaults to `medium` and thinking can't be disabled. | Sonnet for cost — the user-facing answer is evidence-heavy reasoning; we tune effort before downgrading the model. | Re-measure if answer quality needs `high`. |
| **Two providers behind one engine** (`SUTRA_LLM_PROVIDER`) | `anthropic`: structured JSON-schema output and server-side refusal fallbacks. `bedrock`: Claude in Amazon Bedrock (Messages API) with IAM via Pod Identity — no API key in the cluster; schema stated in the prompt and parsed defensively, since structured outputs aren't offered there. | An OpenAI-compatible shim — loses structured outputs, caching and typed errors. | Two request shapes to test (both are, with a fake client). |
| **Prompt caching on the case evidence** | Every question about a case resends the same evidence; an explicit cache breakpoint on that block (honoured on both providers) makes follow-up questions cheaper and faster. | Automatic caching — not available on Bedrock. | Breakpoint placement must stay stable (sorted JSON). |
| **LLM off by default in production** ([ADR 015](adr/015-llm-residency.md)) | From Mumbai/Hyderabad, Claude in Bedrock currently offers only global routing, so prompts could be processed outside India. Until an India-resident option exists, prod uses the deterministic engine; staging (synthetic data) runs Claude. | Turning it on and hoping — a residency finding in the first audit. | Plainer prose in prod; every fact is still cited. |
| **Multi-agent Council, deterministic over Loom** | Eight adversarial roles (incl. a Defence Agent) argue from the same records; agents may *request* records, and the moderator answers from Loom or says "not ingested". No confidence score; dissent is kept. | Free-running LLM agents — persuasive, not grounded. | Agent turns follow a protocol rather than open conversation. |

## 4. Data stores

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **PostgreSQL 17 as the single system of record** | Events, evidence book, cases and the audit hash chain need ACID transactions *together*. JSONB holds evidence facts; arrays and GIN indexes serve entity lookups. | Separate graph DB + document store + RDBMS — three consistency problems. | Graph algorithms run in the app, not the database. |
| **Bitemporal events** ([ADR 003](adr/003-bitemporal-events.md)) | "What did the bank know at 21:46?" needs both valid time and recorded time — the Timeline Replay is literally this query. | Overwrite-in-place — loses what was known when. | More columns and careful queries. |
| **Amazon RDS for PostgreSQL (Multi-AZ, gp3)** | Managed backups (35-day PITR), patching, encryption with our KMS key, `rds.force_ssl`, pgaudit for DDL/role changes, cross-region backup replication for DR. | Aurora PostgreSQL — better at very high scale but costs more at our size and diverges slightly from vanilla Postgres; self-managed Postgres on EKS — we'd own failover and backups. | Vertical scaling ceiling far above our need; Aurora is the documented next step. |
| **No pgvector (yet)** | Nothing in the MVP needs semantic search; retrieval is by evidence code and entity. | Adding embeddings "because RAG" — cost and complexity without a use case. | Revisit for free-text ticket matching. |
| **Valkey (ElastiCache)** | Shared rate-limit counters across replicas. Valkey is the Linux Foundation fork of Redis; ElastiCache prices it lower than Redis OSS and it is wire-compatible. | Redis OSS (licence change, higher price), DynamoDB counters (latency, cost per request). | One more managed service. |
| **S3 with Object Lock (COMPLIANCE) for evidence packs** | Write-once storage: until the retention date (5 years — PMLA Rule 10), nobody, including the AWS root account, can overwrite or delete a pack. The SHA-256 manifest in Postgres proves integrity on demand. | Packs as database blobs (mutable by a DBA), plain S3 with versioning (deletable by an admin). | COMPLIANCE mode is irreversible — staging uses GOVERNANCE with 1-day retention so test buckets can be cleaned up. |

## 5. Frontend

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **Next.js 16 (App Router) as UI *and* BFF** | The Next server holds the session and forwards to the API, so the browser never sees the API or a JWT. One origin means a strict CSP (`connect-src 'self'`). `output: "standalone"` ships only the files the server needs (no `node_modules` install in the image). | SPA talking to the API directly — tokens in the browser, CORS, a public API surface. | One more hop; negligible. |
| **React 19 + TypeScript (strict)** | Typed contracts for 30+ screens; the React Compiler lint rules catch effect/state bugs at build time. | Plain JS — refactors on a 10k-line UI become guesswork. | — |
| **Web Speech API for voice** (Council, Live Ops) | Speech runs in the browser from the operating system's voices: works offline at a venue, costs nothing, and no case text leaves the machine. Indian-English voices are preferred, and each agent gets its own voice and pitch. | Cloud TTS (Polly, ElevenLabs) — better voices, but a network dependency on stage, a per-character bill and case text sent to a third party. | Voice quality depends on the OS; the visual flow never depends on sound. |
| **TanStack Query** | Caching, request de-duplication and background refresh for a read-heavy investigator app. | Redux — boilerplate for what is server state, not client state. | — |
| **Tailwind CSS v4 + design tokens** | Semantic colour tokens (threat, amber, ok, ai, info) used consistently; light/dark themes from one token set. | CSS-in-JS — runtime cost and SSR complexity. | Long class strings. |
| **Radix UI primitives** | Accessible dialogs, tabs, popovers and tooltips (focus traps, ARIA) without imposing a look. | Building them by hand — accessibility bugs. | — |
| **Motion (Framer Motion)** | Purposeful animation: the chain rail draws itself, the Council seats speak in turn. Respects `prefers-reduced-motion`. | CSS-only — not enough for orchestrated sequences. | Bundle size; motion is code-split per page. |
| **React Flow (@xyflow/react)** | Interactive graphs (money trail, mule constellation, risk network) with custom nodes and animated money particles. | D3 directly — rebuilding pan/zoom/selection. | Large graphs need our own layouts (layered, radial rings, wrapped tiers). |
| **Recharts, cmdk, next-themes, lucide-react** | Charting, ⌘K palette, theme switch, icons — small, focused libraries. | — | — |

## 6. Containers and Kubernetes

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **Multi-stage Dockerfiles** | Build tools never reach the runtime image; the dependency layer is cached until `uv.lock` / `package-lock.json` change. | Single-stage images — compilers and caches in production. | — |
| **Non-root, read-only root filesystem, no capabilities** | An attacker with code execution can't write binaries, escalate, or reach node credentials (IMDSv2 hop limit 1). Only `/tmp` (emptyDir) is writable. | Default root containers. | Apps must not write outside `/tmp` — enforced by tests and Kyverno. |
| **Distroless Node runtime for the web tier** | No shell, no package manager, no npm — far fewer CVEs and nothing for an attacker to run. | `node:alpine` (musl surprises, still has a shell). | Debugging needs ephemeral debug containers. |
| **Multi-arch images (amd64 + arm64)** | Runs on Graviton nodes in EKS (better price/performance) and on any laptop. | amd64 only — locks us out of Graviton savings. | Longer CI builds (QEMU for the other arch). |
| **Amazon EKS** ([ADR 009](adr/009-eks-over-ecs.md)) | SUTRA is several cooperating workloads (API, BFF, migrations, scheduled detection) that need network policies, admission control, canaries and GitOps — all Kubernetes-native, and portable to a bank's on-prem OpenShift/Kubernetes. | ECS Fargate (simpler, but no NetworkPolicy/admission/GitOps ecosystem, AWS-only), Lambda (15-minute limit, cold starts with pandas/LightGBM). | Kubernetes has a learning curve and a control-plane fee. |
| **Karpenter + Graviton (m7g)** | Right-sized nodes provisioned in seconds for the detection job's burst; consolidation removes idle nodes. | Cluster Autoscaler with fixed node groups — slower, wasteful. | One more controller to operate. |
| **Helm chart** | Parameterised per environment (`values-staging.yaml`, `values-prod.yaml`), hooks for migrations, a format every platform team knows. | Kustomize (no templating for the Rollout/Deployment switch), raw manifests (duplication). | Templates need linting — CI renders and validates them with kubeconform. |
| **Argo CD (GitOps)** ([ADR 010](adr/010-gitops-argocd.md)) | The cluster pulls its desired state from Git; drift is auto-corrected; the audit trail of production changes is the Git history. Staging syncs automatically, prod on approval. | CI pushing `helm upgrade` — CI holds cluster credentials, and drift goes unnoticed. | Another controller in the cluster. |
| **Argo Rollouts (canary) in prod** | 10% → 50% → 100% with pauses; abort returns traffic to the stable version in seconds. | Plain rolling updates — every pod gets a bad release. | Rollout CRD instead of Deployment (the chart switches by value). |
| **External Secrets Operator** | Secrets live in AWS Secrets Manager (KMS-encrypted, rotatable); the cluster gets a synced copy. Nothing secret in Git or Helm values. | Sealed Secrets/SOPS (secrets in Git, rotation is a commit), Helm values (plain text). | Depends on ESO being healthy (refresh interval 1 h, existing Secret keeps working). |
| **EKS Pod Identity** | Per-service-account AWS permissions with no OIDC-provider-per-cluster plumbing; the API can write evidence and call Bedrock, the web tier can do nothing in AWS. | IRSA (works, more setup), node instance roles (every pod gets every permission). | Requires the Pod Identity agent add-on. |
| **NetworkPolicy via the VPC CNI (eBPF)** | Default-deny inside the namespace, then only web → api → data stores. The VPC CNI enforces it natively. | Calico — a second CNI component to run. | — |
| **Kyverno** | Policies in YAML: only images signed by our release workflow run; no `:latest`; read-only root required. | OPA Gatekeeper (Rego — harder for the team to review). | Admission webhook latency (bounded, 15 s timeout). |
| **Pod Security Admission `restricted`** | The built-in Kubernetes baseline enforced at namespace level. | — | — |
| **Probes split: liveness vs readiness** | Liveness never touches dependencies, so a database blip doesn't restart every pod; readiness removes a pod from the load balancer until Postgres answers and models are loaded. | One `/health` for both — cascading restarts during a DB failover. | — |
| **`preStop` sleep + graceful shutdown** | The ALB deregisters the pod before it stops accepting connections — zero dropped requests on deploy. | — | Deploys take ~10 s longer per pod. |

## 7. AWS infrastructure

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **ap-south-1 (Mumbai), DR in ap-south-2 (Hyderabad)** ([ADR 011](adr/011-region-and-residency.md)) | RBI's directive on storage of payment system data requires it to stay in India. Both regions are in India, so DR copies stay compliant. | A cheaper region outside India — non-compliant. | Fewer services/instance types than us-east-1. |
| **Terraform** | Declarative, reviewable plans, the largest module ecosystem (we use the community VPC/EKS/RDS modules), cloud-agnostic skills. | AWS CDK (imperative, AWS-only), Pulumi (smaller ecosystem in banking), ClickOps (no review, no history). | HCL limitations; complex logic stays in modules. |
| **S3 backend with native locking (`use_lockfile`)** | Terraform ≥ 1.10 locks state in S3 itself — no DynamoDB lock table to create and pay for. | DynamoDB locking (deprecated path). | Needs Terraform 1.10+ (pinned). |
| **Three-tier VPC across 3 AZs** | Public (ALB, NAT), private (pods), database (no internet route at all). NAT per AZ in prod so one AZ failure doesn't cut egress. | Single subnet tier — databases one misconfigured route from the internet. | NAT gateways cost; staging uses one. |
| **VPC endpoints (S3, ECR, STS, Secrets Manager, KMS, Logs)** | AWS API traffic stays on the AWS network, never the internet; cheaper than NAT data processing for image pulls. | Everything through NAT. | Interface endpoints have an hourly cost. |
| **One customer-managed KMS key per data domain** | Separate keys for operational data and evidence: auditing or revoking one never touches the other; rotation enabled. | AWS-managed keys — no separate control or audit boundary. | Key policies to maintain. |
| **AWS WAF on the ALB** | Managed OWASP/known-bad-input/IP-reputation rules, a per-IP rate limit and a geo allow-list (investigators work from India); cookies redacted from WAF logs. | No WAF — the app is the only defence. | Managed-rule false positives need tuning. |
| **GitHub OIDC → AWS** | CI gets a 1-hour credential, only for `main` of this repo, only to push two ECR repositories. No AWS keys stored in GitHub. | Long-lived IAM user keys in GitHub secrets — the most common cloud breach path. | — |
| **ECR with immutable tags + scan on push** | A tag can never be repointed at different bytes; deploys pin digests anyway. | Mutable tags — "which `v1.2` is running?". | — |
| **AWS Budgets + CloudWatch alarms + SNS** | Cost and capacity surprises page a human before they become incidents. | — | — |

## 8. CI/CD and supply chain

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **GitHub Actions** | Lives with the code; OIDC to AWS and Sigstore; free for public repos. | Jenkins (a server to secure and patch). | — |
| **One CI gate for everything** | Lint, 60+ tests incl. scenario twins against a real Postgres, typecheck, production build, Helm render + kubeconform, Terraform validate + tflint + Checkov, hadolint, image build + Trivy, gitleaks. | Separate optional checks — they get ignored. | CI takes several minutes; jobs run in parallel. |
| **Build once, promote by digest** | The exact bytes tested in staging are what reaches prod; promotion is a PR that pins digests. | Rebuilding per environment — what you tested isn't what you ship. | — |
| **Sigstore cosign (keyless)** | Images are signed with the workflow's OIDC identity; Kyverno verifies that identity at admission. No signing keys to leak. | Key-based signing (key management), no signing. | Depends on Sigstore's public transparency log (Rekor). |
| **SBOM (SPDX) + SLSA build provenance** | For every image we can answer "what's inside?" and "which commit and workflow built it?" — increasingly asked by bank vendor-risk teams. | — | Extra CI minutes. |
| **CodeQL, Dependabot, OpenSSF Scorecard** | Static security analysis, dependency updates as PRs, and an external grade of repo hygiene. | — | PR noise, grouped weekly. |
| **Conventional Commits + CODEOWNERS + PR template** | Readable history, automatic changelog, the right reviewer every time, and a checklist that asks the questions that matter (twin scenario? ADR? real data?). | — | — |

## 9. Observability

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **OpenTelemetry (API + BFF)** | One trace from the browser request through the Next.js BFF, FastAPI and each SQL statement. Vendor-neutral: export to X-Ray/Tempo/Datadog by changing collector config, not code. | A vendor SDK — lock-in. | Instrumentation overhead (off unless an OTLP endpoint is set). |
| **Collector-side scrubbing** | Auth headers, cookies and query strings are deleted in the collector, so PII never leaves the process boundary in telemetry. | Trusting every library not to log PII. | — |
| **Structured JSON logs + `X-Request-ID`** | Every log line carries the request ID that's echoed to the client; a user-reported ID finds the exact request. Untrusted IDs are replaced, never echoed. | Free-text logs. | Less readable in a raw terminal (dev mode prints plain text). |
| **CloudWatch Container Insights, Amazon Managed Prometheus, X-Ray** | Managed backends; nothing to run or patch. | Self-hosted Prometheus/Grafana/Jaeger in-cluster — more to operate. | AWS-specific backends (the code isn't). |

## 10. Testing

| Choice | Why | Rejected | Trade-off accepted |
|---|---|---|---|
| **pytest with a rolled-back transaction per API test** | API tests exercise the real database and real permission rules (four-eyes, two-person unmask), and leave no trace. | Mocked databases — they test the mock. | Needs a seeded Postgres in CI (it runs the full demo pipeline first). |
| **In-memory scenario tests** | The whole pipeline runs without a database in ~25 s; scenario twins gate every PR. | Only end-to-end tests — slow, flaky. | — |
| **Contract checks on infrastructure** | `helm template | kubeconform` and `terraform validate` + Checkov catch broken manifests and insecure resources before anyone runs `apply`. | Finding out in the cluster. | Schemas for CRDs come from a community catalogue. |
