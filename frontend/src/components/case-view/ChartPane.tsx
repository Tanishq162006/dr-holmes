"use client";

import { useCaseStore } from "@/lib/stores/caseStore";
import { ChevronRight } from "lucide-react";

export function ChartPane() {
  const patient = useCaseStore((s) => s.patient);

  return (
    <aside className="bg-[hsl(var(--card))] overflow-y-auto p-5 hidden lg:block">
      <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))] mb-3">
        Patient chart
      </h2>

      {!patient ? (
        <div className="text-sm text-[hsl(var(--muted-foreground))]">
          Loading patient data...
        </div>
      ) : (
        <div className="space-y-4 text-sm">
          <Section label="Chief complaint">
            <p className="leading-relaxed">{patient.presenting_complaint || "—"}</p>
          </Section>

          {patient.history && (
            <Section label="HPI / History">
              <p className="leading-relaxed text-[hsl(var(--muted-foreground))]">
                {patient.history}
              </p>
            </Section>
          )}

          {Object.keys(patient.vitals ?? {}).length > 0 && (
            <Section label="Vitals">
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 tabular text-xs">
                {Object.entries(patient.vitals!).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-[hsl(var(--muted-foreground))]">{k}</dt>
                    <dd className="font-mono">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </Section>
          )}

          {Object.keys(patient.labs ?? {}).length > 0 && (
            <Section label="Labs">
              <dl className="space-y-1 tabular text-xs">
                {Object.entries(patient.labs!).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-[hsl(var(--muted-foreground))]">{k}</dt>
                    <dd className="font-mono">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </Section>
          )}

          {(patient.medications ?? []).length > 0 && (
            <Section label="Medications">
              <ul className="space-y-1 text-xs">
                {patient.medications!.map((m, i) => (
                  <li key={i} className="flex items-start gap-1">
                    <ChevronRight size={12} className="mt-0.5 shrink-0 opacity-50" />
                    {m}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {(patient.additional_findings ?? []).length > 0 && (
            <Section label="Additional findings">
              <ul className="space-y-1 text-xs">
                {patient.additional_findings!.map((f, i) => (
                  <li key={i} className="flex items-start gap-1">
                    <ChevronRight size={12} className="mt-0.5 shrink-0 opacity-50" />
                    {f}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <div className="pt-3 mt-3 border-t border-[hsl(var(--border))] text-[11px] text-[hsl(var(--muted-foreground))]">
            Edits while running require a pause first.<br />
            Use <strong>Inject finding</strong> below to add data mid-case.
          </div>
        </div>
      )}
    </aside>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="smallcaps text-[10px] text-[hsl(var(--muted-foreground))] mb-1.5">{label}</h3>
      {children}
    </section>
  );
}
