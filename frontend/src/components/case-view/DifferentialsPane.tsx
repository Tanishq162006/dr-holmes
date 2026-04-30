"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useCaseStore } from "@/lib/stores/caseStore";
import { formatProb, probColor, probBgColor, cn } from "@/lib/utils";
import { useSettingsStore } from "@/lib/stores/settingsStore";
import { ProbabilityBar } from "@/components/differentials/ProbabilityBar";

const interventionIcon: Record<string, string> = {
  inject_evidence: "📋",
  question_agent: "💬",
  correct_agent: "✓",
  conclude_now: "⚠",
  pause: "⏸",
  resume: "▶",
};

function summarizePayload(type: string, payload: Record<string, unknown>): string {
  if (type === "inject_evidence") {
    const name = (payload.name ?? payload.evidence_name ?? "evidence") as string;
    const value = (payload.value ?? payload.evidence_value ?? "?") as string | number;
    return `${name} = ${value}`;
  }
  if (type === "question_agent") {
    const target = (payload.target_agent ?? payload.target ?? "?") as string;
    const q = (payload.question ?? "") as string;
    return q ? `→ ${target}: ${q.slice(0, 60)}${q.length > 60 ? "…" : ""}` : `→ ${target}`;
  }
  if (type === "correct_agent") {
    const target = (payload.target_agent ?? payload.target ?? "?") as string;
    return `→ ${target}`;
  }
  if (type === "conclude_now") return "force-conclude";
  return "";
}

export function DifferentialsPane() {
  const ddx = useCaseStore((s) => s.currentDifferentials);
  const challenges = useCaseStore((s) => s.activeChallenges);
  const finalReport = useCaseStore((s) => s.finalReport);
  const status = useCaseStore((s) => s.status);
  const interventionHistory = useCaseStore((s) => s.interventionHistory);
  const threshold = useSettingsStore((s) => s.convergenceThreshold);
  const [historyOpen, setHistoryOpen] = useState(true);

  const top5 = ddx.slice(0, 5);
  const converged = status === "concluded" && top5[0]?.probability >= threshold;

  return (
    <aside className="bg-[hsl(var(--card))] overflow-y-auto p-5 hidden lg:block space-y-6">
      {/* Differentials */}
      <section>
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))]">
            Live differential
          </h2>
          {converged && (
            <span className="smallcaps text-[10px] text-emerald-500">
              ✓ converged
            </span>
          )}
        </header>

        {top5.length === 0 ? (
          <div className="text-xs text-[hsl(var(--muted-foreground))] py-6 text-center border border-dashed border-[hsl(var(--border))] rounded-md">
            no Bayesian update yet
          </div>
        ) : (
          <ul className="space-y-2.5">
            <AnimatePresence mode="popLayout">
              {top5.map((d, i) => (
                <motion.li
                  key={d.disease}
                  layout
                  initial={{ opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  transition={{ duration: 0.3 }}
                  className={cn(
                    "rounded-md p-2.5",
                    i === 0 && converged && "converged-glow bg-emerald-500/5",
                    i === 0 && !converged && "bg-[hsl(var(--muted))]/40",
                  )}
                >
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <span className="text-xs font-medium leading-tight truncate">
                      {d.disease}
                    </span>
                    <span className={cn("text-xs tabular shrink-0", probColor(d.probability))}>
                      {formatProb(d.probability, 1)}
                    </span>
                  </div>
                  <ProbabilityBar value={d.probability} />
                  {d.proposed_by && (
                    <p className="mt-1 text-[10px] text-[hsl(var(--muted-foreground))] truncate">
                      proposed by {d.proposed_by}
                    </p>
                  )}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </section>

      {/* Active challenges */}
      <section>
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))]">
            Open challenges
          </h2>
          {challenges.length > 0 && (
            <span className="text-[10px] tabular text-amber-500">{challenges.length}</span>
          )}
        </header>
        {challenges.length === 0 ? (
          <p className="text-xs text-[hsl(var(--muted-foreground))]">No unresolved challenges.</p>
        ) : (
          <ul className="space-y-1.5">
            {challenges.map((c, i) => (
              <li key={i} className="text-xs flex items-start gap-1.5 px-2 py-1.5 rounded bg-amber-500/10 border border-amber-500/30">
                <span className="text-amber-500">⚡</span>
                <span>
                  <span className="font-medium">→ {c.target_agent}</span>
                  <span className="block text-[11px] mt-0.5 italic text-[hsl(var(--muted-foreground))]">
                    {c.content}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Intervention history */}
      <section>
        <button
          type="button"
          onClick={() => setHistoryOpen((o) => !o)}
          className="w-full flex items-baseline justify-between mb-2 text-left"
        >
          <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))]">
            Intervention history
          </h2>
          <span className="flex items-center gap-2">
            {interventionHistory.length > 0 && (
              <span className="text-[10px] tabular text-[hsl(var(--muted-foreground))]">
                {interventionHistory.length}
              </span>
            )}
            <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
              {historyOpen ? "▾" : "▸"}
            </span>
          </span>
        </button>
        {historyOpen && (
          interventionHistory.length === 0 ? (
            <p className="text-xs text-[hsl(var(--muted-foreground))]">No interventions yet.</p>
          ) : (
            <ul className="space-y-1.5">
              {interventionHistory.map((h) => {
                const failed = !h.applied;
                const summary = summarizePayload(h.type, h.payload);
                const ts = new Date(h.timestamp);
                const tsStr = isNaN(ts.getTime())
                  ? h.timestamp
                  : ts.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
                return (
                  <li
                    key={h.intervention_id}
                    className={cn(
                      "text-xs flex items-start gap-1.5 px-2 py-1.5 rounded border",
                      failed
                        ? "bg-rose-500/10 border-rose-500/40 text-rose-500"
                        : "bg-[hsl(var(--muted))]/30 border-[hsl(var(--border))]",
                    )}
                  >
                    <span aria-hidden>{interventionIcon[h.type] ?? "•"}</span>
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{h.type.replace(/_/g, " ")}</span>
                      {summary && (
                        <span className="block text-[11px] mt-0.5 italic text-[hsl(var(--muted-foreground))] truncate">
                          {summary}
                        </span>
                      )}
                      {failed && h.failure_reason && (
                        <span className="block text-[11px] mt-0.5 italic">
                          failed: {h.failure_reason}
                        </span>
                      )}
                      <span className="block text-[10px] tabular text-[hsl(var(--muted-foreground))] mt-0.5">
                        {tsStr}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )
        )}
      </section>

      {/* Final report summary */}
      {finalReport && (
        <section className="pt-4 border-t border-[hsl(var(--border))]">
          <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))] mb-2">
            Final report
          </h2>
          <p className="text-sm font-bold">{finalReport.consensus_dx}</p>
          <p className="text-xs tabular text-[hsl(var(--muted-foreground))]">
            {formatProb(finalReport.confidence)} confidence · {finalReport.rounds_taken} rounds
          </p>
          <p className="text-[11px] smallcaps text-[hsl(var(--muted-foreground))] mt-1">
            via {finalReport.convergence_reason}
          </p>
          {finalReport.recommended_workup.length > 0 && (
            <div className="mt-3">
              <h3 className="text-[10px] smallcaps text-[hsl(var(--muted-foreground))] mb-1">
                Recommended workup
              </h3>
              <ul className="space-y-1 text-xs">
                {finalReport.recommended_workup.slice(0, 5).map((t, i) => (
                  <li key={i}>· {t.test_name}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </aside>
  );
}
