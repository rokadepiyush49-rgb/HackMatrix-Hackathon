# 013 — OpenTelemetry, structured logs and request IDs

**Context.** An investigator reports "the case page hung at 22:10". We need to find that exact
request across the BFF, the API and the database without logging personal data.

**Decision.** OpenTelemetry SDKs in the API (FastAPI + SQLAlchemy instrumentation) and the BFF
(Next.js `instrumentation.ts`), exporting OTLP to a collector that **deletes auth headers, cookies
and query strings** before forwarding to X-Ray / Amazon Managed Prometheus. JSON logs with an
`X-Request-ID` on every line, echoed to the client. Liveness and readiness are separate endpoints.
Telemetry is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set, so tests and laptops pay nothing.

**Consequences.** Vendor-neutral: switching to Grafana Tempo or Datadog is a collector change.
