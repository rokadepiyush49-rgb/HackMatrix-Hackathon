import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Poppins } from "next/font/google";

import { Providers } from "@/components/shell/providers";

import "./globals.css";

// Poppins for every word (shared with Disha); JetBrains Mono only for IDs, codes and hashes.
const poppins = Poppins({ subsets: ["latin"], weight: ["300", "400", "500", "600", "700"], variable: "--font-poppins", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: { default: "SUTRA", template: "%s · SUTRA" },
  description: "Privilege-to-payment intelligence for financial-crime and insider-risk investigation.",
};

export const viewport: Viewport = {
  themeColor: "#dce3fb",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${poppins.variable} ${jetbrains.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
