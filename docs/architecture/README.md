# Architecture

SUTRA in four views: the system in its context, the containers inside it, how it is deployed on
AWS, and how a release travels from a commit to production. Diagrams are Mermaid and render on GitHub.

## 1. Context

Who uses SUTRA and which bank systems it reads. SUTRA is read-only towards source systems:
it never changes an account, a privilege or a payment.

```mermaid
flowchart LR
  inv(["Investigators<br/>L1 · L2 · Vigilance · PO"]) -->|browser, SSO| sutra
  aud(["Internal audit<br/>regulator"]) -->|read-only + evidence packs| sutra
  subgraph bank["Bank source systems (read-only feeds)"]
    cbs["Core banking<br/>txns · state changes"]
    iam["IAM<br/>entitlements"]
    hr["HRMS<br/>rosters"]
    sd["Service desk<br/>tickets · eKYC"]
    vpn["VPN · SSO · digital channel<br/>sessions · devices"]
  end
  bank -->|batch / CDC| sutra["SUTRA<br/>privilege-to-payment intelligence"]
  sutra -->|STR draft for human sign-off| fiu["FIU-IND (via Principal Officer)"]
  sutra -.->|language only, cited · off in prod, ADR 015| llm["Claude (API or Bedrock)"]
```

## 2. Containers

```mermaid
flowchart TB
  browser["Browser"] -->|HTTPS · same origin · httpOnly session cookie| web
  subgraph k8s["EKS namespace sutra-prod"]
    web["web — Next.js 16 BFF<br/>UI · session · /api/sutra proxy"]
    api["api — FastAPI<br/>auth · RBAC · cases · council · mend · packs"]
    det["detect — CronJob<br/>Alibi → Needle → Brief"]
    mig["migrate — Job (pre-sync hook)<br/>Alembic"]
  end
  web -->|JWT, in-cluster only| api
  api --> pg[("RDS PostgreSQL 17<br/>Loom events · evidence · cases · audit chain")]
  det --> pg
  mig --> pg
  api --> vk[("ElastiCache Valkey<br/>shared rate limits")]
  api -->|write-once| s3[("S3 Object Lock<br/>evidence packs")]
  api -.->|IAM, Pod Identity · optional| br["Claude in Amazon Bedrock"]
  sm["Secrets Manager"] -->|External Secrets| k8s
```

Inside `api` the code is a modular monolith ([ADR 001](../adr/001-modular-monolith.md)):

| Module | Role |
|---|---|
| `loom` | Bitemporal event store, entity resolution, frames for the pipeline |
| `needle` | 22 detectors (rules R1–R10, models M1/M2/M5/M6, graph G1–G5, ER) and chain assembly |
| `alibi` | Five explanation templates per staff access → EXPLAINED / PARTIAL / UNEXPLAINED |
| `brief` | Evidence book, 7 dimensions, priority lattice, prosecution and defence argument |
| `mend` | Counterfactual controls C1–C8 with friction measured on 90 days of history |
| `council` | Eight adversarial agents + moderator over Loom records |
| `copilot` | Cited answers and STR drafts; cite-or-drop verifier; deterministic fallback |
| `api` | HTTP surface, RBAC, four-eyes and two-person rules, hash-chained audit |

## 3. Deployment on AWS

```mermaid
flowchart TB
  user["Investigator"] --> waf["AWS WAF<br/>OWASP rules · rate limit · geo IN"]
  waf --> alb["ALB (TLS 1.3)"]
  subgraph vpc["VPC 10.40.0.0/16 · ap-south-1 · 3 AZs"]
    subgraph pub["public subnets"]
      alb
      nat["NAT GW ×3"]
    end
    subgraph priv["private subnets"]
      eks["EKS 1.31<br/>Graviton · Karpenter<br/>VPC CNI network policies"]
    end
    subgraph db["database subnets — no internet route"]
      rds[("RDS Postgres<br/>Multi-AZ")]
      cache[("Valkey<br/>Multi-AZ")]
    end
    vpce["VPC endpoints<br/>S3 · ECR · STS · Secrets · KMS · Logs"]
  end
  alb --> eks
  eks --> rds
  eks --> cache
  eks --> vpce
  vpce --> s3[("S3 evidence<br/>Object Lock · KMS")]
  s3 -.->|replication| s3dr[("ap-south-2 replica")]
  rds -.->|backup replication| rdsdr[("ap-south-2 backups")]
  eks -.-> obs["CloudWatch · X-Ray · Managed Prometheus"]
```

Infrastructure is Terraform in [`infra/terraform`](../../infra/terraform): one module
(`modules/sutra`) composed per environment (`envs/staging`, `envs/prod`).

## 4. Release flow

```mermaid
sequenceDiagram
  autonumber
  participant Dev as Developer
  participant GH as GitHub (PR + CI)
  participant Rel as Release workflow
  participant ECR as Amazon ECR
  participant Git as main branch
  participant Argo as Argo CD
  participant K8s as EKS
  Dev->>GH: Pull request
  GH->>GH: lint · 60+ tests · build · helm/kubeconform · terraform/checkov · trivy · codeql
  GH->>Git: Squash-merge (CODEOWNER approved)
  Git->>Rel: push to main
  Rel->>ECR: multi-arch build, push (OIDC, no keys)
  Rel->>ECR: SBOM · SLSA provenance · cosign keyless signature
  Rel->>Git: PR "pin digests in values-staging.yaml"
  Git->>Argo: merged
  Argo->>K8s: PreSync migrate Job → sync
  K8s->>K8s: Kyverno verifies signature · PSA restricted
  Note over Argo,K8s: Prod: tag v* → digest PR on values-prod.yaml → release manager syncs → canary 10% → 50% → 100%
```

## 5. Request path for one investigator click

1. The browser calls `/api/sutra/alerts/AL-0921-001` on the **same origin** — there is no API URL in the browser.
2. The Next.js route handler reads the httpOnly session cookie, attaches the JWT and forwards to the API inside the cluster.
3. FastAPI authenticates the token, checks the capability (`require("alerts:read")`), and reads Loom.
4. The response carries `X-Request-ID`; the same ID is on the API log line and the trace span.
5. Privileged actions (case view, decision, unmask, pack) append an entry to the hash-chained audit log in the same transaction.

## 6. The live demo path

What happens when **Play** is pressed on Live Ops ([ADR 016](../adr/016-live-feed-demo.md)). Demo mode only.

```mermaid
sequenceDiagram
  autonumber
  participant UI as Live Ops (browser)
  participant BFF as Next.js BFF
  participant API as FastAPI /live
  participant W as Run worker
  participant PG as Postgres (Loom)
  UI->>BFF: POST /api/sutra/live/runs {speed}
  BFF->>API: POST /api/v1/live/runs (JWT)
  API->>W: start (one run at a time)
  API-->>UI: 202 {run_id}
  UI->>BFF: EventSource …/live/runs/{id}/events
  loop each held-back row, in time order
    W->>PG: INSERT row + apply its effects (one transaction)
    W-->>UI: event {t, source system, summary}
  end
  W->>PG: read the 90-day window
  W->>W: Alibi → signals → Needle → Brief (a stage event each)
  W->>PG: persist — one transaction; IDs, triage and cases kept
  W-->>UI: alert · alibi verdicts · done {ground truth, scenario checks}
```

Reset runs the same worker in reverse: undo the ingested rows newest-first, remove the alerts the
feed created (recorded in the audit chain), and re-detect.
