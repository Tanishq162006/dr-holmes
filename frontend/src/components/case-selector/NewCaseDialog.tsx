"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createCase } from "@/lib/api";
import { X, Loader2 } from "lucide-react";

const DEMO_FIXTURES = [
  { value: "", label: "(none — live deliberation)" },
  { value: "fixtures/case_01_easy_mi.json", label: "case_01 — STEMI" },
  { value: "fixtures/case_02_atypical_sle.json", label: "case_02 — SLE" },
  { value: "fixtures/case_03_zebra_whipples.json", label: "case_03 — Whipple's" },
];

export function NewCaseDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [chief, setChief] = useState("");
  const [hpi, setHpi] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState<"M" | "F" | "other">("other");
  const [mock, setMock] = useState(true);
  const [fixture, setFixture] = useState("fixtures/case_01_easy_mi.json");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setLoading(true);
    setErr(null);
    try {
      const created = await createCase({
        patient_presentation: {
          presenting_complaint: chief,
          history: hpi,
          vitals: {},
          labs: {},
          imaging: {},
          medications: [],
          allergies: [],
          additional_findings: age ? [`Age: ${age}`, `Sex: ${sex}`] : [],
        },
        mock_mode: mock,
        fixture_path: mock ? fixture : null,
      });
      onClose();
      router.push(`/case/${created.id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[92vw] max-w-md bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-6 shadow-2xl focus:outline-none">
          <div className="flex items-center justify-between">
            <Dialog.Title className="font-semibold">New case</Dialog.Title>
            <button onClick={onClose} className="p-1 rounded hover:bg-[hsl(var(--muted))]">
              <X size={16} />
            </button>
          </div>

          <div className="mt-4 space-y-4 text-sm">
            <Field label="Chief complaint" required>
              <input
                value={chief}
                onChange={(e) => setChief(e.target.value)}
                placeholder="e.g., 4-week history of joint pain and rash"
                className="w-full px-3 py-2 bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30"
              />
            </Field>
            <Field label="HPI / history">
              <textarea
                value={hpi}
                onChange={(e) => setHpi(e.target.value)}
                rows={3}
                placeholder="Onset, prior workup, relevant history..."
                className="w-full px-3 py-2 bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30 resize-none"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Age">
                <input
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                  type="number"
                  className="w-full px-3 py-2 bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))]"
                />
              </Field>
              <Field label="Sex">
                <select
                  value={sex}
                  onChange={(e) => setSex(e.target.value as "M" | "F" | "other")}
                  className="w-full px-3 py-2 bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))]"
                >
                  <option value="other">other</option>
                  <option value="M">M</option>
                  <option value="F">F</option>
                </select>
              </Field>
            </div>

            <div className="rounded-lg bg-[hsl(var(--muted))]/50 p-3 space-y-2">
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} />
                Mock mode (free, deterministic)
              </label>
              {mock && (
                <select
                  value={fixture}
                  onChange={(e) => setFixture(e.target.value)}
                  className="w-full px-2 py-1.5 text-xs font-mono bg-[hsl(var(--card))] rounded border border-[hsl(var(--border))]"
                >
                  {DEMO_FIXTURES.filter((f) => f.value).map((f) => (
                    <option key={f.value} value={f.value}>{f.label}</option>
                  ))}
                </select>
              )}
              {!mock && (
                <p className="text-[11px] text-amber-600 dark:text-amber-400">
                  Live mode requires OPENAI_API_KEY + XAI_API_KEY in backend.
                </p>
              )}
            </div>

            {err && <p className="text-xs text-rose-500">{err}</p>}

            <button
              onClick={submit}
              disabled={!chief.trim() || loading}
              className="w-full py-2 rounded-md bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white text-sm font-medium transition flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : null}
              Start deliberation
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium">
        {label}
        {required && <span className="text-rose-500 ml-0.5">*</span>}
      </span>
      {children}
    </label>
  );
}
