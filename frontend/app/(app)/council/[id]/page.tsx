"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight, FastForward, FileQuestion, Gavel, Pause, Play, RotateCcw, ShieldAlert, Sparkles, UserCheck } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AlertPicker } from "@/components/chain/alert-bits";
import { AgentAvatar, Chamber, ClaimRow, Entry, STATUS_TONE, TallyBar, stanceOf } from "@/components/council/council";
import { Button, Chip, ErrorBox, PageHeader, Panel, PanelHead, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { useAlert, useCouncil } from "@/lib/api";
import { cn } from "@/lib/format";
import type { Council, CouncilEntry } from "@/lib/types";

const SPEEDS = [1, 2, 4];

function useDebate(c?: Council) {
  const reduce = useReducedMotion();
  const flat = useMemo(
    () => (c ? c.rounds.flatMap((r) => r.entries.map((e, i) => ({ e, round: r, first: i === 0 }))) : []),
    [c],
  );
  const [shown, setShown] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    if (!flat.length) return;
    if (reduce) { setShown(flat.length); setPlaying(false); return; }
    if (!playing || shown >= flat.length) return;
    const prev = flat[shown - 1]?.e;
    const base = prev?.kind === "RETRIEVAL" ? 1500 : prev?.kind === "RULING" ? 1600 : 1100;
    const t = setTimeout(() => setShown((s) => s + 1), shown === 0 ? 500 : base / speed);
    return () => clearTimeout(t);
  }, [flat, shown, playing, speed, reduce]);

  useEffect(() => { if (shown >= flat.length && flat.length) setPlaying(false); }, [shown, flat.length]);

  return {
    flat, shown, playing, speed,
    done: flat.length > 0 && shown >= flat.length,
    current: (flat[shown - 1]?.e ?? null) as CouncilEntry | null,
    toggle: () => { if (shown >= flat.length) setShown(0); setPlaying((p) => !p || shown >= flat.length); },
    skip: () => { setShown(flat.length); setPlaying(false); },
    restart: () => { setShown(0); setPlaying(true); },
    cycleSpeed: () => setSpeed((s) => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length]),
  };
}

export default function CouncilRoom() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: c, error, isLoading } = useCouncil(id);
  const { data: alert } = useAlert(id);
  const pool = alert?.evidence ?? [];
  const d = useDebate(c);
  const [picked, setPicked] = useState<string | null>(null);
  const [claimFilter, setClaimFilter] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scroller.current;
    if (el && d.playing) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [d.shown, d.playing]);

  const pickedAgent = c?.agents.find((a) => a.id === picked);
  const visible = d.flat.slice(0, d.shown).filter(({ e }) => !picked || e.speaker === picked || e.target === picked);

  return (
    <div className="mx-auto max-w-[1600px] p-5">
      <PageHeader
        eyebrow={`Council · Investigation Council · ${id}`}
        title="Evidence War Room"
        sub="Eight agents argue the same case from the same evidence. They can ask for records; the moderator retrieves them or says they are not ingested. No agent scores or closes the case — the council hands a structured finding to a human."
        right={<>
          <AlertPicker value={id} onChange={(v) => router.push(`/council/${v}`)} />
          <Button variant="primary" onClick={() => router.push(`/cases/${id}`)}>Open case <ArrowRight size={14} /></Button>
        </>}
      />
      {error && <ErrorBox error={error} />}
      {isLoading && <div className="grid gap-4 xl:grid-cols-2"><Skeleton className="h-[460px]" /><Skeleton className="h-[460px]" /></div>}

      {c && (
        <>
          {/* Stats + playback controls */}
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {[["agents", c.stats.agents], ["evidence items", c.stats.evidence], ["rounds", c.stats.rounds], ["record requests", c.stats.requests], ["exchanges", c.stats.entries]].map(([k, v]) => (
              <span key={k} className="rounded-md border border-line bg-panel px-2.5 py-1 text-[12px] text-muted"><b className="num mr-1 text-ink">{v}</b>{k}</span>
            ))}
            <span className="rounded-md border border-ai/30 bg-ai-soft px-2.5 py-1 text-[12px] text-ai">No confidence score — every claim carries a status</span>
            <div className="ml-auto flex items-center gap-1.5">
              <span className="num mr-1 text-[11.5px] text-faint">{d.shown}/{d.flat.length}</span>
              <Button size="sm" variant="outline" onClick={d.toggle}>{d.playing ? <><Pause size={13} /> Pause</> : <><Play size={13} /> {d.done ? "Replay" : "Resume"}</>}</Button>
              <Button size="sm" variant="ghost" onClick={d.cycleSpeed}>{d.speed}×</Button>
              <Button size="sm" variant="ghost" onClick={d.restart}><RotateCcw size={13} /></Button>
              <Button size="sm" variant="outline" onClick={d.skip} disabled={d.done}><FastForward size={13} /> Skip to ruling</Button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            {/* Chamber */}
            <Panel className="p-3">
              <Chamber c={c} current={d.current} verdictShown={d.done} onPick={setPicked} picked={picked} />
              <div className="mt-3 min-h-[64px] rounded-lg border border-line bg-panel-2 px-3.5 py-2.5">
                <AnimatePresence mode="wait">
                  {d.current ? (
                    <motion.div key={d.shown} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.2 }}>
                      <div className="eyebrow mb-0.5">Round {d.current.round} · {d.flat[d.shown - 1]?.round.title}</div>
                      <p className="line-clamp-2 text-[13px] leading-snug text-ink">
                        <b>{d.current.speaker === "moderator" ? c.moderator.name : c.agents.find((a) => a.id === d.current!.speaker)?.name}:</b> {d.current.text}
                      </p>
                    </motion.div>
                  ) : <p className="text-[13px] text-muted">The council is convening…</p>}
                </AnimatePresence>
              </div>
            </Panel>

            {/* Consensus vs dissent */}
            <Panel className="flex flex-col">
              <PanelHead eyebrow="Structured finding" title={d.done ? "Ruling recorded" : "Council in session"}
                right={d.done && c.consensus.human_review ? <Chip tone="amber"><UserCheck size={11} /> human review required</Chip> : undefined} />
              <div className="flex-1 px-4 pb-4">
                <AnimatePresence mode="wait">
                  {!d.done ? (
                    <motion.div key="wait" exit={{ opacity: 0 }} className="space-y-3">
                      <p className="text-[12.5px] text-muted">The ruling appears when the debate ends. Dissent is never merged into the majority view.</p>
                      <div className="space-y-2">
                        {c.rounds.map((r) => {
                          const idx = d.flat.findIndex((x) => x.round.n === r.n);
                          const state = d.shown > idx + r.entries.length - 1 ? "done" : d.shown > idx ? "live" : "todo";
                          return (
                            <div key={r.n} className="flex items-center gap-3 rounded-md border border-line px-3 py-2">
                              <span className={cn("grid size-6 place-items-center rounded-full border text-[11px] num",
                                state === "done" ? "border-ok/40 bg-ok-soft text-ok" : state === "live" ? "border-info/50 bg-info-soft text-info" : "border-line text-faint")}>{r.n}</span>
                              <span className={cn("text-[12.5px]", state === "todo" ? "text-faint" : "text-ink")}>{r.title}</span>
                              <span className="num ml-auto text-[11px] text-faint">{r.entries.length} exchanges</span>
                              {state === "live" && <span className="size-1.5 animate-pulse rounded-full bg-info" />}
                            </div>
                          );
                        })}
                      </div>
                    </motion.div>
                  ) : (
                    <motion.div key="verdict" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
                      <p className="display text-[19px] font-semibold leading-snug text-ink">{c.consensus.outcome}</p>
                      <TallyBar tally={c.tally} />
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-lg border border-ok/25 bg-ok-soft/40 p-3">
                          <div className="eyebrow mb-2 !text-ok">Consensus · {c.consensus.agree.length} agents</div>
                          <div className="flex flex-wrap gap-1.5">
                            {c.consensus.agree.map((id, i) => {
                              const a = c.agents.find((x) => x.id === id)!;
                              return (
                                <motion.span key={id} initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.1 + i * 0.06 }} title={a.name}>
                                  <AgentAvatar agent={a} size={28} />
                                </motion.span>
                              );
                            })}
                          </div>
                          <p className="mt-2 text-[12px] text-ink-2">Chain links supported by records: <b className="num text-ink">{c.consensus.links_supported}</b></p>
                        </div>
                        <div className="rounded-lg border border-amber/30 bg-amber-soft/40 p-3">
                          <div className="eyebrow mb-2 !text-amber">Dissent · kept on the record</div>
                          {c.consensus.dissent.length === 0 && <p className="text-[12px] text-muted">No agent dissented.</p>}
                          {c.consensus.dissent.map((x) => {
                            const a = c.agents.find((y) => y.id === x.agent)!;
                            return (
                              <div key={x.agent} className="flex gap-2">
                                <AgentAvatar agent={a} size={28} />
                                <div><div className="text-[12px] font-semibold text-ink">{a.name}</div><p className="text-[12px] text-ink-2">{x.reason}</p></div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      <div>
                        <div className="eyebrow mb-2 flex items-center gap-1.5"><Sparkles size={12} /> What would change our conclusion?</div>
                        <div className="space-y-2">
                          {c.sensitivity.map((s, i) => (
                            <motion.div key={s.evidence} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 + i * 0.08 }}
                              className="rounded-md border border-line p-2.5">
                              <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold text-ink"><FileQuestion size={13} className="text-amber" /> If we obtain: {s.evidence}</div>
                              <div className="space-y-1">
                                {s.if.map((w) => (
                                  <div key={w.condition} className="grid grid-cols-[1fr_auto_1fr] items-start gap-2 text-[11.5px]">
                                    <span className="text-ink-2">{w.condition}</span><ArrowRight size={12} className="mt-0.5 text-faint" /><span className="text-ink">{w.effect}</span>
                                  </div>
                                ))}
                              </div>
                            </motion.div>
                          ))}
                        </div>
                      </div>
                      <p className="text-[11px] text-faint">{c.note}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </Panel>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            {/* Transcript */}
            <Panel className="flex flex-col">
              <PanelHead eyebrow="Debate transcript" title={pickedAgent ? `Filtered to ${pickedAgent.name}` : "All exchanges"}
                right={picked ? <Button size="sm" variant="ghost" onClick={() => setPicked(null)}>Clear filter</Button> : <span className="text-[11.5px] text-faint">Click a seat to filter</span>} />
              <div ref={scroller} className="max-h-[640px] overflow-y-auto px-4 pb-4">
                {visible.map(({ e, round, first }, i) => (
                  <div key={i}>
                    {first && !picked && (
                      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="sticky top-0 z-10 -mx-4 mb-1 mt-2 border-y border-line bg-panel/95 px-4 py-1.5 backdrop-blur">
                        <span className="eyebrow">Round {round.n} · {round.title}</span>
                      </motion.div>
                    )}
                    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
                      <Entry e={e} c={c} pool={pool} fresh={d.playing && i === visible.length - 1} />
                    </motion.div>
                  </div>
                ))}
                {d.playing && (
                  <div className="flex items-center gap-2 py-3 text-[12px] text-faint">
                    <span className="flex gap-1">{[0, 1, 2].map((k) => <motion.span key={k} className="size-1.5 rounded-full bg-faint" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ repeat: Infinity, duration: 1, delay: k * 0.15 }} />)}</span>
                    next speaker
                  </div>
                )}
              </div>
            </Panel>

            {/* Claims · requests · roles */}
            <Panel>
              <Tabs defaultValue="claims">
                <div className="px-4 pt-3.5"><TabsList>
                  <TabsTrigger value="claims">Claims ledger</TabsTrigger>
                  <TabsTrigger value="requests">Record requests</TabsTrigger>
                  <TabsTrigger value="roles">Agent roles</TabsTrigger>
                </TabsList></div>
                <TabsContent value="claims" className="px-4 pb-4 pt-3">
                  <TallyBar tally={c.tally} />
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {[null, "SUPPORTED", "CONTESTED", "UNEXPLAINED"].map((s) => (
                      <button key={s ?? "all"} onClick={() => setClaimFilter(s)}
                        className={cn("rounded-full border px-2.5 py-0.5 text-[12px] font-medium", claimFilter === s ? "border-ink bg-ink text-bg" : "border-line text-muted hover:text-ink")}>
                        {s ? s.toLowerCase() : "all"}
                      </button>
                    ))}
                  </div>
                  <div className="mt-1 max-h-[560px] overflow-y-auto">
                    {c.claims.filter((cl) => !claimFilter || cl.status === claimFilter).map((cl) => <ClaimRow key={cl.id} cl={cl} c={c} pool={pool} />)}
                  </div>
                </TabsContent>
                <TabsContent value="requests" className="px-4 pb-4 pt-3">
                  <p className="mb-3 text-[12px] text-muted">Agents cannot invent records. When one needs something, it asks; the moderator either retrieves it from Loom or records that the source is not connected.</p>
                  <div className="space-y-2.5">
                    {c.requests.map((q, i) => {
                      const a = c.agents.find((x) => x.id === q.by);
                      return (
                        <motion.div key={q.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
                          className={cn("rounded-lg border p-3", q.status === "NOT_INGESTED" ? "border-dashed border-line-strong" : "border-line")}>
                          <div className="flex items-center gap-2">
                            {a && <AgentAvatar agent={a} size={22} />}
                            <span className="num text-[11px] text-faint">{q.id} · round {q.round}</span>
                            <span className="ml-auto flex items-center gap-1 text-[10.5px] text-faint">
                              requested <ArrowRight size={10} /> <Chip tone={STATUS_TONE[q.status] ?? "faint"}>{q.status.replace("_", " ").toLowerCase()}</Chip>
                            </span>
                          </div>
                          <div className="mt-1.5 text-[12.5px] font-semibold text-ink">{q.record} <span className="font-normal text-muted">· {q.system}</span></div>
                          <p className="text-[11.5px] text-muted">{q.reason}</p>
                          <p className="mt-1 text-[12px] text-ink-2">{q.result}</p>
                          {q.status === "NOT_INGESTED" && <p className="mt-1.5 flex items-center gap-1 text-[11px] text-amber"><ShieldAlert size={12} /> Collect manually — listed under Missing Evidence</p>}
                        </motion.div>
                      );
                    })}
                  </div>
                </TabsContent>
                <TabsContent value="roles" className="px-4 pb-4 pt-3">
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    {c.agents.map((a) => (
                      <div key={a.id} className="rounded-lg border border-line p-3">
                        <div className="flex items-center gap-2"><AgentAvatar agent={a} size={28} />
                          <div><div className="text-[12.5px] font-semibold text-ink">{a.name}</div><div className={cn("text-[10.5px]", stanceOf(a.stance).text)}>{stanceOf(a.stance).label}</div></div>
                        </div>
                        <p className="mt-2 text-[11.5px] text-muted">{a.job}</p>
                        <p className="mt-1.5 text-[12px] text-ink-2"><Gavel size={11} className="mr-1 inline text-faint" />{a.position}</p>
                      </div>
                    ))}
                  </div>
                </TabsContent>
              </Tabs>
            </Panel>
          </div>
          <div className="mt-4 flex justify-end gap-3 text-[12.5px]">
            <Link href={`/evidence/missing?alert=${id}`} className="text-info hover:underline">Missing evidence for this case</Link>
            <Link href={`/controls?alert=${id}`} className="text-info hover:underline">Which control would have stopped it?</Link>
          </div>
        </>
      )}
    </div>
  );
}
