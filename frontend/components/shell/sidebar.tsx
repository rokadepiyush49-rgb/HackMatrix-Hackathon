"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Sparkle } from "@/components/ui/doodles";
import { useAlerts } from "@/lib/api";
import { cn } from "@/lib/format";
import { useMediaQuery, useStoredValue } from "@/lib/hooks";

import { NAV } from "./nav";

function Wordmark({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <motion.span initial={{ rotate: -90, scale: 0.6 }} animate={{ rotate: 0, scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 18 }}>
        <Sparkle className="size-7 text-ink" fill="var(--color-tangerine)" />
      </motion.span>
      {!collapsed && (
        <div className="leading-none">
          <div className="display text-[22px] font-semibold text-ink">sutra</div>
          <div className="mt-1 text-[10px] font-medium tracking-[0.06em] text-faint">privilege → payment</div>
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const path = usePathname();
  // A stored preference wins; otherwise the rail collapses on narrow windows and follows resizes.
  const narrow = useMediaQuery("(max-width: 1099px)");
  const [stored, store] = useStoredValue("sutra.nav");
  const collapsed = stored !== null ? stored === "1" : narrow;
  const { data: alerts } = useAlerts("", { staleTime: 60_000 });
  const queued = alerts?.length ?? 0;
  const p1 = alerts?.filter((a) => a.priority === "P1").length ?? 0;

  const toggle = () => store(collapsed ? "0" : "1");

  const isActive = (href: string) =>
    href === "/" ? path === "/" : path === href || (path.startsWith(href + "/") && !NAV.flatMap((s) => s.items).some((i) => i.href !== href && i.href.startsWith(href + "/") && path.startsWith(i.href)));

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 248 }}
      transition={{ type: "spring", stiffness: 380, damping: 36 }}
      className="panel relative z-20 flex h-full shrink-0 flex-col overflow-hidden !rounded-[2rem]"
    >
      <div className={cn("flex h-[72px] shrink-0 items-center", collapsed ? "justify-center px-0" : "justify-between pr-4 pl-5")}>
        <Link href="/" aria-label="SUTRA home">
          <Wordmark collapsed={collapsed} />
        </Link>
        {!collapsed && (
          <button onClick={toggle} className="grid size-8 place-items-center rounded-full text-faint hover:bg-ink/[0.06] hover:text-ink" aria-label="Collapse navigation">
            <PanelLeftClose size={16} />
          </button>
        )}
      </div>
      <nav className={cn("flex-1 overflow-y-auto pb-3", collapsed ? "px-2.5" : "px-3")}>
        {NAV.map((section, si) => (
          <div key={si} className="mb-2.5">
            {section.title && !collapsed && <div className="eyebrow px-3.5 pb-1 pt-1.5">{section.title}</div>}
            {section.title && collapsed && <div className="mx-3 my-2 h-px bg-line" />}
            {section.items.map((item) => {
              const active = isActive(item.href);
              const Icon = item.icon;
              const count = item.badge === "queued" ? queued : item.badge === "p1" ? p1 : 0;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "group relative flex items-center gap-3 rounded-full px-3.5 py-[7px] text-[13.5px] transition-colors",
                    active ? "font-medium text-on-primary" : "text-ink-2 hover:bg-ink/[0.05] hover:text-ink",
                    collapsed && "justify-center px-0 py-2.5",
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="nav-active"
                      className="absolute inset-0 rounded-full bg-primary"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  )}
                  <Icon size={17} className="relative z-10 shrink-0" />
                  {!collapsed && <span className="relative z-10 truncate">{item.label}</span>}
                  {!collapsed && count > 0 && (
                    <span className="num relative z-10 ml-auto rounded-full bg-coral-soft px-2 text-[11px] font-semibold text-pastel-ink">{count}</span>
                  )}
                  {collapsed && count > 0 && <span className="absolute top-1.5 right-2 z-10 size-2 rounded-full bg-coral ring-2 ring-panel" />}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <AnimatePresence>
        {collapsed && (
          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={toggle}
            className="mx-auto mb-4 grid size-9 place-items-center rounded-full text-faint hover:bg-ink/[0.06] hover:text-ink"
            aria-label="Expand navigation"
          >
            <PanelLeftOpen size={16} />
          </motion.button>
        )}
      </AnimatePresence>
      {!collapsed && (
        <div className="m-3 mt-0 shrink-0 rounded-3xl bg-panel-2 p-3.5 text-[11px] leading-snug text-muted">
          Synthetic data · Kestrel UCB (fictional). No real customer or employee is represented.
        </div>
      )}
    </motion.aside>
  );
}
