"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { useSettingsStore } from "@/lib/stores/settingsStore";

export function DisclaimerModal() {
  const seen = useSettingsStore((s) => s.hasSeenDisclaimer);
  const setSeen = useSettingsStore((s) => s.setHasSeenDisclaimer);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) return null;

  return (
    <Dialog.Root open={!seen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[92vw] max-w-lg bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-6 shadow-2xl focus:outline-none"
          onEscapeKeyDown={(e) => e.preventDefault()}
          onPointerDownOutside={(e) => e.preventDefault()}
        >
          <Dialog.Title className="text-lg font-semibold flex items-center gap-2">
            <span className="text-amber-500">⚠</span> Before you proceed
          </Dialog.Title>
          <Dialog.Description className="mt-3 text-sm text-[hsl(var(--muted-foreground))] space-y-3">
            <p>
              <strong className="text-[hsl(var(--foreground))]">Dr. Holmes</strong> is an
              educational research project. The diagnoses produced by these AI agents are
              <strong className="text-[hsl(var(--foreground))]"> simulation only</strong>.
            </p>
            <ul className="list-disc list-inside space-y-1 text-xs">
              <li>NOT a medical device. NOT FDA-approved.</li>
              <li>NOT for clinical use. NOT a substitute for medical advice.</li>
              <li>Not affiliated with any television production.</li>
              <li>Do not enter real patient data. Use synthetic / fictional cases only.</li>
            </ul>
          </Dialog.Description>
          <button
            onClick={() => setSeen(true)}
            className="mt-5 w-full py-2 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium transition"
          >
            I understand — proceed
          </button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
