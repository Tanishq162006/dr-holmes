"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createCase } from "@/lib/api";
import { useCaseStore } from "@/lib/stores/caseStore";
import { Loader2, Play } from "lucide-react";

export type DemoCase = {
  id: string;
  fixture: string;
  title: string;
  blurb: string;
  expectedDx: string;
  difficulty: "easy" | "medium" | "hard";
  rounds: number;
};

const DIFF_COLOR: Record<DemoCase["difficulty"], string> = {
  easy: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10",
  medium: "text-amber-600 dark:text-amber-400 bg-amber-500/10",
  hard: "text-rose-600 dark:text-rose-400 bg-rose-500/10",
};

export function DemoCaseCard({ demo }: { demo: DemoCase }) {
  const router = useRouter();
  const reset = useCaseStore((s) => s.resetCase);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function start() {
    setLoading(true);
    setErr(null);
    try {
      reset();
      const created = await createCase({
        patient_presentation: { presenting_complaint: demo.title } as never,
        mock_mode: true,
        fixture_path: demo.fixture,
      });
      router.push(`/case/${created.id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="group relative rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 hover:border-rose-500/40 transition flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5">
          <h3 className="font-medium leading-tight">{demo.title}</h3>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{demo.blurb}</p>
        </div>
        <span className={`text-[10px] smallcaps px-2 py-0.5 rounded ${DIFF_COLOR[demo.difficulty]}`}>
          {demo.difficulty}
        </span>
      </div>

      <div className="mt-4 flex items-center justify-between text-[11px] tabular text-[hsl(var(--muted-foreground))]">
        <span>expected: <span className="text-[hsl(var(--foreground))]">{demo.expectedDx}</span></span>
        <span>{demo.rounds} rounds</span>
      </div>

      <button
        onClick={start}
        disabled={loading}
        className="mt-4 w-full py-2 rounded-md bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white text-xs font-medium transition flex items-center justify-center gap-1.5"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={12} />}
        Run mock deliberation
      </button>

      {err && <p className="mt-2 text-[10px] text-rose-500">{err}</p>}
    </div>
  );
}
