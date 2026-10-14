import "server-only";

import { cookies, headers } from "next/headers";

export const API = process.env.SUTRA_API_URL ?? "http://127.0.0.1:8000";
export const ACCESS = "sutra_at";
export const REFRESH = "sutra_rt";

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const base = { httpOnly: true, sameSite: "lax" as const, path: "/", secure: process.env.NODE_ENV === "production" };

/**
 * The browser's address, for the API's per-client rate limits (sign-in especially). Every API call
 * comes from this server, so without it all users would share one limit. The load balancer appends
 * the address it saw to X-Forwarded-For; earlier entries are whatever the client sent, so only the
 * last one is trusted, and it is passed on alone.
 */
export async function clientHeaders(): Promise<Record<string, string>> {
  const xff = (await headers()).get("x-forwarded-for");
  const ip = xff?.split(",").pop()?.trim();
  return ip ? { "X-Forwarded-For": ip } : {};
}

export async function storeTokens(t: Tokens) {
  const jar = await cookies();
  jar.set(ACCESS, t.access_token, { ...base, maxAge: t.expires_in });
  jar.set(REFRESH, t.refresh_token, { ...base, maxAge: 60 * 60 * 12 });
}

export async function clearTokens() {
  const jar = await cookies();
  jar.delete(ACCESS);
  jar.delete(REFRESH);
}

export async function refresh(): Promise<Tokens | null> {
  const jar = await cookies();
  const rt = jar.get(REFRESH)?.value;
  if (!rt) return null;
  const res = await fetch(`${API}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await clientHeaders()) },
    body: JSON.stringify({ refresh_token: rt }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const t = (await res.json()) as Tokens;
  await storeTokens(t);
  return t;
}
