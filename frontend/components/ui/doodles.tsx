"use client";

import { motion } from "motion/react";

import { cn } from "@/lib/format";

/*
  Line-art doodles in the Disha moodboard style: ink strokes, sparkles, hatched accents.
  Doodles that sit on pastel cards use fixed ink (#111114); Sparkle strokes with currentColor
  so it also works on dark panels.
*/

const INK = "#111114";

export function Sparkle({ className = "", fill = "none" }: { className?: string; fill?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path d="M12 1c1 7.5 3.5 10 11 11-7.5 1-10 3.5-11 11-1-7.5-3.5-10-11-11 7.5-1 10-3.5 11-11Z" fill={fill} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

const draw = {
  hidden: { pathLength: 0, opacity: 0 },
  show: (i: number) => ({
    pathLength: 1,
    opacity: 1,
    transition: { pathLength: { delay: 0.2 + i * 0.15, duration: 0.9, ease: "easeInOut" as const }, opacity: { delay: 0.2 + i * 0.15, duration: 0.01 } },
  }),
};

/** Hero: a key (privilege) whose dotted thread runs through an open door to a stack of coins (payment), under a magnifier. */
export function ThreadIllustration({ className = "" }: { className?: string }) {
  return (
    <motion.svg viewBox="0 0 340 240" className={className} initial="hidden" animate="show" aria-hidden>
      <defs>
        <pattern id="sutra-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="7" stroke={INK} strokeWidth="1.4" />
        </pattern>
      </defs>
      {/* the thread */}
      <motion.path custom={0} variants={draw} d="M24 214 C 70 208, 64 176, 112 178 S 186 204, 230 196 S 290 182, 322 190" fill="none" stroke={INK} strokeWidth="2.4" strokeDasharray="1 9" strokeLinecap="round" />
      {/* key */}
      <motion.g custom={1} variants={draw} transform="rotate(-18 60 130)">
        <motion.circle custom={1} variants={draw} cx="42" cy="130" r="20" fill="#f5c84c" stroke={INK} strokeWidth="2.6" />
        <motion.circle custom={1} variants={draw} cx="42" cy="130" r="6" fill="#fff" stroke={INK} strokeWidth="2.2" />
        <motion.path custom={2} variants={draw} d="M62 130 H112 M96 130 v12 M106 130 v9" fill="none" stroke={INK} strokeWidth="2.6" strokeLinecap="round" />
      </motion.g>
      {/* open door, glowing orchid */}
      <motion.path custom={2} variants={draw} d="M150 184 V100 a36 36 0 0 1 72 0 V184 Z" fill="#f0a0f2" stroke={INK} strokeWidth="2.6" strokeLinejoin="round" />
      <motion.path custom={3} variants={draw} d="M150 184 L132 192 V110 L150 100" fill="#fff" stroke={INK} strokeWidth="2.6" strokeLinejoin="round" />
      <motion.path custom={3} variants={draw} d="M168 142 h36 M168 156 h24 M168 114 a18 18 0 0 1 36 0" fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" />
      {/* coins */}
      {[172, 158, 144].map((y, i) => (
        <motion.g key={y} custom={4 + i * 0.5} variants={draw}>
          <motion.path custom={4 + i * 0.5} variants={draw} d={`M246 ${y} v9 a26 8 0 0 0 52 0 v-9`} fill="#ff9b3f" stroke={INK} strokeWidth="2.4" strokeLinejoin="round" />
          <motion.ellipse custom={4 + i * 0.5} variants={draw} cx="272" cy={y} rx="26" ry="8" fill="#f5c84c" stroke={INK} strokeWidth="2.4" />
        </motion.g>
      ))}
      {/* magnifier with hatched lens */}
      <motion.circle custom={6} variants={draw} cx="262" cy="66" r="22" fill="url(#sutra-hatch)" stroke={INK} strokeWidth="2.4" />
      <motion.path custom={6} variants={draw} d="M278 82 L296 100" fill="none" stroke={INK} strokeWidth="6" strokeLinecap="round" />
      {/* circles & sparkles */}
      <motion.circle custom={7} variants={draw} cx="40" cy="40" r="14" fill="none" stroke={INK} strokeWidth="2" />
      <motion.circle custom={7} variants={draw} cx="118" cy="44" r="5" fill="none" stroke={INK} strokeWidth="2" />
      <motion.path custom={8} variants={draw} d="M196 22c1 12 5 16 17 17-12 1-16 5-17 17-1-12-5-16-17-17 12-1 16-5 17-17Z" fill="#fff" stroke={INK} strokeWidth="2" />
      <motion.path custom={8} variants={draw} d="M92 196c.6 7 3 9.5 10 10-7 .6-9.4 3-10 10-.6-7-3-9.4-10-10 7-.5 9.4-3 10-10Z" fill={INK} />
    </motion.svg>
  );
}

/** Winding path with checkpoints — the current step glows tangerine (moodboard "roadmap" card). */
export function PathDoodle({ className = "", current = 2 }: { className?: string; current?: number }) {
  const stops = [
    [10, 100],
    [74, 70],
    [130, 50],
    [210, 12],
  ];
  return (
    <svg viewBox="0 0 220 120" className={className} aria-hidden>
      <path d="M10 100 C 50 20, 90 120, 130 50 S 190 30, 210 12" fill="none" stroke="#fff" strokeWidth="10" strokeLinecap="round" />
      <path d="M10 100 C 50 20, 90 120, 130 50 S 190 30, 210 12" fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" strokeDasharray="2 10" />
      {stops.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="11" fill={i === current ? "#ff9b3f" : "#fff"} stroke={INK} strokeWidth="2" />
          <path d={`M${x - 4} ${y} l3 3 6-6`} fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" />
        </g>
      ))}
    </svg>
  );
}

export function Avatar({ name, className }: { name?: string | null; className?: string }) {
  const initials = (name ?? "").split(" ").filter(Boolean).map((p) => p[0]).join("").slice(0, 2).toUpperCase() || "✦";
  return (
    <span className={cn("grid size-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-orchid to-periwinkle text-[14px] font-semibold text-pastel-ink ring-4 ring-panel", className)}>
      {initials}
    </span>
  );
}
