// OpenTelemetry for the BFF: traces every server request and the upstream fetch to the SUTRA API,
// so one trace spans browser → Next → FastAPI → Postgres. Off unless an OTLP endpoint is configured.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs" && process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
    const { registerOTel } = await import("@vercel/otel");
    registerOTel({ serviceName: process.env.OTEL_SERVICE_NAME ?? "sutra-web" });
  }
}
