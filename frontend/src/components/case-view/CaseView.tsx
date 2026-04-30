"use client";

import { useEffect } from "react";
import { useCaseStore } from "@/lib/stores/caseStore";
import { startCaseStream, stopCaseStream } from "@/lib/ws/client";
import { getCase, getEvalCaseEvents } from "@/lib/api";
import { ChartPane } from "./ChartPane";
import { ConversationPane } from "./ConversationPane";
import { DifferentialsPane } from "./DifferentialsPane";
import { ControlBar } from "@/components/controls/ControlBar";

export function CaseView({
  caseId,
  replay = false,
  evalRunId,
}: {
  caseId: string;
  replay?: boolean;
  evalRunId?: string;
}) {
  const setCaseId = useCaseStore((s) => s.setCaseId);
  const setIsReplay = useCaseStore((s) => s.setIsReplay);
  const reset = useCaseStore((s) => s.resetCase);
  const ingestEvents = useCaseStore((s) => s.ingestEvents);

  useEffect(() => {
    reset();
    setCaseId(caseId);
    setIsReplay(replay);

    let cancelled = false;
    (async () => {
      // Hydrate patient data via REST (the WS doesn't carry the full chart)
      try {
        const detail = await getCase(caseId);
        if (cancelled) return;
        useCaseStore.setState({
          patient: detail.patient_presentation,
          status: detail.status,
        });
        if (detail.final_report) {
          useCaseStore.setState({ finalReport: detail.final_report });
        }
      } catch {
        // Eval-replay cases may not exist in the cases table; that's OK
      }

      // If this is an eval-run replay, fetch events from the eval endpoint
      if (replay && evalRunId) {
        try {
          const events = await getEvalCaseEvents(evalRunId, caseId);
          if (!cancelled) ingestEvents(events);
        } catch (e) {
          console.warn("eval replay fetch failed:", e);
        }
        return;
      }

      // Otherwise: live or normal-replay via WebSocket
      startCaseStream(caseId, replay);
    })();

    return () => {
      cancelled = true;
      stopCaseStream();
    };
  }, [caseId, replay, evalRunId, setCaseId, setIsReplay, reset, ingestEvents]);

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex-1 grid lg:grid-cols-[320px_1fr_360px] xl:grid-cols-[360px_1fr_400px] divide-x divide-[hsl(var(--border))] min-h-0">
        <ChartPane />
        <ConversationPane />
        <DifferentialsPane />
      </div>
      <ControlBar />
    </div>
  );
}
