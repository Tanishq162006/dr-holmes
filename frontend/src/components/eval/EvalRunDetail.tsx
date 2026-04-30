"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getEvalRun, getEvalRunCases } from "@/lib/api";
import { ArrowLeft } from "lucide-react";
import { formatProb, fmtTime } from "@/lib/utils";

export function EvalRunDetail({ runId }: { runId: string }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [cases, setCases] = useState<Array<Record<string, string>>>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getEvalRun(runId), getEvalRunCases(runId)])
      .then(([d, c]) => { setData(d); setCases(c); })
      .catch((e) => setErr(String(e)));
  }, [runId]);

  if (err) return <div className="text-rose-500 text-sm">{err}</div>;
  if (!data) return <div className="animate-pulse h-32 bg-[hsl(var(--muted))] rounded" />;

  const conditions = (data.conditions as Record<string, ConditionMetrics>) ?? {};

  return (
    <div className="space-y-6">
      <Link href="/eval" className="text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] inline-flex items-center gap-1">
        <ArrowLeft size={14} /> Back to runs
      </Link>

      <header>
        <h1 className="text-2xl font-semibold font-mono">{runId}</h1>
      </header>

      {Object.keys(conditions).length > 0 && (
        <section>
          <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))] mb-2">
            Conditions ({Object.keys(conditions).length})
          </h2>
          <div className="rounded-lg border border-[hsl(var(--border))] overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[hsl(var(--muted))]/50 text-xs smallcaps text-[hsl(var(--muted-foreground))]">
                <tr>
                  <th className="text-left px-3 py-2">Condition</th>
                  <th className="text-right px-3 py-2">Top-1</th>
                  <th className="text-right px-3 py-2">Top-3</th>
                  <th className="text-right px-3 py-2">Top-5</th>
                  <th className="text-right px-3 py-2">MRR</th>
                  <th className="text-right px-3 py-2">ECE</th>
                  <th className="text-right px-3 py-2">Brier</th>
                  <th className="text-right px-3 py-2">$/case</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[hsl(var(--border))]">
                {Object.entries(conditions).map(([cond, m]) => (
                  <tr key={cond} className="hover:bg-[hsl(var(--muted))]/30">
                    <td className="px-3 py-2 font-mono text-xs">{cond}</td>
                    <td className="px-3 py-2 text-right tabular">{formatProb(m.top_1_accuracy ?? 0, 1)}</td>
                    <td className="px-3 py-2 text-right tabular">{formatProb(m.top_3_accuracy ?? 0, 1)}</td>
                    <td className="px-3 py-2 text-right tabular">{formatProb(m.top_5_accuracy ?? 0, 1)}</td>
                    <td className="px-3 py-2 text-right tabular">{(m.mean_reciprocal_rank ?? 0).toFixed(3)}</td>
                    <td className="px-3 py-2 text-right tabular">{(m.expected_calibration_error ?? 0).toFixed(3)}</td>
                    <td className="px-3 py-2 text-right tabular">{(m.brier_score ?? 0).toFixed(3)}</td>
                    <td className="px-3 py-2 text-right tabular">${(m.mean_cost_per_case ?? 0).toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {cases.length > 0 && (
        <section>
          <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))] mb-2">
            Per-case results · {cases.length}
          </h2>
          <div className="rounded-lg border border-[hsl(var(--border))] overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-[hsl(var(--muted))]/50 sticky top-0 smallcaps text-[hsl(var(--muted-foreground))]">
                <tr>
                  <th className="text-left px-3 py-2">case</th>
                  <th className="text-left px-3 py-2">condition</th>
                  <th className="text-left px-3 py-2">truth</th>
                  <th className="text-left px-3 py-2">predicted</th>
                  <th className="text-center px-3 py-2">top-1</th>
                  <th className="text-right px-3 py-2">conf</th>
                  <th></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[hsl(var(--border))]">
                {cases.slice(0, 200).map((c, i) => {
                  const correct = c.top_1_correct === "True" || c.top_1_correct === "true";
                  return (
                    <tr key={i} className="hover:bg-[hsl(var(--muted))]/30">
                      <td className="px-3 py-1.5 font-mono text-[11px]">{c.case_id?.slice(-12)}</td>
                      <td className="px-3 py-1.5">{c.condition}</td>
                      <td className="px-3 py-1.5">{c.ground_truth_dx?.slice(0, 30)}</td>
                      <td className="px-3 py-1.5">{c.final_dx?.slice(0, 30)}</td>
                      <td className="px-3 py-1.5 text-center">
                        {correct ? "✓" : "✗"}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular">
                        {parseFloat(c.confidence_at_top_1 ?? "0").toFixed(2)}
                      </td>
                      <td className="px-3 py-1.5">
                        <Link
                          href={`/case/${c.case_id}?replay=true&runId=${runId}`}
                          className="text-violet-500 hover:underline text-[10px]"
                        >
                          replay →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

type ConditionMetrics = {
  top_1_accuracy?: number;
  top_3_accuracy?: number;
  top_5_accuracy?: number;
  mean_reciprocal_rank?: number;
  expected_calibration_error?: number;
  brier_score?: number;
  mean_cost_per_case?: number;
};
