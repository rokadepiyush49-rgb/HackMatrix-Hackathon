# SUTRA — developer entry points. Run `make help`.
SHELL := /bin/bash
DB    ?= sutra
# Explicit import paths: macOS can flag venv .pth files as hidden, which Python 3.12 ignores.
export PYTHONPATH := $(CURDIR)/backend:$(CURDIR)/data/kestrel_sim
PY    := uv run --no-sync

.PHONY: help setup db migrate seed train detect demo live-play live-reset bank-check replay eval-behaviour api web test lint typecheck check up down images helm-lint tf-check clean

help:            ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-10s\033[0m %s\n",$$1,$$2}'

setup:           ## Install Python + Node dependencies
	uv sync --all-groups
	cd frontend && npm install

db:              ## Create the local Postgres database (idempotent)
	@psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$(DB)'" | grep -q 1 || createdb $(DB)

migrate: db      ## Apply database migrations
	cd backend && $(PY) alembic upgrade head

seed: migrate    ## Generate Kestrel-Sim data and load it
	$(PY) python -m app.cli seed

train:           ## Train M5, M6, M7 on worlds 7–10; evaluate against rule baselines (ml/reports)
	$(PY) python -m app.cli train

detect:          ## Run the full pipeline: signals → chains → alibi → briefs
	$(PY) python -m app.cli detect

demo: seed train detect  ## Everything needed for the demo, from scratch

live-play:       ## Stream tonight's held-back feed into Loom and detect (what Live Ops does)
	$(PY) python -m app.cli live-play

live-reset:      ## Undo the live feed and re-detect — ready to demo again
	$(PY) python -m app.cli live-reset

bank-check:      ## Run every mock-bank scenario through SUTRA, check outcomes, undo (docs/mock-bank)
	$(PY) python -m app.cli bank-check

replay:          ## Replay tonight's feed late, duplicated, shuffled and reversed; check it converges (ml/reports/replay)
	$(PY) python -m app.cli replay

eval-behaviour:  ## Evaluate M1/M2 against rule baselines on worlds 7–11 (ml/reports/m1_m2_eval.json)
	$(PY) python -m app.cli eval-behaviour

api:             ## Run the API on :8000
	cd backend && $(PY) uvicorn app.main:app --reload --port 8000

web:             ## Run the investigator app on :3000
	cd frontend && npm run dev

test:            ## Backend tests (scenario twins included)
	$(PY) pytest

lint:            ## Lint Python + TypeScript
	$(PY) ruff check backend data
	cd frontend && npm run lint

typecheck:       ## Type-check the frontend
	cd frontend && npm run typecheck

check: lint typecheck test   ## Everything CI's application lane runs
	cd frontend && npm run build

# ── Platform ────────────────────────────────────────────────────────────────
up:              ## Full stack in containers (docker compose)
	docker compose up --build

down:            ## Stop the stack and delete its volumes
	docker compose down -v

images:          ## Build both production images locally
	docker build -f docker/api.Dockerfile -t sutra-api:local .
	docker build -f docker/web.Dockerfile -t sutra-web:local .

helm-lint:       ## Lint and render the Helm chart for every environment
	helm lint deploy/helm/sutra -f deploy/helm/sutra/values-prod.yaml
	for env in staging prod; do helm template sutra deploy/helm/sutra -f deploy/helm/sutra/values-$$env.yaml > /dev/null; done

tf-check:        ## terraform fmt + validate every root (no credentials needed)
	terraform fmt -check -recursive infra/terraform
	for d in infra/terraform/bootstrap infra/terraform/envs/staging infra/terraform/envs/prod; do \
	  terraform -chdir=$$d init -backend=false -input=false >/dev/null && terraform -chdir=$$d validate; done

clean:           ## Remove generated data and caches
	rm -rf data/generated var .pytest_cache .ruff_cache
