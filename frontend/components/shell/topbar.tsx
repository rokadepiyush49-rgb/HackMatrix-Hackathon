"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ChevronDown, LogOut, Moon, Search, Sparkles, Sun, UserRound } from "lucide-react";
import { useTheme } from "next-themes";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Avatar } from "@/components/ui/doodles";
import { Kbd } from "@/components/ui/primitives";
import { useMe, useAlerts } from "@/lib/api";
import { cn } from "@/lib/format";
import { useMounted } from "@/lib/hooks";

import { LivePill } from "./live";
import { ALL_ITEMS, NAV } from "./nav";
import { useUI } from "./ui-context";

export function Topbar() {
  const path = usePathname();
  const router = useRouter();
  const { setPalette, openAsk, focusAlert } = useUI();
  const { data: me } = useMe();
  const { data: alerts } = useAlerts("", { staleTime: 60_000 });
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();

  const item = [...ALL_ITEMS].sort((a, b) => b.href.length - a.href.length).find((i) => (i.href === "/" ? path === "/" : path.startsWith(i.href)));
  const section = NAV.find((s) => s.items.some((i) => i.href === item?.href))?.title;
  const askTarget = focusAlert ?? alerts?.[0]?.id;
  const firstName = me?.display_name?.split(" ")[0];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPalette]);

  const signOut = async () => {
    await fetch("/api/session", { method: "DELETE" });
    router.push("/login");
  };

  return (
    <header className="z-30 flex h-[72px] shrink-0 items-center gap-2.5 px-2">
      {/* "Hello, name" greeting from the Disha moodboard; opens the persona menu. */}
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button className="flex min-w-0 flex-1 items-center gap-3 rounded-full py-1 pr-3 pl-1 text-left">
            <Avatar name={me?.display_name} />
            <span className="min-w-0 leading-tight">
              <span className="flex items-center gap-1 text-[15px] font-semibold text-ink">
                <span className="truncate">Hello{firstName ? `, ${firstName}` : ""}</span>
                <ChevronDown size={14} className="shrink-0 text-faint" />
              </span>
              <span className="block truncate text-[12px] text-muted">
                {section ? `${section} · ` : ""}
                {item?.label ?? "SUTRA"}
              </span>
            </span>
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content align="start" sideOffset={6} className="z-[70] w-64 rounded-3xl bg-raised p-1.5 shadow-xl">
            <div className="px-3 py-2">
              <div className="text-[13px] font-medium text-ink">{me?.display_name}</div>
              <div className="text-[11.5px] text-muted">{me?.title}</div>
              <div className="mt-1 text-[10.5px] font-medium tracking-[0.06em] text-faint">{me?.role}</div>
            </div>
            <Dropdown.Separator className="mx-2 my-1 h-px bg-line" />
            <Dropdown.Item onSelect={() => router.push("/login")} className={cn("flex cursor-pointer items-center gap-2 rounded-full px-3 py-2 text-[12.5px] text-ink-2 outline-none data-[highlighted]:bg-panel-2")}>
              <UserRound size={14} /> Switch persona
            </Dropdown.Item>
            <Dropdown.Item onSelect={signOut} className="flex cursor-pointer items-center gap-2 rounded-full px-3 py-2 text-[12.5px] text-ink-2 outline-none data-[highlighted]:bg-panel-2">
              <LogOut size={14} /> Sign out
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>

      <button
        onClick={() => setPalette(true)}
        className="hidden h-10 w-[220px] items-center gap-2 rounded-full bg-panel px-4 text-left text-[13px] text-faint shadow-sm transition-shadow hover:shadow-md md:flex xl:w-[320px]"
      >
        <Search size={15} />
        <span className="flex-1 truncate">Find an employee, account, case…</span>
        <Kbd>⌘K</Kbd>
      </button>
      <LivePill />
      <button
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        className="grid size-10 shrink-0 place-items-center rounded-full bg-panel text-ink-2 shadow-sm transition-shadow hover:shadow-md"
        aria-label="Toggle theme"
      >
        {mounted && resolvedTheme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
      </button>
      <button
        onClick={() => askTarget && openAsk(askTarget)}
        className="flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-full bg-primary py-1 pr-4 pl-1 text-[14px] font-medium text-on-primary shadow-md transition-transform hover:scale-[1.03] active:scale-[.97]"
      >
        <span className="grid size-8 place-items-center rounded-full bg-tangerine text-pastel-ink">
          <Sparkles size={15} />
        </span>
        <span className="hidden sm:inline">Ask SUTRA</span>
      </button>
    </header>
  );
}
