# Contributing to SUTRA

## Workflow

1. Branch from `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `infra/<topic>`.
2. Commit using [Conventional Commits](https://www.conventionalcommits.org/) — `feat(alibi): …`,
   `fix(api): …`, `infra(helm): …`. The changelog and release notes are built from them.
3. Open a pull request. CI must be green (lint, 60+ tests incl. scenario twins, typecheck, build,
   Helm/Terraform validation, image scan) and a CODEOWNER must approve.
4. Squash-merge. Merging to `main` builds, signs and stages the release automatically.

## Local setup

```bash
make setup      # uv + npm dependencies
make demo       # Postgres schema, synthetic world, models, detection
make api        # http://localhost:8000/docs
make web        # http://localhost:3000
```

Or everything in containers: `docker compose up --build`.

## Before you push

```bash
make lint test typecheck
pre-commit run --all-files     # optional but recommended: same checks as CI's fast lane
```

## Rules that reviews enforce

- **Detection changes need a twin.** A new or changed detector ships with a suspicious scenario it
  catches *and* a legitimate twin it stays quiet on (`data/scenarios/scenarios.yaml`, `backend/tests/test_scenarios.py`).
- **No opaque scores.** Alerts carry named dimensions and the rule that set the priority.
- **The LLM is language-only.** It may phrase and cite; it never creates, scores or closes an alert.
- **Every architectural choice gets an ADR** in `docs/adr/` — what we chose, what we rejected, and why.
- **Synthetic data only.** Never commit real customer, staff or transaction data.
