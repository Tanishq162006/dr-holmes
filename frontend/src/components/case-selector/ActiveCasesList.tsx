"use client";

import Link from "next/link";
import type { CaseSummary } from "@/lib/types/wire";
import { fmtTime } from "@/lib/utils";

const STATUS_COLOR: Record<string, string> = {
  pending:    "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  running:    "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  paused:     "bg-slate-500/15 text-slate-500 dark:text-slate-400",
  concluded:  "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  errored:    "bg-rose-500/15 text-rose-500",
  interrupted:"bg-rose-500/15 text-rose-500",
};

export function ActiveCasesList({ cases, loading }: { cases: CaseSummary[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 rounded-md bg-[hsl(var(--muted))] animate-pulse" />
        ))}
      </div>
    );
  }
  if (cases.length === 0) {
    return (
      <div className="text-sm text-[hsl(var(--muted-foreground))] py-8 text-center border border-dashed border-[hsl(var(--border))] rounded-lg">
        No active cases yet. Start one above ↑
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))]">
      {cases.map((c) => (
        <Link
          key={c.id}
          href={`/case/${c.id}`}
          className="flex items-center gap-4 px-4 py-3 hover:bg-[hsl(var(--muted))]/40 transition"
        >
          <span className={`text-[10px] smallcaps px-2 py-0.5 rounded ${STATUS_COLOR[c.status] ?? ""}`}>
            {c.status}
          </span>
          <span className="font-mono text-xs">{c.id.slice(-14)}</span>
          {c.mock_mode && (
            <span className="text-[10px] smallcaps text-[hsl(var(--muted-foreground))]">mock</span>
          )}
          <span className="ml-auto text-xs text-[hsl(var(--muted-foreground))] tabular">
            {c.rounds_taken}r · {fmtTime(c.created_at)}
          </span>
          {c.convergence_reason && (
            <span className="text-[10px] smallcaps opacity-70 hidden md:inline">{c.convergence_reason}</span>
          )}
        </Link>
      ))}
    </div>
  );
}
