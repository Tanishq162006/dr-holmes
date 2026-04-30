import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatProb(p: number, digits: number = 0): string {
  return `${(p * 100).toFixed(digits)}%`;
}

export function probColor(p: number): string {
  if (p >= 0.7) return "text-emerald-600 dark:text-emerald-400";
  if (p >= 0.3) return "text-amber-600 dark:text-amber-400";
  return "text-rose-600 dark:text-rose-400";
}

export function probBgColor(p: number): string {
  if (p >= 0.7) return "bg-emerald-500/80";
  if (p >= 0.3) return "bg-amber-500/80";
  return "bg-rose-500/80";
}

export function fmtTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}
