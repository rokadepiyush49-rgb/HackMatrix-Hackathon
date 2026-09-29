"use client";

import { motion } from "motion/react";
import { Landmark, Smartphone, UserCog, Users, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { EntitySearch } from "@/components/graph/entity-search";
import { PageHeader, Panel, PanelHead, PriorityPill, Skeleton } from "@/components/ui/primitives";
import { useAlerts } from "@/lib/api";
import type { Priority } from "@/lib/types";

const GROUPS = [
  { key: "EMP-", title: "Employees", icon: UserCog, note: "pseudonymous — role and branch only" },
  { key: "A-", title: "Accounts at Kestrel UCB", icon: Wallet, note: "victims, mules and consolidators" },
  { key: "X-", title: "External accounts", icon: Landmark, note: "other banks, ATM network, exits" },
  { key: "C-", title: "Customers", icon: Users, note: "" },
  { key: "D-", title: "Devices", icon: Smartphone, note: "" },
];
const RANK: Record<string, number> = { P1: 0, P2: 1, P3: 2, WATCH: 3, EXPLAINED: 4 };

export default function EntityExplorer() {
  const router = useRouter();
  const { data: alerts } = useAlerts();
  const seen = new Map<string, { p: Priority; alerts: string[] }>();
  alerts?.forEach((a) => a.entity_refs.forEach((e) => {
    const cur = seen.get(e);
    if (!cur) seen.set(e, { p: a.priority, alerts: [a.id] });
    else { cur.alerts.push(a.id); if (RANK[a.priority] < RANK[cur.p]) cur.p = a.priority; }
  }));

  return (
    <div className="mx-auto max-w-[1400px] p-5">
      <PageHeader eyebrow="Investigate · Entity Explorer" title="Every person, account and device on one page"
        sub="Open a dossier for anything in the graph — its rhythm, privileges, alibis, money and the chains it sits in." />
      <Panel className="mb-4 p-4">
        <EntitySearch className="sm:w-[520px]" onPick={(h) => router.push(h.kind === "alert" ? `/cases/${h.id}` : `/entities/${h.id}`)} />
        <p className="mt-2 text-[11.5px] text-faint">Try EMP-0417, A-5520, RK Traders or D-9F2.</p>
      </Panel>
      {!alerts && <Skeleton className="h-64" />}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {GROUPS.map((g) => {
          const items = [...seen.entries()].filter(([id]) => id.startsWith(g.key)).sort((a, b) => RANK[a[1].p] - RANK[b[1].p] || b[1].alerts.length - a[1].alerts.length);
          if (!items.length) return null;
          return (
            <Panel key={g.key}>
              <PanelHead eyebrow={`In active chains · ${items.length}`} title={<span className="flex items-center gap-2"><g.icon size={15} className="text-muted" />{g.title}</span>}
                right={g.note && <span className="text-[11px] text-faint">{g.note}</span>} />
              <div className="grid gap-1.5 px-3 pb-3 sm:grid-cols-2">
                {items.slice(0, 16).map(([id, v], i) => (
                  <motion.div key={id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.02 }}>
                    <Link href={`/entities/${id}`} className="flex items-center gap-2 rounded-md border border-line px-2.5 py-2 hover:border-line-strong hover:bg-panel-2">
                      <span className="num text-[12.5px] text-ink">{id}</span>
                      <span className="ml-auto"><PriorityPill p={v.p} /></span>
                      {v.alerts.length > 1 && <span className="num text-[10.5px] text-faint">×{v.alerts.length}</span>}
                    </Link>
                  </motion.div>
                ))}
              </div>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}
