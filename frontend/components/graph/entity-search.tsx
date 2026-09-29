"use client";

import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Chip } from "@/components/ui/primitives";
import { useGet } from "@/lib/api";
import { cn } from "@/lib/format";

export interface SearchHit { id: string; kind: string; label: string; sub: string }

const KIND_TONE: Record<string, "threat" | "info" | "amber" | "ai" | "faint"> = {
  employee: "threat", account: "info", external: "faint", customer: "amber", device: "ai", alert: "threat",
};

/** Type-ahead over employees, accounts, customers, devices and alerts. */
export function EntitySearch({ onPick, placeholder = "Search an account, employee, customer or device…", kinds, className, initial = "" }: {
  onPick: (hit: SearchHit) => void; placeholder?: string; kinds?: string[]; className?: string; initial?: string;
}) {
  const [q, setQ] = useState(initial);
  const [debounced, setDebounced] = useState(initial);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 180); return () => clearTimeout(t); }, [q]);
  const { data } = useGet<SearchHit[]>(["search", debounced], debounced.length >= 2 ? `/entities/search?q=${encodeURIComponent(debounced)}` : null);
  const hits = (data ?? []).filter((h) => !kinds || kinds.includes(h.kind));

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (h: SearchHit) => { onPick(h); setQ(h.id); setOpen(false); };

  return (
    <div ref={box} className={cn("relative w-full sm:w-[360px]", className)}>
      <div className="flex h-9 items-center gap-2 rounded-md border border-line-strong bg-panel px-2.5 focus-within:border-info">
        <Search size={14} className="text-faint" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setIdx(0); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
            if (e.key === "Enter" && hits[idx]) pick(hits[idx]);
            if (e.key === "Escape") setOpen(false);
          }}
          placeholder={placeholder}
          aria-label="Search entities"
          className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none placeholder:text-faint"
        />
      </div>
      {open && hits.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-[70] mt-1 max-h-[320px] overflow-y-auto rounded-lg border border-line-strong bg-raised p-1 shadow-2xl">
          {hits.map((h, i) => (
            <button key={`${h.kind}-${h.id}`} onMouseEnter={() => setIdx(i)} onClick={() => pick(h)}
              className={cn("flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px]", i === idx && "bg-panel-2")}>
              <Chip tone={KIND_TONE[h.kind] ?? "faint"}>{h.kind}</Chip>
              <span className="num text-ink">{h.label}</span>
              <span className="min-w-0 truncate text-muted">{h.sub}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
