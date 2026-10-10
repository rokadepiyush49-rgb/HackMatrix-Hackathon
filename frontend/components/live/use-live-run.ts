"use client";

// One live run (feed, your input, or a reset) as React state, fed by the API's Server-Sent Events.
// The server keeps every run's events, so attaching late — or after a page reload — replays the
// whole run from its `start` event and lands on exactly the same state.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef } from "react";

import { api, ApiError } from "@/lib/api";
import type { ComposeSpec, LiveAlert, LiveAlibi, LiveFeedRow, LiveResult, LiveScope, LiveSignal, LiveStage, StageStatus } from "@/lib/types";

export type Phase = "idle" | "connecting" | "streaming" | "detecting" | "done" | "cancelled" | "error";

export interface StageState { status: StageStatus; detail: string | null; elapsed: number | null }

export interface RunState {
  runId: string | null;
  kind: "feed" | "reset" | null;
  scope: LiveScope | null;
  startedAt: string | null;
  phase: Phase;
  total: number;
  speed: number;
  stages: LiveStage[];
  progress: Record<string, StageState>;
  events: LiveFeedRow[];
  clock: string | null;
  alerts: LiveAlert[];
  alibi: LiveAlibi[];
  signals: LiveSignal[];
  result: LiveResult | null;
  error: string | null;
}

export const idleRun: RunState = {
  runId: null, kind: null, scope: null, startedAt: null, phase: "idle", total: 0, speed: 0, stages: [], progress: {},
  events: [], clock: null, alerts: [], alibi: [], signals: [], result: null, error: null,
};

type StartData = { run: string; kind: "feed" | "reset"; scope?: LiveScope; started_at: string; total?: number; speed?: number; stages: LiveStage[] };

type Action =
  | { type: "attach"; runId: string }
  | { type: "start"; data: StartData }
  | { type: "event"; data: LiveFeedRow }
  | { type: "stage"; data: { key: string; status: StageStatus; detail: string | null; elapsed: number } }
  | { type: "alert"; data: LiveAlert }
  | { type: "alibi"; data: LiveAlibi }
  | { type: "signal"; data: LiveSignal }
  | { type: "done"; data: LiveResult }
  | { type: "cancelled" }
  | { type: "error"; message: string };

function reducer(s: RunState, a: Action): RunState {
  switch (a.type) {
    case "attach":
      return { ...idleRun, runId: a.runId, phase: "connecting" };
    case "start":
      return {
        ...idleRun, runId: a.data.run, kind: a.data.kind, scope: a.data.scope ?? "evening", startedAt: a.data.started_at,
        phase: a.data.kind === "feed" ? "streaming" : "detecting",
        total: a.data.total ?? 0, speed: a.data.speed ?? 0, stages: a.data.stages,
        progress: Object.fromEntries(a.data.stages.map((st) => [st.key, { status: "pending", detail: null, elapsed: null }])),
      };
    case "event":
      return { ...s, events: [...s.events, a.data], clock: a.data.t };
    case "stage": {
      const progress = { ...s.progress, [a.data.key]: { status: a.data.status, detail: a.data.detail, elapsed: a.data.elapsed } };
      const phase = s.kind === "feed" && a.data.key !== "ingest" ? "detecting" : s.phase;
      return { ...s, progress, phase };
    }
    case "alert":
      return { ...s, alerts: [...s.alerts.filter((x) => x.id !== a.data.id), a.data] };
    case "alibi":
      return { ...s, alibi: [...s.alibi.filter((x) => x.ref !== a.data.ref), a.data] };
    case "signal":
      return { ...s, signals: [...s.signals, a.data] };
    case "done":
      return { ...s, phase: "done", result: a.data };
    case "cancelled":
      return { ...s, phase: "cancelled" };
    case "error":
      return { ...s, phase: "error", error: a.message };
  }
}

export interface LiveHandlers {
  onEvent?: (row: LiveFeedRow) => void;
  onAlert?: (alert: LiveAlert) => void;
  onDone?: (result: LiveResult, kind: "feed" | "reset" | null, scope: LiveScope | null) => void;
}

export function useLiveRun(handlers: LiveHandlers = {}) {
  const [state, dispatch] = useReducer(reducer, idleRun);
  const es = useRef<EventSource | null>(null);
  const qc = useQueryClient();
  const live = useRef(handlers);
  useEffect(() => {
    live.current = handlers;
  });
  const meta = useRef<{ kind: "feed" | "reset" | null; scope: LiveScope | null }>({ kind: null, scope: null });

  const close = useCallback(() => {
    es.current?.close();
    es.current = null;
  }, []);

  const attach = useCallback((runId: string) => {
    close();
    dispatch({ type: "attach", runId });
    const src = new EventSource(`/api/sutra/live/runs/${runId}/events`);
    es.current = src;
    const on = <T,>(name: string, fn: (d: T) => void) =>
      src.addEventListener(name, (e) => fn(JSON.parse((e as MessageEvent).data) as T));
    on<StartData>("start", (d) => {
      meta.current = { kind: d.kind, scope: d.scope ?? "evening" };
      dispatch({ type: "start", data: d });
    });
    on<LiveFeedRow>("event", (d) => {
      dispatch({ type: "event", data: d });
      live.current.onEvent?.(d);
    });
    on<Extract<Action, { type: "stage" }>["data"]>("stage", (d) => dispatch({ type: "stage", data: d }));
    on<LiveAlert>("alert", (d) => {
      dispatch({ type: "alert", data: d });
      live.current.onAlert?.(d);
    });
    on<LiveAlibi>("alibi", (d) => dispatch({ type: "alibi", data: d }));
    on<LiveSignal>("signal", (d) => dispatch({ type: "signal", data: d }));
    on<LiveResult>("done", (d) => {
      dispatch({ type: "done", data: d });
      live.current.onDone?.(d, meta.current.kind, meta.current.scope);
      // every screen that reads alerts, cases or the lab is now stale
      qc.invalidateQueries();
    });
    // "failed" is the server saying the run broke; a bare "error" event is the connection dropping.
    on<{ message: string }>("failed", (d) => dispatch({ type: "error", message: d.message }));
    on("cancelled", () => dispatch({ type: "cancelled" }));
    on("end", () => close());
    src.onerror = () => {
      // The browser retries on its own (resuming from Last-Event-ID); give up only if the run is gone.
      if (src.readyState === EventSource.CLOSED) dispatch({ type: "error", message: "Lost the connection to the run." });
    };
  }, [close, qc]);

  useEffect(() => close, [close]);

  const start = useCallback(async (speed: number) => {
    const r = await api<{ run_id: string }>("/live/runs", { method: "POST", body: JSON.stringify({ speed, detect: true }) });
    attach(r.run_id);
  }, [attach]);

  const compose = useCallback(async (spec: ComposeSpec, speed: number) => {
    const r = await api<{ run_id: string }>("/live/compose", { method: "POST", body: JSON.stringify({ ...spec, speed }) });
    attach(r.run_id);
  }, [attach]);

  const detectBank = useCallback(async () => {
    const r = await api<{ run_id: string }>("/live/detect", { method: "POST", body: "{}" });
    attach(r.run_id);
  }, [attach]);

  const reset = useCallback(async (scope: "all" | "yours" | "bank" = "all") => {
    const r = await api<{ run_id: string }>(`/live/reset?scope=${scope}`, { method: "POST", body: "{}" });
    attach(r.run_id);
  }, [attach]);

  const cancel = useCallback(async () => {
    if (state.runId) await api(`/live/runs/${state.runId}/cancel`, { method: "POST", body: "{}" }).catch((e: ApiError) => e);
  }, [state.runId]);

  return { state, attach, start, compose, detectBank, reset, cancel };
}
