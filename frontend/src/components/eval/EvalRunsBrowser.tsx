"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listEvalRuns } from "@/lib/api";
import { fmtTime, formatProb } from "@/lib/utils";
import { FlaskConical } from "lucide-react";

type RunRow = Awaited<ReturnType<typeof listEvalRuns>>[number];

export function EvalRunsBrowser() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listEvalRuns().then(setRuns).catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <div className="flex items-center gap-2 text-violet-500 text-sm smallcaps mb-1">
          <FlaskConical size={16} /> Eval runs
        </div>
        <h1 className="text-2xl font-semibold">Benchmark history</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
          DDXPlus benchmark runs, baseline comparisons, calibration analysis.
          Generate a new run with{" "}
          <code className="text-xs bg-[hsl(var(--muted))] px-1.5 py-0.5 rounded">
            python3 -m dr_holmes.eval --tier standard --all-conditions --budget 25
          </code>
        </p>
      </header>

      {err && (
        <div className="rounded-lg border border-rose-300 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-4 text-sm text-rose-900 dark:text-rose-200">
          Couldn&apos;t reach the API: {err}
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-20 rounded-md bg-[hsl(var(--muted))] animate-pulse" />
          ))}
        </div>
      ) : runs.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-[hsl(var(--border))] rounded-lg">
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            No eval runs yet. Run a smoke test:
          </p>
          <code className="block mt-3 text-xs bg-[hsl(var(--muted))] inline-block px-3 py-1.5 rounded font-mono">
            python3 -m dr_holmes.eval --tier smoke --conditions full_team --full-team-mock-fixture fixtures/case_01_easy_mi.json
          </code>
        </div>
      ) : (
        <div className="rounded-lg border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))]">
          {runs.map((r) => (
            <Link
              key={r.run_id}
              href={`/eval/${r.run_id}`}
              className="flex items-center gap-4 px-4 py-3 hover:bg-[hsl(var(--muted))]/40 transition"
            >
              <div className="flex-1 min-w-0">
                <p className="font-mono text-sm">{r.run_id}</p>
                <p className="text-[11px] text-[hsl(var(--muted-foreground))] tabular">
                  {r.timestamp ? fmtTime(r.timestamp) : "—"} · {r.n_cases_completed} cases
                </p>
              </div>
              {r.is_multi_condition ? (
                <span className="text-[10px] smallcaps px-2 py-0.5 rounded bg-violet-500/10 text-violet-500">
                  multi-condition
                </span>
              ) : (
                <>
                  {r.top_1_accuracy !== undefined && (
                    <div className="text-xs tabular text-right">
                      <p className="font-medium">{formatProb(r.top_1_accuracy)}</p>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))]">top-1</p>
                    </div>
                  )}
                  {r.total_cost_usd !== undefined && (
                    <div className="text-xs tabular text-right">
                      <p>${r.total_cost_usd.toFixed(2)}</p>
                      <p className="text-[10px] text-[hsl(var(--muted-foreground))]">cost</p>
                    </div>
                  )}
                </>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
