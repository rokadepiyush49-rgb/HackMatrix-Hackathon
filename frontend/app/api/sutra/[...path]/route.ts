import { cookies } from "next/headers";

import { ACCESS, API, refresh } from "@/lib/server/session";

// Backend-for-frontend pass-through: attaches the httpOnly access token, refreshes it once on
// 401, and streams the upstream body back unchanged (JSON, PDFs and Server-Sent Events alike).

async function forward(request: Request, ctx: RouteContext<"/api/sutra/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  if (path[0] === "auth" && path[1] === "login") {
    return Response.json({ detail: "Use /api/session to sign in" }, { status: 400 });
  }
  const url = new URL(request.url);
  const target = `${API}/api/v1/${path.map(encodeURIComponent).join("/")}${url.search}`;
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();

  const send = async (token?: string) =>
    fetch(target, {
      method: request.method,
      headers: {
        "Content-Type": request.headers.get("content-type") ?? "application/json",
        Accept: request.headers.get("accept") ?? "*/*",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
      cache: "no-store",
    });

  const jar = await cookies();
  let upstream: Response;
  try {
    upstream = await send(jar.get(ACCESS)?.value);
    if (upstream.status === 401) {
      const t = await refresh();
      if (t) upstream = await send(t.access_token);
    }
  } catch {
    return Response.json({ detail: "The SUTRA API is not reachable. Start it with `make api`." }, { status: 502 });
  }

  const headers = new Headers();
  for (const h of ["content-type", "content-disposition", "cache-control"]) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  if ((headers.get("content-type") ?? "").includes("text/event-stream")) {
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("X-Accel-Buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;
