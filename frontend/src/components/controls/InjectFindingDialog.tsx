"use client";

import { useState } from "react";
import { DialogShell, FieldLabel, TextInput, Select, PrimaryButton } from "./_DialogShell";
import { injectEvidence } from "@/lib/api";
import { sendCommand } from "@/lib/ws/client";

const TYPES = ["lab", "imaging", "symptom", "physical_exam", "test_result", "history"] as const;

export function InjectFindingDialog({
  open, onClose, caseId,
}: {
  open: boolean; onClose: () => void; caseId: string;
}) {
  const [type, setType] = useState<typeof TYPES[number]>("lab");
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      sendCommand({
        command: "inject_evidence", case_id: caseId,
        payload: { type, name, value, is_present: true },
      });
      await injectEvidence(caseId, { type, name, value });
      onClose();
      setName(""); setValue("");
    } finally { setBusy(false); }
  }

  return (
    <DialogShell open={open} onClose={onClose} title="Inject finding mid-case">
      <p className="text-xs text-[hsl(var(--muted-foreground))] mb-4">
        Backend handler lands in Phase 6. Phase 5 sends the WS message and
        REST fallback so the wire-up is real, even if the agents don&apos;t
        re-deliberate yet.
      </p>
      <div className="space-y-3">
        <div>
          <FieldLabel>Type</FieldLabel>
          <Select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
        </div>
        <div>
          <FieldLabel>Name</FieldLabel>
          <TextInput value={name} onChange={(e) => setName(e.target.value)}
                     placeholder="e.g., anti-dsDNA" />
        </div>
        <div>
          <FieldLabel>Value</FieldLabel>
          <TextInput value={value} onChange={(e) => setValue(e.target.value)}
                     placeholder="e.g., positive 1:160" />
        </div>
        <PrimaryButton onClick={submit} disabled={!name || !value || busy}>
          Inject
        </PrimaryButton>
      </div>
    </DialogShell>
  );
}
