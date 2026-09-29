"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { ArrowRight, ChevronRight } from "lucide-react";
import { animate, motion, useInView, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import Link from "next/link";
import { forwardRef, useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/format";

import { Sparkle } from "./doodles";

// ── Button ─────────────────────────────────────────────────────────────────

// Moodboard pills: ink for the dominant action, paper for secondary, pastel for accents.
type Variant = "primary" | "ghost" | "outline" | "danger" | "ai" | "tangerine";
const VARIANT: Record<Variant, string> = {
  primary: "bg-primary text-on-primary hover:bg-primary-pressed active:bg-primary-pressed",
  ghost: "text-ink-2 hover:bg-ink/[0.06] hover:text-ink",
  outline: "border border-line bg-panel text-ink shadow-xs hover:bg-panel-2",
  danger: "bg-coral text-pastel-ink hover:brightness-105",
  ai: "bg-ai-soft text-ai hover:brightness-95",
  tangerine: "bg-tangerine text-pastel-ink hover:brightness-105",
};

const buttonClass = (variant: Variant, size: "sm" | "md", className?: string) =>
  cn(
    "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-medium leading-[1.3] transition-[background-color,color,filter,transform] duration-150 active:scale-[.97] disabled:opacity-40 disabled:pointer-events-none select-none",
    size === "sm" ? "h-8 px-3.5 text-[12.5px]" : "h-10 px-5 text-[14px]",
    VARIANT[variant],
    className,
  );

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }>(
  function Button({ variant = "outline", size = "md", className, ...props }, ref) {
    return <button ref={ref} className={buttonClass(variant, size, className)} {...props} />;
  },
);

/** A link styled as a button — for navigation, so we never nest a <button> inside an <a>. */
export function ButtonLink({ href, variant = "outline", size = "md", className, children }: {
  href: string; variant?: Variant; size?: "sm" | "md"; className?: string; children: ReactNode;
}) {
  return <Link href={href} className={buttonClass(variant, size, className)}>{children}</Link>;
}

// ── Tone chips ─────────────────────────────────────────────────────────────

export type Tone = "threat" | "amber" | "ok" | "ai" | "info" | "faint" | "ink";
const TONE: Record<Tone, string> = {
  threat: "bg-threat-soft text-threat",
  amber: "bg-amber-soft text-amber",
  ok: "bg-ok-soft text-ok",
  ai: "bg-ai-soft text-ai",
  info: "bg-info-soft text-info",
  faint: "bg-panel-2 text-muted",
  ink: "bg-primary text-on-primary",
};

export function Chip({ tone = "faint", children, className, mono = false }: { tone?: Tone; children: ReactNode; className?: string; mono?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-[3px] text-[11.5px] font-medium leading-[16px] whitespace-nowrap",
        mono && "font-mono text-[10.5px] tracking-wide uppercase",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ tone = "faint", pulse = false, className }: { tone?: Tone; pulse?: boolean; className?: string }) {
  const color = { threat: "bg-threat", amber: "bg-amber", ok: "bg-ok", ai: "bg-ai", info: "bg-info", faint: "bg-faint", ink: "bg-ink" }[tone];
  return (
    <span className={cn("relative inline-flex size-2", className)}>
      {pulse && <span className={cn("absolute inset-0 rounded-full opacity-60 animate-ping", color)} />}
      <span className={cn("relative inline-flex size-2 rounded-full", color)} />
    </span>
  );
}

export function PriorityPill({ p }: { p: string }) {
  const tone = ({ P1: "threat", P2: "amber", P3: "info", WATCH: "faint", EXPLAINED: "ok" } as const)[p as "P1"] ?? "faint";
  const label = p === "P1" ? "P1 · critical" : p === "P2" ? "P2 · same day" : p === "P3" ? "P3" : p === "EXPLAINED" ? "Explained" : "Watch";
  return <Chip tone={tone}>{label}</Chip>;
}

// ── Panel & headers ────────────────────────────────────────────────────────

export function Panel({ children, className, ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("panel", className)} {...rest}>
      {children}
    </div>
  );
}

export function PanelHead({ eyebrow, title, right, className }: { eyebrow?: ReactNode; title?: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-5 pt-4 pb-2", className)}>
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
        {title && <div className="display truncate text-[16px] font-semibold text-ink">{title}</div>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

export function PageHeader({ eyebrow, title, sub, right }: { eyebrow: string; title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <div className="eyebrow mb-1.5 flex items-center gap-1.5">
          <Sparkle className="size-3.5 text-ink" fill="var(--color-tangerine)" /> {eyebrow}
        </div>
        <h1 className="display text-[30px] font-semibold leading-[1.2] text-ink">{title}</h1>
        {sub && <p className="mt-2 max-w-[80ch] text-[14px] leading-[1.6] text-muted">{sub}</p>}
      </div>
      {right && <div className="flex max-w-full flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

// ── Numbers that count up (respecting reduced motion) ──────────────────────

export function CountUp({ value, format = (v: number) => Math.round(v).toLocaleString("en-IN"), className }: {
  value: number; format?: (v: number) => string; className?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(reduce ? value : 0);
  const text = useTransform(mv, (v) => format(v));
  useEffect(() => {
    if (!inView) return;
    const c = animate(mv, value, { duration: reduce ? 0 : 1.1, ease: [0.16, 1, 0.3, 1] });
    return c.stop;
  }, [inView, value, mv, reduce]);
  return <motion.span ref={ref} className={cn("num", className)}>{text}</motion.span>;
}

// ── Level segments (qualitative — never a score) ───────────────────────────

const LEVEL_IDX: Record<string, number> = { NONE: 0, LOW: 1, ELEVATED: 2, HIGH: 3 };
export function LevelBar({ level, className }: { level: string; className?: string }) {
  const idx = LEVEL_IDX[level] ?? 0;
  const color = level === "HIGH" ? "bg-threat" : level === "ELEVATED" ? "bg-amber" : level === "LOW" ? "bg-ok" : "bg-line-strong";
  return (
    <div className={cn("flex gap-[3px]", className)} aria-label={`Level ${level}`}>
      {[1, 2, 3].map((i) => (
        <motion.span
          key={i}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ delay: i * 0.06, duration: 0.35 }}
          className={cn("h-1.5 w-5 origin-left rounded-full", i <= idx ? color : "bg-line")}
        />
      ))}
    </div>
  );
}

// ── Tabs ───────────────────────────────────────────────────────────────────

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;
export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <TabsPrimitive.List className={cn("inline-flex max-w-full items-center gap-1.5 overflow-x-auto", className)}>
      {children}
    </TabsPrimitive.List>
  );
}
export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      className="shrink-0 whitespace-nowrap rounded-full border border-line bg-panel px-3.5 py-1.5 text-[13px] font-medium text-muted transition-colors hover:text-ink data-[state=active]:border-primary data-[state=active]:bg-primary data-[state=active]:text-on-primary"
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}

// ── Tooltip ────────────────────────────────────────────────────────────────

export function Tip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <TooltipPrimitive.Root delayDuration={150}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className="z-[80] max-w-[320px] rounded-2xl bg-primary px-3 py-2 text-[12px] leading-snug text-on-primary shadow-lg"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

// ── States ─────────────────────────────────────────────────────────────────

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-2xl bg-ink/[0.06]", className)} />;
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="mb-1 grid size-12 place-items-center rounded-full bg-periwinkle-soft text-pastel-ink">
        {icon ?? <Sparkle className="size-6" fill="var(--color-orchid)" />}
      </div>
      <div className="display text-[16px] font-semibold text-ink">{title}</div>
      {children && <div className="max-w-[48ch] text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-2xl bg-threat-soft px-5 py-3.5 text-[13px] text-threat">
      <b>Could not load this view.</b> {msg}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md border border-line bg-panel-2 px-1.5 py-[1px] font-mono text-[10.5px] text-muted">{children}</kbd>;
}

// ── Moodboard pieces (shared with Disha) ───────────────────────────────────

const TILE = {
  mist: "bg-mist",
  sunflower: "bg-sunflower",
  periwinkle: "bg-periwinkle",
  "periwinkle-soft": "bg-periwinkle-soft",
  orchid: "bg-orchid",
  mint: "bg-mint",
  tangerine: "bg-tangerine-soft",
  coral: "bg-coral-soft",
} as const;
export type TileTone = keyof typeof TILE;

/** Pastel stat tile: icon disc on top, label and a big number below. Always ink on pastel. */
export function StatTile({ icon, label, value, sub, tone = "mist", href, className }: {
  icon: ReactNode; label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: TileTone; href?: string; className?: string;
}) {
  const body = (
    <motion.div
      whileHover={href ? { y: -3 } : undefined}
      className={cn("flex h-full min-h-32 flex-col justify-between gap-3 rounded-[1.75rem] p-4 text-pastel-ink", TILE[tone], className)}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-paper/70">{icon}</span>
        {href && <ArrowRight size={15} className="mt-2 opacity-50" />}
      </div>
      <div>
        <div className="text-[13px] leading-tight">{label}</div>
        <div className="display num mt-1.5 text-[28px] font-medium leading-none">{value}</div>
        {sub && <div className="mt-2 text-[11.5px] leading-snug opacity-75">{sub}</div>}
      </div>
    </motion.div>
  );
  return href ? <Link href={href} className="block h-full">{body}</Link> : body;
}

/** Moodboard "black pill" row: white disc icon, title + subtitle, chevron. */
export function PillLink({ href, onClick, icon, title, subtitle, tone = "ink", disabled, trailing }: {
  href?: string; onClick?: () => void; icon: ReactNode; title: ReactNode; subtitle?: ReactNode; tone?: "ink" | "periwinkle"; disabled?: boolean; trailing?: ReactNode;
}) {
  const body = (
    <motion.span
      whileHover={disabled ? undefined : { x: 4 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      className={cn(
        "flex w-full items-center gap-3.5 rounded-full py-2 pr-2.5 pl-2 text-left",
        tone === "ink" ? "bg-pastel-ink text-paper" : "bg-periwinkle-soft text-pastel-ink",
      )}
    >
      <span className="grid size-11 shrink-0 place-items-center rounded-full bg-paper text-[13px] font-semibold text-pastel-ink">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium">{title}</span>
        {subtitle && <span className="block truncate text-[12px] opacity-70">{subtitle}</span>}
      </span>
      <span className={cn("grid size-8 shrink-0 place-items-center rounded-full", tone === "ink" ? "bg-[#2a2a33]" : "bg-paper/70")}>
        {trailing ?? <ChevronRight className="size-4" />}
      </span>
    </motion.span>
  );
  if (href) return <Link href={href} className="block">{body}</Link>;
  return <button type="button" onClick={onClick} disabled={disabled} className="block w-full disabled:opacity-60">{body}</button>;
}

/** Round black arrow CTA with an offset ring, as on the moodboard hero. */
export function ArrowCTA({ href, onClick, label }: { href?: string; onClick?: () => void; label: string }) {
  const inner = (
    <motion.span whileHover={{ scale: 1.06, rotate: -8 }} whileTap={{ scale: 0.94 }} className="relative grid size-[72px] place-items-center">
      <span className="absolute inset-0 -translate-x-1 rounded-full border-[3px] border-pastel-ink" />
      <span className="grid size-16 place-items-center rounded-full bg-pastel-ink text-paper">
        <ArrowRight className="size-6" />
      </span>
    </motion.span>
  );
  return href ? (
    <Link href={href} aria-label={label} className="inline-block">{inner}</Link>
  ) : (
    <button type="button" onClick={onClick} aria-label={label} className="inline-block">{inner}</button>
  );
}

/** Staggered reveal used by bento layouts. */
export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } },
};
export const rise = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { type: "spring" as const, stiffness: 260, damping: 26 } },
};
