"use client";

import { useState, useEffect } from "react";
import { Pause, Play, MessageSquarePlus, HelpCircle, Edit3, Target } from "lucide-react";
import { useCaseStore } from "@/lib/stores/caseStore";
import { sendCommand } from "@/lib/ws/client";
import { pauseCase, resumeCase, concludeCase } from "@/lib/api";
import { InjectFindingDialog } from "./InjectFindingDialog";
import { QuestionAgentDialog } from "./QuestionAgentDialog";
import { CorrectAgentDialog } from "./CorrectAgentDialog";
import { ConcludeDialog } from "./ConcludeDialog";

export function ControlBar() {
  const caseId = useCaseStore((s) => s.caseId);
  const status = useCaseStore((s) => s.status);
  const isReplay = useCaseStore((s) => s.isReplay);

  const [inject, setInject] = useState(false);
  const [question, setQuestion] = useState(false);
  const [correct, setCorrect] = useState(false);
  const [conclude, setConclude] = useState(false);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)) return;
      if (e.key === " ")          { e.preventDefault(); togglePause(); }
      else if (e.key === "i")     { setInject(true); }
      else if (e.key === "q")     { setQuestion(true); }
      else if (e.key === "c")     { setCorrect(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, caseId]);

  const concluded = status === "concluded" || status === "errored";
  const paused = status === "paused";

  async function togglePause() {
    if (!caseId || concluded || isReplay) return;
    if (paused) {
      sendCommand({ command: "resume", case_id: caseId, payload: {} });
      await resumeCase(caseId);
    } else {
      sendCommand({ command: "pause", case_id: caseId, payload: {} });
      await pauseCase(caseId);
    }
  }

  if (!caseId) return null;

  return (
    <>
      <footer className="border-t border-[hsl(var(--border))] bg-[hsl(var(--card))]/95 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 py-2.5 flex items-center gap-2 overflow-x-auto">
          <ControlButton
            icon={paused ? Play : Pause}
            label={paused ? "Resume" : "Pause"}
            shortcut="space"
            onClick={togglePause}
            disabled={concluded || isReplay}
          />
          <ControlButton
            icon={MessageSquarePlus}
            label="Inject finding"
            shortcut="i"
            onClick={() => setInject(true)}
            disabled={concluded || isReplay}
          />
          <ControlButton
            icon={HelpCircle}
            label="Ask agent"
            shortcut="q"
            onClick={() => setQuestion(true)}
            disabled={concluded || isReplay}
          />
          <ControlButton
            icon={Edit3}
            label="Correct agent"
            shortcut="c"
            onClick={() => setCorrect(true)}
            disabled={concluded || isReplay}
          />
          <div className="ml-auto" />
          <ControlButton
            icon={Target}
            label="Conclude"
            onClick={() => setConclude(true)}
            disabled={concluded || isReplay}
            primary
          />
          {isReplay && (
            <span className="text-[10px] smallcaps text-violet-500 px-2 ml-2">replay · controls disabled</span>
          )}
        </div>
      </footer>

      <InjectFindingDialog open={inject} onClose={() => setInject(false)} caseId={caseId} />
      <QuestionAgentDialog open={question} onClose={() => setQuestion(false)} caseId={caseId} />
      <CorrectAgentDialog open={correct} onClose={() => setCorrect(false)} caseId={caseId} />
      <ConcludeDialog
        open={conclude}
        onClose={() => setConclude(false)}
        caseId={caseId}
        onConfirm={async () => {
          if (caseId) {
            sendCommand({ command: "conclude_now", case_id: caseId, payload: {} });
            await concludeCase(caseId);
          }
          setConclude(false);
        }}
      />
    </>
  );
}

function ControlButton({
  icon: Icon, label, shortcut, onClick, disabled, primary,
}: {
  icon: React.ComponentType<{ size?: number }>;
  label: string;
  shortcut?: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition shrink-0 ${
        primary
          ? "bg-rose-600 hover:bg-rose-700 text-white disabled:opacity-40"
          : "bg-[hsl(var(--muted))] hover:bg-[hsl(var(--muted))]/70 disabled:opacity-40"
      }`}
    >
      <Icon size={14} />
      <span>{label}</span>
      {shortcut && (
        <kbd className="ml-1 text-[9px] opacity-50 font-mono uppercase">{shortcut}</kbd>
      )}
    </button>
  );
}
