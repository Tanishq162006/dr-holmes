/**
 * Agent metadata: colors, avatars, specialty pictograms.
 * Single source of truth for visual identity. Adding an agent = one row.
 */
import type { AgentName } from "./types/wire";

export type AgentMeta = {
  name: AgentName;
  initial: string;
  /** Tailwind class fragments — paired so they all stay in sync. */
  hue: string; // CSS variable name (matches globals.css)
  bgClass: string;
  textClass: string;
  borderClass: string;
  ringClass: string;
  specialty: string;
  pictogram: string; // emoji fallback; replace with SVG when polishing
};

export const AGENT_META: Record<AgentName, AgentMeta> = {
  Hauser: {
    name: "Hauser", initial: "H", hue: "--agent-hauser",
    bgClass: "bg-rose-600 dark:bg-rose-500",
    textClass: "text-rose-600 dark:text-rose-400",
    borderClass: "border-rose-600 dark:border-rose-500",
    ringClass: "ring-rose-500/30",
    specialty: "Lead diagnostician",
    pictogram: "🩺",
  },
  Forman: {
    name: "Forman", initial: "F", hue: "--agent-forman",
    bgClass: "bg-blue-600 dark:bg-blue-500",
    textClass: "text-blue-600 dark:text-blue-400",
    borderClass: "border-blue-600 dark:border-blue-500",
    ringClass: "ring-blue-500/30",
    specialty: "Internal med · Neuro",
    pictogram: "🧠",
  },
  Carmen: {
    name: "Carmen", initial: "C", hue: "--agent-carmen",
    bgClass: "bg-emerald-600 dark:bg-emerald-500",
    textClass: "text-emerald-600 dark:text-emerald-400",
    borderClass: "border-emerald-600 dark:border-emerald-500",
    ringClass: "ring-emerald-500/30",
    specialty: "Immunology",
    pictogram: "🧬",
  },
  Chen: {
    name: "Chen", initial: "Ch", hue: "--agent-chen",
    bgClass: "bg-cyan-600 dark:bg-cyan-500",
    textClass: "text-cyan-600 dark:text-cyan-400",
    borderClass: "border-cyan-600 dark:border-cyan-500",
    ringClass: "ring-cyan-500/30",
    specialty: "Surgical · ICU",
    pictogram: "🔪",
  },
  Wills: {
    name: "Wills", initial: "W", hue: "--agent-wills",
    bgClass: "bg-amber-600 dark:bg-amber-500",
    textClass: "text-amber-600 dark:text-amber-400",
    borderClass: "border-amber-600 dark:border-amber-500",
    ringClass: "ring-amber-500/30",
    specialty: "Oncology",
    pictogram: "🧫",
  },
  Caddick: {
    name: "Caddick", initial: "Ca", hue: "--agent-caddick",
    bgClass: "bg-violet-600 dark:bg-violet-500",
    textClass: "text-violet-600 dark:text-violet-400",
    borderClass: "border-violet-600 dark:border-violet-500",
    ringClass: "ring-violet-500/30",
    specialty: "Moderator",
    pictogram: "⚖️",
  },
};

export function metaFor(name: string): AgentMeta {
  if (name in AGENT_META) {
    return AGENT_META[name as AgentName];
  }
  // Fallback for unknown agent names (won't happen with strict types, but
  // protects against backend drift)
  return {
    name: name as AgentName,
    initial: name.slice(0, 2),
    hue: "--agent-default",
    bgClass: "bg-slate-600",
    textClass: "text-slate-600",
    borderClass: "border-slate-500",
    ringClass: "ring-slate-500/30",
    specialty: "Specialist",
    pictogram: "·",
  };
}
