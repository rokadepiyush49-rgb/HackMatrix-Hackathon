# 008 — Signed, minimal, reproducible container images

**Context.** A bank's vendor-risk review asks three questions of every deployable: what is in it,
who built it, and can it be tampered with between build and run? Default Docker images run as
root, carry shells and compilers, and can be pushed by anyone with registry credentials.

**Decision.**
- Multi-stage builds: dependencies resolved from lockfiles (`uv.lock`, `package-lock.json`); models
  trained in a build stage from code + seed; the runtime stage holds no build tools.
- API on `python:3.12-slim` as UID 10001; web on **distroless** Node (`:nonroot`) — no shell.
- Read-only root filesystem, all capabilities dropped, `/tmp` as the only writable path.
- Built only by GitHub Actions for `linux/amd64` and `linux/arm64`; pushed to ECR with immutable tags.
- Every image gets an SPDX SBOM, SLSA build provenance and a **Sigstore cosign keyless** signature
  bound to the release workflow's OIDC identity. Kyverno rejects any image without that signature.
- Deployments reference images by **digest**, promoted from staging to prod by pull request.

**Consequences.** "What is running in prod?" has an exact, verifiable answer. A stolen registry
credential can't get an unsigned image scheduled. Debugging uses ephemeral debug containers,
since the web image has no shell.
