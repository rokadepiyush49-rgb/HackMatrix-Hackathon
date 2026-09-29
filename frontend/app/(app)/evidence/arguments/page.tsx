"use client";

import { Landmark } from "lucide-react";
import { Suspense } from "react";

import { ProsecutionDefence, WhySuspicious } from "@/components/brief/brief";
import { AlertPicker } from "@/components/chain/alert-bits";
import { AgentAvatar } from "@/components/council/council";
import { ButtonLink, Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useAlert, useCouncil } from "@/lib/api";
import { useAlertParam } from "@/lib/params";

function Arguments() {
  const [alertId, setAlert] = useAlertParam("INSIDER_ATO");
  const { data: a, error } = useAlert(alertId);
  const { data: c } = useCouncil(alertId);

  return (
    <div className="mx-auto max-w-[1500px] p-5">
      <PageHeader eyebrow="Evidence · Prosecution & Defence" title="The case for, the case against"
        sub="Every alert carries its own argument: the claim, the grounds with evidence codes, the warrant that links them — and the innocent explanations SUTRA tried to prove before calling anything suspicious."
        right={<><AlertPicker value={alertId} onChange={setAlert} />{alertId && <ButtonLink variant="ai" href={`/council/${alertId}`}><Landmark size={14} /> Council</ButtonLink>}</>} />
      {error && <ErrorBox error={error} />}
      {!a && !error && <Skeleton className="h-[480px]" />}
      {a && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <Panel className="p-4"><ProsecutionDefence a={a} /></Panel>
          <div className="space-y-4">
            <Panel className="p-4"><WhySuspicious a={a} /></Panel>
            {c && (
              <Panel>
                <PanelHead eyebrow="Council ruling" title={c.consensus.outcome} />
                <div className="space-y-2 px-4 pb-4">
                  <p className="text-[12px] text-muted">Links supported by records: <b className="num text-ink">{c.consensus.links_supported}</b></p>
                  {c.consensus.dissent.map((d) => {
                    const ag = c.agents.find((x) => x.id === d.agent);
                    return (
                      <div key={d.agent} className="flex gap-2 rounded-md border border-amber/30 bg-amber-soft/30 p-2.5">
                        {ag && <AgentAvatar agent={ag} size={26} />}
                        <div><div className="flex items-center gap-1.5 text-[12px] font-semibold text-ink">{ag?.name} <Chip tone="amber">dissent</Chip></div><p className="text-[12px] text-ink-2">{d.reason}</p></div>
                      </div>
                    );
                  })}
                </div>
              </Panel>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ArgumentsPage() {
  return <Suspense fallback={<div className="p-5"><Skeleton className="h-[480px]" /></div>}><Arguments /></Suspense>;
}
