"use client";

import { motion } from "motion/react";

// Re-mounted on every navigation: a quick fade + rise, never bouncy (docs/ux: "speed").
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: "easeOut" }} className="h-full">
      {children}
    </motion.div>
  );
}
