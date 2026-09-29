"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { useAlerts } from "@/lib/api";

/** One URL query parameter as state. Callers must sit inside a <Suspense> boundary. */
export function useParam(name: string): [string | null, (v: string | null) => void] {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const set = useCallback(
    (v: string | null) => {
      const p = new URLSearchParams(sp.toString());
      if (v === null || v === "") p.delete(name);
      else p.set(name, v);
      const q = p.toString();
      router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
    },
    [sp, router, pathname, name],
  );
  return [sp.get(name), set];
}

/** `?alert=` for workbench pages; defaults to the first alert of `prefer` typology, else the top of the queue. */
export function useAlertParam(prefer?: string): [string | undefined, (v: string) => void] {
  const [alert, setAlert] = useParam("alert");
  const { data } = useAlerts();
  const fallback = (prefer && data?.find((a) => a.typology === prefer)) || data?.[0];
  return [alert ?? fallback?.id, (v) => setAlert(v)];
}
