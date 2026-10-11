# syntax=docker/dockerfile:1.10
# SUTRA API + batch jobs (migrate, seed, detect). One image, different commands.
#
# Stages
#   deps     resolve the locked dependency set once; cached until uv.lock changes
#   models   train M5/M6/M7 on worlds 7–10, validate, promote (app.ml.registry) — model binaries are build outputs, never committed
#   runtime  slim, non-root, no compilers, no package manager caches
#
# Build:  docker buildx build -f docker/api.Dockerfile --platform linux/amd64,linux/arm64 .

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.8

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ── deps ────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Manifests only: this layer is reused for every code change that leaves uv.lock alone.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/
COPY data/kestrel_sim/pyproject.toml data/kestrel_sim/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package sutra-backend --extra cloud

# ── models ──────────────────────────────────────────────────────────────────
FROM deps AS models
# DL3008: Debian security updates replace exact package versions, so a pin would break rebuilds; the base
# image is tracked by Dependabot and every image is scanned by Trivy instead.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY backend backend
COPY data/kestrel_sim data/kestrel_sim
COPY data/scenarios data/scenarios
ENV PYTHONPATH=/app/backend:/app/data/kestrel_sim PATH=/opt/venv/bin:$PATH
# Deterministic: same code + same worlds (seeds 7–10) → same model. Training ignores --seed; the registry
# records the worlds, metrics, libraries and the validation that promoted each model.
RUN python -m app.cli train

# ── runtime ─────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="sutra-api" \
      org.opencontainers.image.description="SUTRA privilege-to-payment intelligence API" \
      org.opencontainers.image.source="https://github.com/rokadepiyush49-rgb/HackMatrix-Hackathon" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0"

# libgomp1: OpenMP runtime LightGBM links against. Nothing else is installed. (DL3008: see the models stage.)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 sutra \
    && useradd --system --uid 10001 --gid sutra --home-dir /app --shell /usr/sbin/nologin sutra

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/backend:/app/data/kestrel_sim \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUTRA_LOG_JSON=true \
    SUTRA_SERVICE_VERSION=${VERSION}

WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY --chown=root:root backend backend
COPY --chown=root:root data/kestrel_sim data/kestrel_sim
COPY --chown=root:root data/scenarios data/scenarios
COPY --from=models --chown=10001:10001 /app/ml ml

# Code is owned by root and read-only to the app user; only /tmp (an emptyDir in Kubernetes) is writable.
USER 10001:10001
WORKDIR /app/backend
EXPOSE 8000

# One process per container: Kubernetes scales replicas, so no gunicorn worker pool inside.
# --proxy-headers: rate limits key on the client address in X-Forwarded-For. Only the web pods can reach
# the API (NetworkPolicy), and the web BFF sends exactly one address: the one the ALB saw.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--no-server-header", "--no-access-log", "--timeout-graceful-shutdown", "25"]
