# 001 — FastAPI modular monolith

**Context.** Detection, ML and the API all need the same domain models (events, chains,
evidence). A hackathon team has limited time; judges reward clarity over service count.

**Decision.** One Python service (`backend/app`) with hard module boundaries:
`loom` (data + graph queries), `needle` (detectors + chain assembly), `alibi`,
`brief`, `mend`, `copilot`, `api`. Modules talk through plain function calls and
typed dataclasses, never through each other's tables directly (except via `loom`).

**Consequences.** One deployable, one set of Pydantic models → one OpenAPI schema →
one generated TypeScript client. Scale-out path (see `docs/scalability.md`): `needle`
becomes a stream processor keyed by account; `api` scales horizontally unchanged.
