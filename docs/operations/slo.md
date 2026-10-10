# Service level objectives

Measured over 28 days. Error budgets gate releases: if a budget is exhausted, only reliability
fixes ship until it recovers.

| SLO | Target | Indicator |
|---|---|---|
| Investigator app availability | 99.9 % | Share of `/api/sutra/*` requests at the ALB answered without a 5xx |
| API latency | p95 < 400 ms, p99 < 1.5 s | FastAPI server spans (excluding `/council` and pack generation) |
| Evidence pack generation | p95 < 10 s | `POST /cases/{id}/packs` span duration |
| Detection freshness | New events argued within 20 min | Time from event ingest to the detection run that covered it (CronJob every 15 min) |
| Audit chain integrity | 100 % | `/governance/audit` verification `ok` — any break pages immediately |
