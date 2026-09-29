"use client";

import { Command } from "cmdk";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Banknote, BriefcaseBusiness, History, Landmark, Search, ShieldCheck, Sparkles, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Chip } from "@/components/ui/primitives";
import { api, useAlerts } from "@/lib/api";

import { ALL_ITEMS } from "./nav";
import { useUI } from "./ui-context";

interface Hit {
  id: string;
  kind: string;
  label: string;
  sub: string;
}

export function CommandPalette() {
  const { palette, setPalette, openAsk } = useUI();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const { data: alerts } = useAlerts("", { staleTime: 60_000 });
  // Quick actions follow the flagship insider case when there is one.
  const top = alerts?.find((a) => a.typology === "INSIDER_ATO") ?? alerts?.[0];

  const searching = q.trim().length >= 2;
  const shown = searching ? hits : [];
  useEffect(() => {
    if (!searching) return;
    const t = setTimeout(() => {
      api<Hit[]>(`/entities/search?q=${encodeURIComponent(q.trim())}`).then(setHits).catch(() => setHits([]));
    }, 140);
    return () => clearTimeout(t);
  }, [q, searching]);

  const go = (href: string) => {
    setPalette(false);
    setQ("");
    router.push(href);
  };

  const actions = top
    ? [
        { icon: BriefcaseBusiness, label: `Open case ${top.id}`, hint: top.typology_label, run: () => go(`/cases/${top.id}`) },
        { icon: History, label: "Replay the case at 21:46", hint: "What did the bank know?", run: () => go(`/replay?alert=${top.id}&at=21:46`) },
        { icon: Landmark, label: "Convene the Investigation Council", hint: "8 agents debate the evidence", run: () => go(`/council/${top.id}`) },
        { icon: ShieldCheck, label: "Run control simulation", hint: "What would have stopped it?", run: () => go(`/controls?alert=${top.id}`) },
        { icon: Banknote, label: "Trace money from A-5520", hint: "Money Trail", run: () => go(`/trail?account=A-5520`) },
        { icon: User, label: "Find unexplained accesses", hint: "Alibi Ledger", run: () => go(`/alibi?verdict=UNEXPLAINED`) },
        { icon: Sparkles, label: "Ask SUTRA about this case", hint: "Evidence-grounded", run: () => { setPalette(false); openAsk(top.id); } },
      ]
    : [];

  const hrefFor = (h: Hit) =>
    h.kind === "alert" ? `/cases/${h.id}` : `/entities/${h.id}`;

  return (
    <AnimatePresence>
      {palette && (
        <motion.div
          className="fixed inset-0 z-[90] flex items-start justify-center bg-pastel-ink/30 pt-[12vh] backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setPalette(false)}
        >
          <motion.div
            initial={{ y: -12, scale: 0.98, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={{ y: -8, opacity: 0 }}
            transition={{ type: "spring", stiffness: 520, damping: 38 }}
            className="w-[640px] max-w-[92vw] overflow-hidden rounded-[2rem] bg-raised shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <Command label="Search SUTRA" shouldFilter={false} onKeyDown={(e) => e.key === "Escape" && setPalette(false)}>
              <div className="flex items-center gap-2.5 border-b border-line px-5">
                <Search size={16} className="text-faint" />
                <Command.Input
                  autoFocus
                  value={q}
                  onValueChange={setQ}
                  placeholder="Search employees, accounts, devices, cases… or pick an action"
                  className="h-14 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-faint"
                />
              </div>
              <Command.List className="max-h-[420px] overflow-y-auto p-2">
                <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted">No matches.</Command.Empty>
                {shown.length > 0 && (
                  <Command.Group heading="Entities" className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3.5 [&_[cmdk-group-heading]]:py-1.5">
                    {shown.map((h) => (
                      <Command.Item key={h.kind + h.id} value={h.kind + h.id} onSelect={() => go(hrefFor(h))}
                        className="flex cursor-pointer items-center gap-3 rounded-full px-3.5 py-2 text-[13px] data-[selected=true]:bg-panel-2">
                        <Chip tone={h.kind === "employee" ? "threat" : h.kind === "alert" ? "amber" : "info"}>{h.kind}</Chip>
                        <span className="num text-ink">{h.label}</span>
                        <span className="truncate text-muted">{h.sub}</span>
                        <ArrowRight size={14} className="ml-auto text-faint" />
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                {q.trim().length < 2 && (
                  <>
                    <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3.5 [&_[cmdk-group-heading]]:py-1.5">
                      {actions.map((a) => (
                        <Command.Item key={a.label} value={a.label} onSelect={a.run}
                          className="flex cursor-pointer items-center gap-3 rounded-full px-3.5 py-2 text-[13px] text-ink data-[selected=true]:bg-panel-2">
                          <a.icon size={15} className="text-muted" />
                          <span>{a.label}</span>
                          <span className="ml-auto text-[12px] text-faint">{a.hint}</span>
                        </Command.Item>
                      ))}
                    </Command.Group>
                    <Command.Group heading="Go to" className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-3.5 [&_[cmdk-group-heading]]:py-1.5">
                      {ALL_ITEMS.map((i) => (
                        <Command.Item key={i.href} value={i.label} onSelect={() => go(i.href)}
                          className="flex cursor-pointer items-center gap-3 rounded-full px-3.5 py-1.5 text-[13px] text-ink-2 data-[selected=true]:bg-panel-2">
                          <i.icon size={15} className="text-faint" /> {i.label}
                        </Command.Item>
                      ))}
                    </Command.Group>
                  </>
                )}
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
