import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { BankHeader } from "@/components/bank/shell";

// The mock bank uses its own type and colours so it never looks like part of SUTRA.
const plex = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata: Metadata = { title: { absolute: "Kestrel Bank · test systems" } };

export default function BankLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={`${plex.className} ${plexMono.variable} min-h-screen bg-[#eef1f0] text-[#14211d] [color-scheme:light] [&_.font-mono]:[font-family:var(--font-plex-mono)]`}>
      <BankHeader />
      <main className="mx-auto max-w-[1240px] px-4 py-6">{children}</main>
    </div>
  );
}
