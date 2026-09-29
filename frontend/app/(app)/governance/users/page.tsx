"use client";

import { motion } from "motion/react";
import { Check, Minus } from "lucide-react";

import { Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton } from "@/components/ui/primitives";
import { useGet, useMe } from "@/lib/api";
import { cn } from "@/lib/format";

interface Users { users: { id: string; name: string; role: string; title: string; capabilities: string[] }[]; roles: Record<string, string[]> }

const CAP_LABEL: Record<string, string> = {
  "alerts:read": "See alerts", "alerts:triage": "Triage alerts", "cases:read": "Read cases", "cases:propose": "Propose a decision",
  "cases:review": "Approve a decision (four-eyes)", "packs:create": "Generate evidence packs", "packs:lock": "Lock packs",
  "copilot:use": "Ask SUTRA", "str:draft": "Draft STRs", "mend:use": "Control Lab", "unmask:request": "Request an unmask",
  "unmask:approve": "Approve an unmask", "alibi:review": "Review Alibi", "audit:read": "Read the audit trail",
  "pipeline:run": "Run the pipeline", "users:manage": "Manage users",
};

export default function UsersRoles() {
  const { data, error } = useGet<Users>(["gov-users"], "/governance/users");
  const { data: me } = useMe();
  const caps = [...new Set(Object.values(data?.roles ?? {}).flat())].sort();
  const roles = Object.keys(data?.roles ?? {});

  return (
    <div className="mx-auto max-w-[1500px] p-5">
      <PageHeader eyebrow="Governance · Users & Roles" title="Least privilege, enforced by the API"
        sub="Capabilities are checked on every request, not hidden in the interface. Nobody can both propose and approve the same decision, or request and approve the same unmask." />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Skeleton className="h-96" />}
      {data && (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {data.users.map((u, i) => (
              <motion.div key={u.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
                <Panel className={cn("h-full p-3.5", me?.id === u.id && "ring-1 ring-info/50")}>
                  <div className="flex items-center gap-2">
                    <span className="grid size-8 place-items-center rounded-full bg-panel-2 text-[11px] font-semibold text-ink">{u.name.split(" ").map((x) => x[0]).join("").slice(0, 2)}</span>
                    <div className="min-w-0"><div className="truncate text-[13px] font-semibold text-ink">{u.name}</div><div className="truncate text-[11px] text-muted">{u.title}</div></div>
                    {me?.id === u.id && <Chip tone="info" className="ml-auto">you</Chip>}
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[11px]"><Chip tone="faint">{u.role.replaceAll("_", " ")}</Chip><span className="num text-faint">{u.capabilities.length} capabilities</span></div>
                </Panel>
              </motion.div>
            ))}
          </div>
          <Panel className="overflow-hidden">
            <PanelHead eyebrow="Capability matrix" title="What each role can do" />
            <div className="overflow-x-auto px-4 pb-4">
              <table className="w-full min-w-[900px] text-[12px]">
                <thead><tr className="border-b border-line">
                  <th className="py-2 text-left eyebrow">Capability</th>
                  {roles.map((r) => <th key={r} className="px-2 py-2 text-center eyebrow">{r.replaceAll("_", " ")}</th>)}
                </tr></thead>
                <tbody>
                  {caps.map((c) => (
                    <tr key={c} className="border-b border-line last:border-0 hover:bg-panel-2">
                      <td className="py-1.5 text-ink">{CAP_LABEL[c] ?? c} <span className="num ml-1 text-[10.5px] text-faint">{c}</span></td>
                      {roles.map((r) => (
                        <td key={r} className="px-2 py-1.5 text-center">
                          {data.roles[r].includes(c) ? <Check size={14} className="mx-auto text-ok" /> : <Minus size={12} className="mx-auto text-line-strong" />}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
