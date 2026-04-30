"use client";

import { useCaseStore } from "@/lib/stores/caseStore";
import { cn } from "@/lib/utils";

const COLORS = {
  idle:         { dot: "bg-slate-400",   label: "idle" },
  connecting:   { dot: "bg-amber-500 animate-pulse", label: "connecting" },
  connected:    { dot: "bg-emerald-500", label: "live" },
  reconnecting: { dot: "bg-amber-500 animate-pulse", label: "reconnecting" },
  disconnected: { dot: "bg-rose-500",    label: "offline" },
} as const;

export function ConnectionStatusPill() {
  const wsState = useCaseStore((s) => s.wsState);
  const meta = COLORS[wsState];

  return (
    <div className="hidden sm:flex items-center gap-1.5 text-[11px] smallcaps text-[hsl(var(--muted-foreground))] px-2 py-1 rounded-md bg-[hsl(var(--muted))]">
      <span className={cn("w-1.5 h-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </div>
  );
}
