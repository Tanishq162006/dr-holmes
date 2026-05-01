"use client";

import { useState } from "react";
import { Plus, X, Send, Lock } from "lucide-react";
import { useCaseStore } from "@/lib/stores/caseStore";
import { submitFollowup, finalizeCase, type FollowupFinding } from "@/lib/api";

const TYPES: FollowupFinding["type"][] = [
  "lab", "imaging", "treatment_response", "symptom", "physical_exam", "test_result", "history",
];

export function AddFindingsPanel({ caseId, isLive }: { caseId: string; isLive: boolean }) {
  const status = useCaseStore((s) => s.status);
  const [findings, setFindings] = useState<FollowupFinding[]>([
    { type: "lab", name: "", value: "" },
  ]);
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Only show when case is concluded (reversible state) — not when running, paused, or finalized
  if (status !== "concluded" && status !== "errored") return null;

  const update = (i: number, patch: Partial<FollowupFinding>) => {
    setFindings((arr) => arr.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  };
  const remove = (i: number) => {
    setFindings((arr) => (arr.length > 1 ? arr.filter((_, j) => j !== i) : arr));
  };
  const add = () => {
    setFindings((arr) => [...arr, { type: "lab", name: "", value: "" }]);
  };

  const validFindings = findings.filter((f) => f.name.trim() && f.value.trim());

  async function submit() {
    setErr(null);
    setSubmitting(true);
    try {
      await submitFollowup(caseId, validFindings, question.trim() || undefined, undefined, isLive);
      setFindings([{ type: "lab", name: "", value: "" }]);
      setQuestion("");
    } catch (e) {
      setErr(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function finalize() {
    if (!confirm("Finalize this case? This permanently locks the report. The doctor's signoff.")) return;
    setFinalizing(true);
    setErr(null);
    try {
      await finalizeCase(caseId);
    } catch (e) {
      setErr(String(e));
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <section className="mt-4 pt-4 border-t-2 border-rose-500/30">
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="smallcaps text-xs text-rose-500 font-semibold">
          Add findings · continue deliberation
        </h2>
        <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
          AI awaits new info
        </span>
      </header>

      <div className="space-y-2">
        {findings.map((f, i) => (
          <div key={i} className="flex gap-1.5 items-start">
            <select
              value={f.type}
              onChange={(e) => update(i, { type: e.target.value as FollowupFinding["type"] })}
              className="px-1.5 py-1 text-[11px] bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))]"
            >
              {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <input
              value={f.name}
              onChange={(e) => update(i, { name: e.target.value })}
              placeholder="name (e.g. BMP)"
              className="flex-1 px-2 py-1 text-[11px] bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30 min-w-0"
            />
            <input
              value={f.value}
              onChange={(e) => update(i, { value: e.target.value })}
              placeholder="value (e.g. Na 132, BUN 35)"
              className="flex-[2] px-2 py-1 text-[11px] bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30 min-w-0"
            />
            <button
              onClick={() => remove(i)}
              disabled={findings.length === 1}
              className="p-1 text-[hsl(var(--muted-foreground))] hover:text-rose-500 disabled:opacity-30"
              aria-label="Remove"
            >
              <X size={12} />
            </button>
          </div>
        ))}

        <button
          onClick={add}
          className="text-[11px] text-rose-500 hover:underline flex items-center gap-1"
        >
          <Plus size={11} /> add another
        </button>

        <div className="pt-2">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
            placeholder="Optional: a question for the team (e.g. 'patient improved on fluids — confirm dehydration?')"
            className="w-full px-2 py-1.5 text-[11px] bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30 resize-none"
          />
        </div>

        {err && <p className="text-[10px] text-rose-500 break-words">{err}</p>}

        <div className="flex flex-col gap-1.5">
          <button
            onClick={submit}
            disabled={submitting || finalizing || validFindings.length === 0}
            className="w-full py-1.5 rounded-md bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white text-xs font-medium transition flex items-center justify-center gap-1.5"
          >
            <Send size={12} />
            {submitting ? "Re-deliberating..." : `Submit ${validFindings.length} finding${validFindings.length === 1 ? "" : "s"} · continue`}
          </button>

          <button
            onClick={finalize}
            disabled={submitting || finalizing}
            className="w-full py-1.5 rounded-md bg-[hsl(var(--muted))] hover:bg-[hsl(var(--muted))]/70 disabled:opacity-40 text-[hsl(var(--foreground))] text-xs font-medium transition flex items-center justify-center gap-1.5 border border-[hsl(var(--border))]"
            title="Permanently lock the case with the current report. Doctor signoff."
          >
            <Lock size={12} />
            {finalizing ? "Finalizing..." : "Finalize case (lock)"}
          </button>
        </div>
      </div>
    </section>
  );
}
