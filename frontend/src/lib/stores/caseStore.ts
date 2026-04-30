/**
 * Ephemeral case state. Never persisted — case state lives in events[]
 * and is restored on reconnect via WS replay (?from_sequence=N).
 */
import { create } from "zustand";
import type {
  WSEvent, AgentResponse, TeamDifferential, Challenge, FinalReport,
  CaseStatus, PatientPresentation, AgentName,
} from "@/lib/types/wire";

export type Round = {
  round_number: number;
  speakers: AgentName[];
  events: WSEvent[];
};

type WSState = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected";

export type InterventionHistoryEntry = {
  intervention_id: string;
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
  applied: boolean;
  failure_reason?: string | null;
};

export type EvidenceConflictEntry = {
  name: string;
  prev_value: string;
  new_value: string;
};

interface CaseStoreState {
  // Identity
  caseId: string | null;
  status: CaseStatus | "idle";
  patient: PatientPresentation | null;

  // Event log
  events: WSEvent[];
  lastSequence: number;

  // Derived (rebuilt on each ingest)
  agentResponses: Record<string, AgentResponse[]>;
  caddickHistory: Array<{
    round: number;
    next_speakers: string[];
    routing_reason: string;
    synthesis_text: string;
  }>;
  currentDifferentials: TeamDifferential[];
  activeChallenges: Challenge[];
  finalReport: FinalReport | null;
  rounds: Round[];

  // Phase 6: HITL
  interventionHistory: InterventionHistoryEntry[];
  evidenceConflicts: EvidenceConflictEntry[];

  // WS connection
  wsState: WSState;
  wsRetryCount: number;
  isReplay: boolean;

  // Actions
  setCaseId: (id: string | null) => void;
  setIsReplay: (replay: boolean) => void;
  setWSState: (s: WSState) => void;
  bumpRetry: () => void;
  resetCase: () => void;
  ingestEvent: (ev: WSEvent) => void;
  ingestEvents: (evs: WSEvent[]) => void;
}

export const useCaseStore = create<CaseStoreState>((set, get) => ({
  caseId: null,
  status: "idle",
  patient: null,
  events: [],
  lastSequence: 0,
  agentResponses: {},
  caddickHistory: [],
  currentDifferentials: [],
  activeChallenges: [],
  finalReport: null,
  rounds: [],
  interventionHistory: [],
  evidenceConflicts: [],
  wsState: "idle",
  wsRetryCount: 0,
  isReplay: false,

  setCaseId: (id) => set({ caseId: id }),
  setIsReplay: (replay) => set({ isReplay: replay }),
  setWSState: (s) => set({ wsState: s }),
  bumpRetry: () => set((st) => ({ wsRetryCount: st.wsRetryCount + 1 })),
  resetCase: () => set({
    caseId: null, status: "idle", patient: null,
    events: [], lastSequence: 0,
    agentResponses: {}, caddickHistory: [],
    currentDifferentials: [], activeChallenges: [], finalReport: null,
    rounds: [],
    interventionHistory: [], evidenceConflicts: [],
    wsState: "idle", wsRetryCount: 0, isReplay: false,
  }),

  ingestEvents: (evs) => {
    for (const ev of evs) get().ingestEvent(ev);
  },

  ingestEvent: (ev) => {
    const st = get();
    // De-dup against replay overlap on reconnect
    if (ev.sequence <= st.lastSequence) return;

    const events = [...st.events, ev];
    const next: Partial<CaseStoreState> = { events, lastSequence: ev.sequence };

    switch (ev.event_type) {
      case "case_started": {
        const p = ev.payload as { patient_presentation?: PatientPresentation };
        next.patient = p.patient_presentation ?? null;
        next.status = "running";
        break;
      }
      case "round_started": {
        const p = ev.payload as { round_number: number; planned_speakers?: string[] };
        const rounds = [...st.rounds, {
          round_number: p.round_number,
          speakers: (p.planned_speakers ?? []) as AgentName[],
          events: [ev],
        }];
        next.rounds = rounds;
        break;
      }
      case "agent_response": {
        const p = ev.payload as { agent_name: string; response: AgentResponse };
        const prev = st.agentResponses[p.agent_name] ?? [];
        next.agentResponses = { ...st.agentResponses, [p.agent_name]: [...prev, p.response] };
        break;
      }
      case "bayesian_update": {
        const p = ev.payload as {
          top_dx: string;
          top_prob: number;
          deltas?: Array<{ disease: string; prev: number | null; now: number; change: number }>;
        };
        // Build a TeamDifferential list from the deltas (best-effort)
        const ddx: TeamDifferential[] = (p.deltas ?? []).map((d) => ({
          disease: d.disease,
          probability: d.now,
          proposed_by: "",
          supporting_evidence: [],
          against_evidence: [],
        }));
        // If only a top is reported, ensure it's in the list
        if (ddx.length === 0) {
          ddx.push({ disease: p.top_dx, probability: p.top_prob, proposed_by: "",
                     supporting_evidence: [], against_evidence: [] });
        }
        ddx.sort((a, b) => b.probability - a.probability);
        next.currentDifferentials = ddx;
        break;
      }
      case "challenge_raised": {
        const p = ev.payload as { raiser: string; target: string; challenge_type: string; content: string };
        next.activeChallenges = [...st.activeChallenges, {
          target_agent: p.target,
          challenge_type: p.challenge_type as Challenge["challenge_type"],
          content: p.content,
        }];
        break;
      }
      case "challenge_resolved": {
        const p = ev.payload as { target: string; raiser: string };
        next.activeChallenges = st.activeChallenges.filter(
          (c) => !(c.target_agent === p.target),
        );
        break;
      }
      case "caddick_routing": {
        const p = ev.payload as {
          next_speakers: string[]; routing_reason: string; synthesis_text: string;
        };
        const round = st.rounds.length > 0 ? st.rounds[st.rounds.length - 1].round_number : 1;
        next.caddickHistory = [...st.caddickHistory, {
          round,
          next_speakers: p.next_speakers,
          routing_reason: p.routing_reason,
          synthesis_text: p.synthesis_text,
        }];
        break;
      }
      case "case_paused":     next.status = "paused"; break;
      case "case_resumed":    next.status = "running"; break;
      case "evidence_injected": {
        const p = ev.payload as {
          intervention_id?: string;
          conflict?: { name: string; prev_value: string; new_value: string } | null;
          [k: string]: unknown;
        };
        next.interventionHistory = [...st.interventionHistory, {
          intervention_id: p.intervention_id ?? `ev_${ev.sequence}`,
          type: "inject_evidence",
          timestamp: ev.timestamp,
          payload: p,
          applied: true,
          failure_reason: null,
        }];
        if (p.conflict) {
          next.evidenceConflicts = [...st.evidenceConflicts, {
            name: p.conflict.name,
            prev_value: p.conflict.prev_value,
            new_value: p.conflict.new_value,
          }];
        }
        break;
      }
      case "question_asked": {
        const p = ev.payload as { intervention_id?: string; [k: string]: unknown };
        next.interventionHistory = [...st.interventionHistory, {
          intervention_id: p.intervention_id ?? `ev_${ev.sequence}`,
          type: "question_agent",
          timestamp: ev.timestamp,
          payload: p,
          applied: true,
          failure_reason: null,
        }];
        break;
      }
      case "correction_applied": {
        const p = ev.payload as { intervention_id?: string; [k: string]: unknown };
        next.interventionHistory = [...st.interventionHistory, {
          intervention_id: p.intervention_id ?? `ev_${ev.sequence}`,
          type: "correct_agent",
          timestamp: ev.timestamp,
          payload: p,
          applied: true,
          failure_reason: null,
        }];
        break;
      }
      case "forced_conclusion": {
        const p = ev.payload as { intervention_id?: string; [k: string]: unknown };
        next.interventionHistory = [...st.interventionHistory, {
          intervention_id: p.intervention_id ?? `ev_${ev.sequence}`,
          type: "conclude_now",
          timestamp: ev.timestamp,
          payload: p,
          applied: true,
          failure_reason: null,
        }];
        break;
      }
      case "intervention_failed": {
        const p = ev.payload as {
          intervention_id?: string;
          intervention_type?: string;
          type?: string;
          failure_reason?: string;
          reason?: string;
          [k: string]: unknown;
        };
        next.interventionHistory = [...st.interventionHistory, {
          intervention_id: p.intervention_id ?? `ev_${ev.sequence}`,
          type: (p.intervention_type ?? p.type ?? "unknown") as string,
          timestamp: ev.timestamp,
          payload: p,
          applied: false,
          failure_reason: p.failure_reason ?? p.reason ?? "unknown",
        }];
        break;
      }
      case "case_converged":  next.status = "concluded"; break;
      case "final_report": {
        const p = ev.payload as { report: FinalReport };
        next.finalReport = p.report;
        next.status = "concluded";
        break;
      }
      case "error": next.status = "errored"; break;
      // agent_thinking, tool_call, tool_result are kept in events[] only
      default: break;
    }

    set(next);
  },
}));
