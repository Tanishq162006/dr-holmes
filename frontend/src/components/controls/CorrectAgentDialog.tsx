"use client";

import { useState } from "react";
import { DialogShell, FieldLabel, Select, TextArea, PrimaryButton } from "./_DialogShell";
import { sendCommand } from "@/lib/ws/client";
import { AGENT_NAMES } from "@/lib/types/wire";

export function CorrectAgentDialog({
  open, onClose, caseId,
}: { open: boolean; onClose: () => void; caseId: string; }) {
  const [agent, setAgent] = useState<string>(AGENT_NAMES[0]);
  const [correction, setCorrection] = useState("");

  function submit() {
    sendCommand({
      command: "correct_agent", case_id: caseId,
      payload: { target: agent, correction },
    });
    onClose();
    setCorrection("");
  }

  return (
    <DialogShell open={open} onClose={onClose} title="Correct an agent">
      <p className="text-xs text-[hsl(var(--muted-foreground))] mb-3">
        Inject a fact correction. The targeted agent will be re-prompted
        next round (Phase 6 handler).
      </p>
      <div className="space-y-3">
        <div>
          <FieldLabel>Agent</FieldLabel>
          <Select value={agent} onChange={(e) => setAgent(e.target.value)}>
            {AGENT_NAMES.map((n) => <option key={n} value={n}>Dr. {n}</option>)}
          </Select>
        </div>
        <div>
          <FieldLabel>Correction</FieldLabel>
          <TextArea
            value={correction} onChange={(e) => setCorrection(e.target.value)} rows={4}
            placeholder='e.g., "ANCA is negative — you misread the panel"'
          />
        </div>
        <PrimaryButton onClick={submit} disabled={!correction.trim()}>Send correction</PrimaryButton>
      </div>
    </DialogShell>
  );
}
