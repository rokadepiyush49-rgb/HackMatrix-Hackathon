"use client";

// Voice for the Investigation Council and Live Ops, using the browser's own speech synthesis
// (Web Speech API). Nothing leaves the machine — no API key, no network, works offline on the
// demo laptop. Indian-English voices are preferred where the OS has them.

import { useEffect, useState, useSyncExternalStore } from "react";

import { useStoredValue } from "@/lib/hooks";

export interface Persona {
  pitch: number;
  rate: number;
  /** index into the ranked voice list, so different speakers get different voices where possible */
  slot: number;
}

// One voice per seat. Prosecution voices are lower and steadier, the defence brighter, neutral
// finders in between; the moderator is unhurried.
export const PERSONAS: Record<string, Persona> = {
  moderator: { pitch: 0.95, rate: 0.98, slot: 0 },
  chain: { pitch: 0.9, rate: 1.04, slot: 1 },
  money: { pitch: 1.05, rate: 1.06, slot: 2 },
  insider: { pitch: 0.85, rate: 1.0, slot: 3 },
  alibi: { pitch: 1.1, rate: 1.02, slot: 4 },
  defence: { pitch: 1.2, rate: 1.05, slot: 5 },
  prosecution: { pitch: 0.8, rate: 0.98, slot: 6 },
  control: { pitch: 1.0, rate: 1.04, slot: 7 },
  evidence: { pitch: 1.12, rate: 1.0, slot: 8 },
  announcer: { pitch: 1.0, rate: 1.0, slot: 0 },
};

// Known natural-sounding voices by name; anything en-IN outranks the rest.
const FAVOURITES = ["Neerja", "Prabhat", "Heera", "Ravi", "Rishi", "Veena", "Lekha", "Google UK English", "Daniel", "Samantha", "Karen", "Moira", "Tessa"];
// Newer macOS "character" voices: usable, but cast only when nothing plainer exists.
const CHARACTER = /^(Eddy|Flo|Reed|Rocko|Sandy|Shelley)\b/;
// macOS ships sound-effect and robotic voices under en-US; never cast them.
const NOVELTY = /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Fred|Good News|Jester|Junior|Kathy|Organ|Ralph|Superstar|Trinoids|Whisper|Wobble|Zarvox|Grandma|Grandpa)\b/;

export function voiceSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

function rank(v: SpeechSynthesisVoice): number {
  const lang = v.lang.toLowerCase().replace("_", "-");
  const fav = FAVOURITES.findIndex((n) => v.name.includes(n));
  return (lang === "en-in" ? 0 : lang.startsWith("en-gb") ? 100 : lang.startsWith("en") ? 200 : 900)
    + (fav === -1 ? 50 : fav) + (CHARACTER.test(v.name) ? 400 : 0) + (v.localService ? 0 : 5);
}

const noSubscription = () => () => {};

/** Whether this browser can speak — false during server rendering, so markup hydrates cleanly. */
export function useVoiceSupported(): boolean {
  return useSyncExternalStore(noSubscription, voiceSupported, () => false);
}

/** English voices, best first. Re-reads when the OS finishes loading its voice list. */
export function useVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    if (!voiceSupported()) return;
    const load = () =>
      setVoices(speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("en") && !NOVELTY.test(v.name))
        .sort((a, b) => rank(a) - rank(b)));
    load();
    speechSynthesis.addEventListener("voiceschanged", load);
    return () => speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);
  return voices;
}

/** The voice on/off switch, remembered per browser. Off until the person turns it on. */
export function useVoiceSetting(): [boolean, (on: boolean) => void] {
  const [stored, setStored] = useStoredValue("sutra.voice");
  return [stored === "on", (on) => {
    setStored(on ? "on" : "off");
    if (!on) stopSpeaking();
  }];
}

const UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];

function spell(id: string): string {
  // "AL-0922-003" → "A L, 0 9 2 2, 0 0 3": identifiers read character by character.
  return id.split("-").map((part) => part.split("").map((ch) => (/\d/.test(ch) ? UNITS[+ch] : ch)).join(" ")).join(", ");
}

/** Rewrite on-screen text into something a speech engine reads naturally. */
export function speakable(text: string): string {
  return text
    .replace(/\s*[([]?\bEV-\d+(?:\s*,\s*EV-\d+)*[)\]]?/g, "") // citations are for the eye
    .replace(/₹\s?([\d.]+)\s?Cr\b/g, (_, n: string) => `${parseFloat(n)} crore rupees`)
    .replace(/₹\s?([\d.]+)\s?L\b/g, (_, n: string) => `${parseFloat(n)} lakh rupees`)
    .replace(/₹\s?([\d,]+(?:\.\d+)?)/g, "$1 rupees")
    .replace(/\bP([123])\b/g, (_, n) => `priority ${UNITS[+n]}`)
    .replace(/\bE(\d)′/g, "E $1 prime")
    .replace(/\b(?:[A-Z]{1,4}-[A-Z0-9]+(?:-\d+)*)\b/g, (m) => spell(m))
    .replace(/\+91 •+ (\d{4})/g, (_, d: string) => `a number ending ${d.split("").map((c) => UNITS[+c]).join(" ")}`)
    .replace(/\b(\d+) min\b/g, "$1 minutes")
    .replace(/\b(\d+(?:\.\d+)?) h\b/g, "$1 hours")
    .replace(/\b[A-Z]{5,}\b/g, (w) => w.toLowerCase()) // OVERRIDE is a word, not an acronym
    .replace(/→/g, " to ")
    .replace(/\s*[·•]\s*/g, ", ")
    .replace(/×/g, " times ")
    .replace(/≥/g, " at least ")
    .replace(/[“”"]/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** Sentence-sized pieces: Chrome stops reading a single utterance after ~15 seconds. */
function chunks(text: string, max = 180): string[] {
  const out: string[] = [];
  // split after sentence punctuation followed by a space, so "14.15" stays whole
  for (const sentence of text.split(/(?<=[.!?])\s+/)) {
    let rest = sentence.trim();
    while (rest.length > max) {
      const cut = Math.max(rest.lastIndexOf(", ", max), rest.lastIndexOf(" ", max));
      out.push(rest.slice(0, cut > 40 ? cut : max));
      rest = rest.slice(cut > 40 ? cut + 1 : max).trim();
    }
    if (rest) out.push(rest);
  }
  return out;
}

/** Indian-English voices only when there are at least two (a bank in Pune); otherwise the best four. */
function cast(voices: SpeechSynthesisVoice[], persona: Persona): SpeechSynthesisVoice | null {
  const indian = voices.filter((v) => v.lang.toLowerCase().replace("_", "-") === "en-in");
  const pool = indian.length >= 2 ? indian : voices.slice(0, 4);
  return pool.length ? pool[persona.slot % pool.length] : null;
}

let generation = 0;

/**
 * Speak `text` as `persona`. Resolves `onDone` once, when the last piece finishes or fails.
 * Returns a cancel function; cancelling (or starting another speech) never fires `onDone`.
 */
export function speak(text: string, persona: Persona, voices: SpeechSynthesisVoice[], opts: { rate?: number; onDone?: () => void } = {}): () => void {
  if (!voiceSupported()) {
    opts.onDone?.();
    return () => {};
  }
  const mine = ++generation;
  speechSynthesis.cancel();
  const voice = cast(voices, persona);
  const parts = chunks(speakable(text));
  const finish = () => {
    if (mine === generation) opts.onDone?.();
  };
  if (!parts.length) {
    finish();
    return () => {};
  }
  parts.forEach((part, i) => {
    const u = new SpeechSynthesisUtterance(part);
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    }
    u.pitch = persona.pitch;
    u.rate = Math.min(2, persona.rate * (opts.rate ?? 1));
    if (i === parts.length - 1) {
      u.onend = finish;
      u.onerror = finish;
    }
    speechSynthesis.speak(u);
  });
  return () => {
    if (mine === generation) {
      generation++;
      speechSynthesis.cancel();
    }
  };
}

export function stopSpeaking(): void {
  generation++;
  if (voiceSupported()) speechSynthesis.cancel();
}
