import { API } from "@/lib/server/session";

// Pass-through for Kestrel Bank, the mock bank used to test SUTRA by hand. The bank is a separate
// system from SUTRA: no SUTRA session is attached here, only the bank's own session header.

async function forward(request: Request, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const url = new URL(request.url);
  const target = `${API}/api/v1/bank/${path.map(encodeURIComponent).join("/")}${url.search}`;
  const token = request.headers.get("x-bank-token");
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: { "Content-Type": "application/json", ...(token ? { "X-Bank-Token": token } : {}) },
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "The bank's systems are not reachable. Start the API with `make api`." }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
  });
}

export const GET = forward;
export const POST = forward;
