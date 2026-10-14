# syntax=docker/dockerfile:1.10
# SUTRA investigator app (Next.js standalone server, which is also the BFF that holds sessions).
#
# The runtime is distroless: no shell, no package manager, no npm — only Node and the traced files
# `next build` says the server needs. That removes most of what an attacker could use after an RCE.

ARG NODE_VERSION=22

# ── deps ────────────────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-bookworm-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# ── build ───────────────────────────────────────────────────────────────────
FROM deps AS build
COPY frontend/ .
ENV NEXT_TELEMETRY_DISABLED=1 NODE_ENV=production
RUN npm run build

# ── runtime ─────────────────────────────────────────────────────────────────
FROM gcr.io/distroless/nodejs${NODE_VERSION}-debian12:nonroot AS runtime
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="sutra-web" \
      org.opencontainers.image.description="SUTRA investigator app and session BFF" \
      org.opencontainers.image.source="https://github.com/rokadepiyush49-rgb/HackMatrix-Hackathon" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

# Distroless "nonroot", given by number so runtimes can verify it is not root.
USER 65532:65532
EXPOSE 3000
CMD ["server.js"]
