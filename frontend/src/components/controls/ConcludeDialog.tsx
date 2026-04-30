"use client";

import { DialogShell, PrimaryButton } from "./_DialogShell";
import { useCaseStore } from "@/lib/stores/caseStore";
import { formatProb } from "@/lib/utils";

export function ConcludeDialog({
  open, onClose, caseId, onConfirm,
}: { open: boolean; onClose: () => void; caseId: string; onConfirm: () => void; }) {
  const top = useCaseStore((s) => s.currentDifferentials[0]);

  return (
    <DialogShell open={open} onClose={onClose} title="Conclude case?">
      <p className="text-sm text-[hsl(var(--muted-foreground))] mb-4">
        Force-conclude this case with the current top differential. The team
        will compile the final report.
      </p>
      {top ? (
        <div className="rounded-md border border-[hsl(var(--border))] p-3 mb-4">
          <p className="text-xs smallcaps text-[hsl(var(--muted-foreground))]">
            Current top differential
          </p>
          <p className="text-base font-bold mt-1">{top.disease}</p>
          <p className="text-sm tabular text-[hsl(var(--muted-foreground))]">
            {formatProb(top.probability, 1)} confidence
          </p>
        </div>
      ) : (
        <p className="text-xs text-amber-500 mb-4">
          No team differential yet — case will conclude with empty report.
        </p>
      )}
      <PrimaryButton onClick={onConfirm}>Conclude with this diagnosis</PrimaryButton>
      <p className="mt-3 text-[10px] text-[hsl(var(--muted-foreground))] text-center font-mono">
        case {caseId.slice(-12)}
      </p>
    </DialogShell>
  );
}
