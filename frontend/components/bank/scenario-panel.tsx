"use client";

// The one-click testing dashboard: run a predefined situation in the mock bank, ask SUTRA to detect,
// reset. Everything shown is the bank's literal JSON answer or SUTRA's run result.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { bank, BankError } from "./bank-client";
import { Btn, Card, Notice } from "./shell";

interface Scenario { key: string; title: string; what: string; expect: string }
interface RunInfo { id: string; kind: string; finished: boolean; stagesDone: number; result: { verdict?: { headline: string; detail: string } | null; undone?: number; scenarios?: { passed: number; total: number } } | null; newAlerts: { id: string; priority: string; typology: string; claim: string }[] }

export function ScenarioPanel() {
  const qc = useQueryClient();
  const list = useQuery<Scenario[]>({ queryKey: ["bank-scenarios"], queryFn: () => bank<Scenario[]>("test/scenarios") });
  const [last, setLast] = useState<{ title: string; body: unknown; expect?: string } | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = useQuery<RunInfo>({
    queryKey: ["bank-test-run", runId], queryFn: () => bank<RunInfo>(`test/runs/${runId}`), enabled: !!runId,
    refetchInterval: (q) => (q.state.data?.finished ? false : 1500),
    refetchIntervalInBackground: true, // keep following the run while you look at SUTRA in another tab
  });
  const refresh = () => ["bank-activity", "bank-clock"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const call = async (title: string, path: string, expect?: string) => {
    setBusy(true);
    try {
      const body = await bank<unknown>(path, { body: {} });
      setLast({ title, body, expect });
      const id = (body as { runId?: string | null }).runId;
      if (id) setRunId(id);
    } catch (e) {
      setLast({ title, body: { status: "FAILED", message: e instanceof BankError ? e.message : "The bank is not reachable." }, expect });
    } finally {
      setBusy(false);
      refresh();
    }
  };

  return (
    <Card title="Test scenarios" sub="One click each. The bank acts on fixed synthetic accounts; then ask SUTRA to detect.">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {list.data?.map((s) => (
          <button key={s.key} disabled={busy} onClick={() => call(s.title, `test/scenario/${s.key}`, s.expect)}
            className="rounded-md border border-[#c7d0cc] bg-white px-3 py-2 text-left hover:border-[#0f6b50] disabled:opacity-50">
            <span className="block text-[13px] font-semibold">{s.title}</span>
            <span className="block text-[11.5px] text-[#5b6b66]">{s.what}</span>
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Btn disabled={busy} onClick={() => call("Run SUTRA detection", "test/detect")}>Run SUTRA detection</Btn>
        <Btn tone="warn" disabled={busy} onClick={() => call("Reset test data", "test/reset")}>Reset test data</Btn>
      </div>
      {last && (
        <div className="mt-3 flex flex-col gap-2">
          <div className="text-[12.5px] font-semibold">{last.title} · bank response</div>
          <pre className="max-h-[220px] overflow-auto rounded-md bg-[#14211d] p-3 font-mono text-[11.5px] leading-relaxed text-[#d9f2e6]">{JSON.stringify(last.body, null, 2)}</pre>
          {last.expect && <Notice tone="info"><b>What SUTRA should conclude:</b> {last.expect}</Notice>}
        </div>
      )}
      {runId && run.data && (
        <div className="mt-3">
          {!run.data.finished ? (
            <Notice tone="info">SUTRA is working ({run.data.kind === "reset" ? "undoing and re-detecting" : "detecting"}) · {run.data.stagesDone} of 10 stages done…</Notice>
          ) : run.data.kind === "reset" ? (
            <Notice tone="ok">Test data reset: {run.data.result?.undone ?? 0} rows undone, accounts restored, bank clock back to 20:45.</Notice>
          ) : (
            <Notice tone={run.data.newAlerts.length ? "error" : "ok"}>
              <b>{run.data.result?.verdict?.headline ?? "Done"}</b>
              {run.data.newAlerts.map((a) => <span key={a.id} className="block">{a.id} · {a.priority} · {a.typology} · {a.claim}</span>)}
              <span className="block">Open SUTRA → Live Ops → Kestrel Bank for the full chain, signals and Alibi.</span>
            </Notice>
          )}
        </div>
      )}
    </Card>
  );
}
