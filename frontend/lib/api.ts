"use client";

// Browser-side API client. Every call goes through the Next.js BFF at /api/sutra/*, which
// attaches the httpOnly session token server-side — the browser never holds a JWT.

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import type {
  AlertDetail,
  AlertSummary,
  AskAnswer,
  CaseFile,
  Council,
  Me,
  Mend,
  Overview,
  Replay,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/sutra${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth")) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

type Opts<T> = Omit<UseQueryOptions<T, ApiError>, "queryKey" | "queryFn">;

export const useMe = () => useQuery<Me, ApiError>({ queryKey: ["me"], queryFn: () => api("/auth/me"), staleTime: 60_000 });
export const useOverview = (o?: Opts<Overview>) =>
  useQuery<Overview, ApiError>({ queryKey: ["overview"], queryFn: () => api("/overview"), ...o });
export const useAlerts = (params = "", o?: Opts<AlertSummary[]>) =>
  useQuery<AlertSummary[], ApiError>({ queryKey: ["alerts", params], queryFn: () => api(`/alerts${params}`), ...o });
export const useAlert = (id?: string) =>
  useQuery<AlertDetail, ApiError>({ queryKey: ["alert", id], queryFn: () => api(`/alerts/${id}`), enabled: !!id });
export const useReplay = (id?: string) =>
  useQuery<Replay, ApiError>({ queryKey: ["replay", id], queryFn: () => api(`/replay/${id}`), enabled: !!id });
export const useCouncil = (id?: string) =>
  useQuery<Council, ApiError>({ queryKey: ["council", id], queryFn: () => api(`/council/${id}`), enabled: !!id, staleTime: Infinity });
export const useMend = (id?: string, controls: string[] = []) =>
  useQuery<Mend, ApiError>({
    queryKey: ["mend", id, controls.join(",")],
    queryFn: () => api(`/mend/${id}?${controls.map((c) => `controls=${c}`).join("&")}`),
    enabled: !!id,
    placeholderData: (prev) => prev,
  });
export const useCases = () => useQuery<CaseFile[], ApiError>({ queryKey: ["cases"], queryFn: () => api("/cases") });

export function useGet<T>(key: unknown[], path: string | null, o?: Opts<T>) {
  return useQuery<T, ApiError>({ queryKey: key, queryFn: () => api<T>(path as string), enabled: !!path, ...o });
}

export function useAsk() {
  return useMutation<AskAnswer, ApiError, { alert_id: string; question: string }>({
    mutationFn: (body) => api("/copilot/ask", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useOpenCase() {
  const qc = useQueryClient();
  return useMutation<CaseFile, ApiError, string>({
    mutationFn: (alert_id) => api("/cases", { method: "POST", body: JSON.stringify({ alert_id }) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}

export function usePost<TBody, TOut>(path: string, invalidate: unknown[][] = []) {
  const qc = useQueryClient();
  return useMutation<TOut, ApiError, TBody>({
    mutationFn: (body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k })),
  });
}
