import { API, clearTokens, storeTokens, type Tokens } from "@/lib/server/session";

// POST /api/session  { username, password } — or { username, demo: true } in local demo mode,
// where the seeded demo password is read from the server environment (never sent to the browser).
export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as { username?: string; password?: string; demo?: boolean };
  const demoMode = process.env.SUTRA_DEMO_MODE === "true";
  const password = body.demo && demoMode ? process.env.SUTRA_DEMO_PASSWORD ?? "" : body.password ?? "";
  if (!body.username || !password) {
    return Response.json({ detail: "Enter a username and password" }, { status: 400 });
  }
  const res = await fetch(`${API}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: body.username, password }),
    cache: "no-store",
  }).catch(() => null);
  if (!res) return Response.json({ detail: "The SUTRA API is not reachable. Start it with `make api`." }, { status: 502 });
  if (!res.ok) return Response.json(await res.json().catch(() => ({ detail: "Sign-in failed" })), { status: res.status });
  await storeTokens((await res.json()) as Tokens);
  return Response.json({ ok: true });
}

export async function DELETE() {
  await clearTokens();
  return Response.json({ ok: true });
}
