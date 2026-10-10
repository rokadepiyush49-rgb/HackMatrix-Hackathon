// Liveness for the web tier. Deliberately does not call the API: a slow backend must not get
// healthy web pods restarted. Readiness of the whole stack is the API's /health/ready.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok", service: "sutra-web" }, { headers: { "Cache-Control": "no-store" } });
}
