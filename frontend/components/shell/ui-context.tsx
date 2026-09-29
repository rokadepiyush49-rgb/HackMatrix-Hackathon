"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { EvidenceItem } from "@/lib/types";

interface UIState {
  evidence: { item: EvidenceItem; pool: EvidenceItem[] } | null;
  openEvidence: (code: string, pool: EvidenceItem[]) => void;
  closeEvidence: () => void;
  ask: { alertId: string; question?: string } | null;
  openAsk: (alertId: string, question?: string) => void;
  closeAsk: () => void;
  palette: boolean;
  setPalette: (v: boolean) => void;
  focusAlert: string | null;
  setFocusAlert: (id: string | null) => void;
}

const Ctx = createContext<UIState | null>(null);

export function UIProvider({ children }: { children: ReactNode }) {
  const [evidence, setEvidence] = useState<UIState["evidence"]>(null);
  const [ask, setAsk] = useState<UIState["ask"]>(null);
  const [palette, setPalette] = useState(false);
  const [focusAlert, setFocusAlert] = useState<string | null>(null);

  const openEvidence = useCallback((code: string, pool: EvidenceItem[]) => {
    const item = pool.find((e) => e.code === code);
    if (item) setEvidence({ item, pool });
  }, []);

  const value = useMemo<UIState>(
    () => ({
      evidence, openEvidence, closeEvidence: () => setEvidence(null),
      ask, openAsk: (alertId, question) => setAsk({ alertId, question }), closeAsk: () => setAsk(null),
      palette, setPalette, focusAlert, setFocusAlert,
    }),
    [evidence, openEvidence, ask, palette, focusAlert],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useUI() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useUI outside UIProvider");
  return v;
}
