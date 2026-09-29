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
