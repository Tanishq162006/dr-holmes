import { describe, it, expect, beforeEach } from "vitest";
import { useCaseStore } from "@/lib/stores/caseStore";
import type { WSEvent } from "@/lib/types/wire";

function ev(seq: number, type: WSEvent["event_type"], payload: Record<string, unknown>): WSEvent {
  return {
    protocol_version: "v1",
    sequence: seq,
    case_id: "test_case",
    event_type: type,
    timestamp: new Date().toISOString(),
    payload,
  };
}

describe("caseStore.ingestEvent", () => {
  beforeEach(() => {
    useCaseStore.getState().resetCase();
  });

  it("appends events in sequence order", () => {
    useCaseStore.getState().ingestEvent(ev(1, "case_started", {
      patient_presentation: { presenting_complaint: "chest pain" },
    }));
    useCaseStore.getState().ingestEvent(ev(2, "round_started", { round_number: 1 }));
    expect(useCaseStore.getState().events.length).toBe(2);
    expect(useCaseStore.getState().lastSequence).toBe(2);
    expect(useCaseStore.getState().status).toBe("running");
  });

  it("dedupes events on replay overlap", () => {
    useCaseStore.getState().ingestEvent(ev(5, "round_started", { round_number: 1 }));
    useCaseStore.getState().ingestEvent(ev(5, "round_started", { round_number: 1 }));
    useCaseStore.getState().ingestEvent(ev(3, "round_started", { round_number: 0 }));
    expect(useCaseStore.getState().events.length).toBe(1);
  });

  it("captures agent responses indexed by name", () => {
    useCaseStore.getState().ingestEvent(ev(1, "agent_response", {
      agent_name: "Hauser",
      response: {
        agent_name: "Hauser", turn_number: 1,
        differentials: [{ diagnosis: "SLE", probability: 0.6, rationale: "" }],
        confidence: 0.6, defers_to_team: false,
        reasoning: "", proposed_tests: [], challenges: [],
        request_floor: false, force_speak: false,
      },
    }));
    expect(useCaseStore.getState().agentResponses.Hauser?.[0]?.differentials[0]?.diagnosis).toBe("SLE");
  });

  it("updates differentials from bayesian_update events", () => {
    useCaseStore.getState().ingestEvent(ev(1, "bayesian_update", {
      top_dx: "SLE", top_prob: 0.78,
      deltas: [{ disease: "SLE", prev: 0.45, now: 0.78, change: 0.33 }],
    }));
    expect(useCaseStore.getState().currentDifferentials[0]?.disease).toBe("SLE");
    expect(useCaseStore.getState().currentDifferentials[0]?.probability).toBe(0.78);
  });

  it("flips status to concluded on case_converged + final_report", () => {
    useCaseStore.getState().ingestEvent(ev(1, "case_converged", {
      consensus_dx: "SLE", confidence: 0.85, convergence_reason: "team_agreement",
    }));
    expect(useCaseStore.getState().status).toBe("concluded");
  });

  it("captures intervention history from evidence_injected events", () => {
    useCaseStore.getState().ingestEvent(ev(1, "evidence_injected", {
      intervention_id: "iv_evidence_1",
      name: "anti-dsDNA",
      value: "positive 1:160",
    }));
    const hist = useCaseStore.getState().interventionHistory;
    expect(hist.length).toBe(1);
    expect(hist[0].intervention_id).toBe("iv_evidence_1");
    expect(hist[0].type).toBe("inject_evidence");
    expect(hist[0].applied).toBe(true);
  });

  it("flags evidence conflicts", () => {
    useCaseStore.getState().ingestEvent(ev(1, "evidence_injected", {
      intervention_id: "iv_evidence_2",
      name: "WBC",
      value: 14,
      conflict: { name: "WBC", prev_value: "10", new_value: "14" },
    }));
    const conflicts = useCaseStore.getState().evidenceConflicts;
    expect(conflicts.length).toBe(1);
    expect(conflicts[0].name).toBe("WBC");
    expect(conflicts[0].prev_value).toBe("10");
    expect(conflicts[0].new_value).toBe("14");
  });

  it("captures intervention_failed events with failure_reason", () => {
    useCaseStore.getState().ingestEvent(ev(1, "intervention_failed", {
      intervention_id: "iv_failed_1",
      intervention_type: "question_agent",
      failure_reason: "target_agent required",
    }));
    const hist = useCaseStore.getState().interventionHistory;
    expect(hist.length).toBe(1);
    expect(hist[0].applied).toBe(false);
    expect(hist[0].failure_reason).toBe("target_agent required");
    expect(hist[0].type).toBe("question_agent");
  });
});
