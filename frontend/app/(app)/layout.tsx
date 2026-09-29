import { EvidenceSheet } from "@/components/brief/evidence";
import { AskDock } from "@/components/shell/ask-dock";
import { CommandPalette } from "@/components/shell/command-palette";
import { LiveProvider, LiveToasts } from "@/components/shell/live";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { UIProvider } from "@/components/shell/ui-context";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <UIProvider>
      <LiveProvider>
        {/* Floating rail and content on the periwinkle canvas, as in Disha. */}
        <div className="flex h-screen gap-3 overflow-hidden p-3">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <Topbar />
            <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
          </div>
        </div>
        <CommandPalette />
        <AskDock />
        <EvidenceSheet />
        <LiveToasts />
      </LiveProvider>
    </UIProvider>
  );
}
