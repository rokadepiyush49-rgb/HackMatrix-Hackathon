# SUTRA — developer entry points. Run `make help`.
SHELL := /bin/bash
DB    ?= sutra
# Explicit import paths: macOS can flag venv .pth files as hidden, which Python 3.12 ignores.
export PYTHONPATH := $(CURDIR)/backend:$(CURDIR)/data/kestrel_sim
PY    := uv run --no-sync

.PHONY: help setup db migrate seed train detect demo api web test lint typecheck clean

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

train:           ## Train ML models on an independent synthetic world (seed 7)
	$(PY) python -m app.cli train

detect:          ## Run the full pipeline: signals → chains → alibi → briefs
	$(PY) python -m app.cli detect

demo: seed train detect  ## Everything needed for the demo, from scratch

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

clean:           ## Remove generated data and caches
	rm -rf data/generated var .pytest_cache .ruff_cache
