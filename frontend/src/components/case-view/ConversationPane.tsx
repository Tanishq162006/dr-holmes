"use client";

import { useCaseStore } from "@/lib/stores/caseStore";
import { useSettingsStore } from "@/lib/stores/settingsStore";
import { AgentMessage } from "@/components/conversation/AgentMessage";
import { RoundDivider } from "@/components/conversation/RoundDivider";
import { CaddickRoutingNote } from "@/components/conversation/CaddickRoutingNote";
import { DissentPanel } from "@/components/conversation/DissentPanel";
import { useMemo } from "react";
import type { WSEvent, AgentResponse } from "@/lib/types/wire";

export function ConversationPane() {
  const events = useCaseStore((s) => s.events);
  const finalReport = useCaseStore((s) => s.finalReport);
  const showThinking = useSettingsStore((s) => s.showAgentThinking);

  const items = useMemo(() => buildItems(events, showThinking), [events, showThinking]);

  return (
    <main className="overflow-y-auto bg-[hsl(var(--background))]">
      <div className="max-w-3xl mx-auto px-6 py-8">
        <h2 className="smallcaps text-xs text-[hsl(var(--muted-foreground))] mb-4">
          Deliberation
        </h2>

        {events.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-1">
            {items.map((it, i) => {
              if (it.kind === "round") {
                return <RoundDivider key={i} round={it.round} tokenCount={it.tokenCount} />;
              }
              if (it.kind === "agent") {
                return <AgentMessage key={i} agent={it.agent} response={it.response} />;
              }
              if (it.kind === "caddick") {
                return (
                  <CaddickRoutingNote
                    key={i}
                    nextSpeakers={it.nextSpeakers}
                    reason={it.reason}
                    synthesis={it.synthesis}
                  />
                );
              }
              return null;
            })}
            {finalReport?.hauser_dissent && (
              <DissentPanel dissent={finalReport.hauser_dissent} />
            )}
          </div>
        )}
      </div>
    </main>
  );
}

type Item =
  | { kind: "round"; round: number; tokenCount?: number }
  | { kind: "agent"; agent: string; response: AgentResponse }
  | { kind: "caddick"; nextSpeakers: string[]; reason: string; synthesis: string };

function buildItems(events: WSEvent[], showThinking: boolean): Item[] {
  const items: Item[] = [];
  for (const ev of events) {
    if (ev.event_type === "round_started") {
      const p = ev.payload as { round_number: number };
      items.push({ kind: "round", round: p.round_number });
    } else if (ev.event_type === "agent_response") {
      const p = ev.payload as { agent_name: string; response: AgentResponse };
      items.push({ kind: "agent", agent: p.agent_name, response: p.response });
    } else if (ev.event_type === "caddick_routing") {
      const p = ev.payload as { next_speakers: string[]; routing_reason: string; synthesis_text: string };
      items.push({
        kind: "caddick",
        nextSpeakers: p.next_speakers,
        reason: p.routing_reason,
        synthesis: p.synthesis_text,
      });
    }
    // showThinking: would render agent_thinking events here. Phase 5 omits
    // for noise reduction.
    void showThinking;
  }
  return items;
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse mb-4" />
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        Awaiting Round 1
      </p>
      <p className="text-[11px] text-[hsl(var(--muted-foreground))] mt-1 opacity-70">
        Specialists will respond in parallel once the case is intake-complete.
      </p>
    </div>
  );
}
