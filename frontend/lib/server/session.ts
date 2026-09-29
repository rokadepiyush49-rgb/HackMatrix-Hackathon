import "server-only";

import { cookies } from "next/headers";

export const API = process.env.SUTRA_API_URL ?? "http://127.0.0.1:8000";
export const ACCESS = "sutra_at";
export const REFRESH = "sutra_rt";

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const base = { httpOnly: true, sameSite: "lax" as const, path: "/", secure: process.env.NODE_ENV === "production" };

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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  const t = (await res.json()) as Tokens;
  await storeTokens(t);
  return t;
}
