"use client";

import { useState } from "react";
import { DialogShell, FieldLabel, Select, TextArea, PrimaryButton } from "./_DialogShell";
import { sendCommand } from "@/lib/ws/client";
import { AGENT_NAMES } from "@/lib/types/wire";

export function QuestionAgentDialog({
  open, onClose, caseId,
}: { open: boolean; onClose: () => void; caseId: string; }) {
  const [agent, setAgent] = useState<string>(AGENT_NAMES[0]);
  const [question, setQuestion] = useState("");

  function submit() {
    sendCommand({
      command: "question_agent", case_id: caseId,
      payload: { target: agent, question },
    });
    onClose();
    setQuestion("");
  }

  return (
    <DialogShell open={open} onClose={onClose} title="Ask an agent">
      <div className="space-y-3">
        <div>
          <FieldLabel>Agent</FieldLabel>
          <Select value={agent} onChange={(e) => setAgent(e.target.value)}>
            {AGENT_NAMES.map((n) => <option key={n} value={n}>Dr. {n}</option>)}
          </Select>
        </div>
        <div>
          <FieldLabel>Question</FieldLabel>
          <TextArea
            value={question} onChange={(e) => setQuestion(e.target.value)} rows={4}
            placeholder="e.g., Why are you weighting SLE so heavily over MCTD?"
          />
        </div>
        <PrimaryButton onClick={submit} disabled={!question.trim()}>Send question</PrimaryButton>
      </div>
    </DialogShell>
  );
}
