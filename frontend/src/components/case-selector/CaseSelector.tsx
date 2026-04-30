"use client";

import { useEffect, useState } from "react";
import { listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types/wire";
import { DemoCaseCard, type DemoCase } from "./DemoCaseCard";
import { ActiveCasesList } from "./ActiveCasesList";
import { NewCaseDialog } from "./NewCaseDialog";
import { Plus, Sparkles, FlaskConical, History } from "lucide-react";

const DEMO_CASES: DemoCase[] = [
  {
    id: "case_01_easy_mi",
    fixture: "fixtures/case_01_easy_mi.json",
    title: "58 yo M · crushing chest pain",
    blurb: "Classic anterior STEMI. Team converges quickly.",
    expectedDx: "Anterior STEMI",
    difficulty: "easy",
    rounds: 2,
  },
  {
    id: "case_02_atypical_sle",
    fixture: "fixtures/case_02_atypical_sle.json",
    title: "28 yo F · joint pain, photosensitive rash",
    blurb: "Atypical SLE with renal involvement. Carmen vs Forman debate.",
    expectedDx: "SLE",
    difficulty: "medium",
    rounds: 4,
  },
  {
    id: "case_03_zebra_whipples",
    fixture: "fixtures/case_03_zebra_whipples.json",
    title: "52 yo M · diarrhea, weight loss, arthralgias",
    blurb: "Whipple's disease — Hauser's contrarian zebra is right.",
    expectedDx: "Whipple's disease",
    difficulty: "hard",
    rounds: 5,
  },
];

export function CaseSelector() {
  const [active, setActive] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [newOpen, setNewOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCases({ limit: 20 })
      .then(setActive)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-12">
      {/* Hero */}
      <section className="text-center pt-4 pb-2">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight">
          Six minds, one diagnosis.
        </h1>
        <p className="mt-3 text-sm sm:text-base text-[hsl(var(--muted-foreground))] max-w-xl mx-auto">
          A multi-agent LLM diagnostic deliberation system. Watch the team
          debate, inject findings, and converge — or dissent.
        </p>
        <button
          onClick={() => setNewOpen(true)}
          className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium transition shadow-sm"
        >
          <Plus size={16} />
          Start a new case
        </button>
      </section>

      {/* Demo cases */}
      <section>
        <header className="flex items-baseline gap-3 mb-4">
          <Sparkles size={16} className="text-amber-500" />
          <h2 className="text-lg font-semibold">Demo cases</h2>
          <span className="text-xs text-[hsl(var(--muted-foreground))]">
            mock-mode — no API keys needed, free to run
          </span>
        </header>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {DEMO_CASES.map((d) => (
            <DemoCaseCard key={d.id} demo={d} />
          ))}
        </div>
      </section>

      {/* Active cases */}
      <section>
        <header className="flex items-baseline gap-3 mb-4">
          <History size={16} className="text-blue-500" />
          <h2 className="text-lg font-semibold">Recent cases</h2>
          <span className="text-xs text-[hsl(var(--muted-foreground))]">
            running, paused, or concluded — from the API
          </span>
        </header>
        {error ? (
          <div className="rounded-lg border border-rose-300 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-4 text-sm text-rose-900 dark:text-rose-200">
            <p className="font-medium">Couldn&apos;t reach the API.</p>
            <p className="mt-1 text-xs opacity-80">
              Make sure the backend is running: <code className="font-mono">python3 -m uvicorn dr_holmes.api.main:app</code>
            </p>
          </div>
        ) : (
          <ActiveCasesList cases={active} loading={loading} />
        )}
      </section>

      {/* Eval pointer */}
      <section className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 p-5 flex items-start gap-3">
        <FlaskConical size={18} className="text-violet-500 shrink-0 mt-0.5" />
        <div className="text-sm">
          <p className="font-medium">
            Looking for benchmark numbers?
          </p>
          <p className="text-[hsl(var(--muted-foreground))] mt-1">
            The eval browser shows DDXPlus benchmark runs across 5 baseline
            conditions, with calibration analysis and per-disease breakdown.
          </p>
          <a href="/eval" className="text-violet-500 hover:underline mt-2 inline-block">
            View eval results →
          </a>
        </div>
      </section>

      <NewCaseDialog open={newOpen} onClose={() => setNewOpen(false)} />
    </div>
  );
}
