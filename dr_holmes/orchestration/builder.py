"""LangGraph state machine builder for the Phase 3 6-agent flow."""
from __future__ import annotations
from typing import Callable

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from dr_holmes.orchestration.state import CaseState
from dr_holmes.orchestration.constants import SPECIALISTS, MAX_ROUNDS
from dr_holmes.orchestration.routing import select_next_speakers
from dr_holmes.orchestration.convergence import (
    has_converged, has_stagnated, escalation_reason,
)
from dr_holmes.orchestration.aggregation import (
    aggregate_team_differential, collect_active_challenges,
)
from dr_holmes.schemas.responses import (
    AgentResponse, FinalReport, HauserDissent,
)


# Hooks the CLI passes in for live rendering
class RenderHooks:
    def __init__(
        self,
        on_round_start: Callable[[int], None] | None = None,
        on_agent_response: Callable[[AgentResponse], None] | None = None,
        on_caddick: Callable[[dict], None] | None = None,  # CaddickSynthesis as dict
        on_team_dx: Callable[[list], None] | None = None,
        on_final: Callable[[FinalReport], None] | None = None,
    ):
        self.on_round_start    = on_round_start    or (lambda *_: None)
        self.on_agent_response = on_agent_response or (lambda *_: None)
        self.on_caddick        = on_caddick        or (lambda *_: None)
        self.on_team_dx        = on_team_dx        or (lambda *_: None)
        self.on_final          = on_final          or (lambda *_: None)


def build_phase3_graph(agent_registry: dict, caddick_agent, hooks: RenderHooks):
    """
    agent_registry: {"Hauser": SpecialistAgent, "Forman": ..., "Carmen": ..., "Chen": ..., "Wills": ...}
    caddick_agent : CaddickAgent instance (mock or live)
    """

    # ── patient_intake ─────────────────────────────────────────────────────
    def patient_intake(state: CaseState) -> dict:
        rn = 1
        hooks.on_round_start(rn)
        return {
            "round_number": rn,
            "next_speakers": list(SPECIALISTS),     # everyone speaks round 1
            "last_speakers": [],
            "evidence_log": [],
            "agent_responses": {},
            "current_differentials": [],
            "active_challenges": [],
            "proposed_tests": [],
            "last_round_top_delta": 0.0,
            "prev_round_top_delta": 0.0,
            "evidence_added_this_round": False,
            "evidence_added_prev_round": False,
            "hauser_force_speak": False,
            "hauser_interrupt_used": False,
            "converged": False,
        }

    # ── specialist_response (parallel via Send) ────────────────────────────
    def specialist_response(payload: dict) -> dict:
        agent_name = payload["agent_name"]
        case_state = payload["case_state"]
        agent = agent_registry[agent_name]
        response = agent.respond(case_state)
        hooks.on_agent_response(response)
        return {"agent_responses": {agent_name: [response]}}

    def fan_out_speakers(state: CaseState):
        speakers = state.get("next_speakers", []) or list(SPECIALISTS)
        # Snapshot the case state for each parallel branch (read-only)
        return [
            Send("specialist_response", {
                "agent_name": a,
                "case_state": dict(state),
            })
            for a in speakers if a in agent_registry
        ]

    # ── bayesian_update / aggregation ──────────────────────────────────────
    def bayesian_update(state: CaseState) -> dict:
        responses = state.get("agent_responses", {}) or {}
        prev_top_prob = 0.0
        cur_dx = state.get("current_differentials", []) or []
        if cur_dx:
            prev_top_prob = float(cur_dx[0].probability if hasattr(cur_dx[0], "probability")
                                  else cur_dx[0].get("probability", 0.0))

        team_ddx = aggregate_team_differential(responses)
        active_challenges = collect_active_challenges(responses)

        new_top_prob = team_ddx[0].probability if team_ddx else 0.0
        delta = new_top_prob - prev_top_prob

        # Hauser force_speak detection
        hauser_force = False
        hauser_hist = responses.get("Hauser", [])
        if hauser_hist:
            last = hauser_hist[-1]
            hauser_force = bool(getattr(last, "force_speak", False) or
                                (isinstance(last, dict) and last.get("force_speak")))

        hooks.on_team_dx(team_ddx)

        return {
            "current_differentials": team_ddx,
            "active_challenges": active_challenges,
            "last_round_top_delta": delta,
            "prev_round_top_delta": state.get("last_round_top_delta", 0.0),
            "evidence_added_prev_round": state.get("evidence_added_this_round", False),
            "evidence_added_this_round": False,   # reset for next round
            "hauser_force_speak": hauser_force,
            "last_speakers": state.get("next_speakers", []),
        }

    # ── caddick_synthesis ──────────────────────────────────────────────────
    def caddick_synthesis(state: CaseState) -> dict:
        synthesis = caddick_agent.synthesize(state)
        hooks.on_caddick(synthesis.model_dump())
        return {
            "next_speakers": synthesis.next_speakers,
            "caddick_synthesis_history": [synthesis],
        }

    # ── convergence_check (router) ─────────────────────────────────────────
    # Escalation reasons (stagnation, tied_top_2) are HINTS for Caddick to
    # propose a discriminating test next round — they do NOT terminate.
    # Only true convergence or hitting max_rounds ends the case.
    def convergence_decision(state: CaseState) -> str:
        converged, _ = has_converged(state)
        if converged:
            return "final_report"
        if state.get("round_number", 0) >= MAX_ROUNDS:
            return "final_report"
        return "specialist_turn"

    # ── increment_round ────────────────────────────────────────────────────
    def increment_round(state: CaseState) -> dict:
        rn = state.get("round_number", 1) + 1
        hooks.on_round_start(rn)
        return {"round_number": rn}

    # ── final_report ───────────────────────────────────────────────────────
    def final_report_node(state: CaseState) -> dict:
        case_id = state.get("case_id", "unknown")
        ddx = state.get("current_differentials", []) or []
        if ddx:
            top = ddx[0]
            consensus_dx = top.disease if hasattr(top, "disease") else top.get("disease", "Unknown")
            confidence = float(top.probability if hasattr(top, "probability") else top.get("probability", 0.0))
        else:
            consensus_dx, confidence = "No conclusion", 0.0

        # Determine convergence reason
        converged, reason = has_converged(state)
        if converged:
            convergence_reason = reason
        elif state.get("round_number", 0) >= MAX_ROUNDS:
            convergence_reason = "max_rounds"
        elif has_stagnated(state):
            convergence_reason = "stagnation"
        else:
            convergence_reason = escalation_reason(state) or "early_termination"

        # Hauser dissent check
        dissent = None
        hauser_hist = state.get("agent_responses", {}).get("Hauser", [])
        if hauser_hist and ddx:
            last_h = hauser_hist[-1]
            h_diffs = getattr(last_h, "differentials", None)
            if h_diffs is None and isinstance(last_h, dict):
                h_diffs = last_h.get("differentials", [])
            if h_diffs:
                h_top = h_diffs[0]
                h_dx = h_top.diagnosis if hasattr(h_top, "diagnosis") else h_top.get("diagnosis", "")
                from dr_holmes.orchestration.convergence import _dx_tokens_match
                if not _dx_tokens_match(h_dx, consensus_dx):
                    h_test = None
                    h_tests = (last_h.proposed_tests if hasattr(last_h, "proposed_tests")
                               else last_h.get("proposed_tests", [])) or []
                    if h_tests:
                        h_test = h_tests[0]
                        if not hasattr(h_test, "model_dump"):
                            from dr_holmes.schemas.responses import TestProposal
                            h_test = TestProposal(**h_test)
                    dissent = HauserDissent(
                        hauser_dx=h_dx,
                        hauser_confidence=float(h_top.probability if hasattr(h_top, "probability")
                                                else h_top.get("probability", 0.0)),
                        rationale=h_top.rationale if hasattr(h_top, "rationale")
                                  else h_top.get("rationale", ""),
                        recommended_test=h_test,
                    )

        # Collect proposed tests (deduped)
        tests = {}
        for agent_hist in state.get("agent_responses", {}).values():
            if not agent_hist:
                continue
            last = agent_hist[-1]
            tps = (last.proposed_tests if hasattr(last, "proposed_tests")
                   else last.get("proposed_tests", [])) or []
            for tp in tps:
                tname = tp.test_name if hasattr(tp, "test_name") else tp.get("test_name", "")
                if tname and tname not in tests:
                    tests[tname] = tp if hasattr(tp, "model_dump") else None

        from dr_holmes.schemas.responses import TestProposal
        recommended = [t if hasattr(t, "model_dump") else TestProposal(**t)
                       for t in tests.values() if t is not None]

        report = FinalReport(
            case_id=case_id,
            consensus_dx=consensus_dx,
            confidence=confidence,
            rounds_taken=state.get("round_number", 0),
            hauser_dissent=dissent,
            recommended_workup=recommended,
            deliberation_summary="(see full transcript)",
            convergence_reason=convergence_reason,
            full_responses=state.get("agent_responses", {}),
        )

        hooks.on_final(report)
        return {"converged": True, "convergence_reason": convergence_reason,
                "final_report": report.model_dump()}

    # ── Build graph ────────────────────────────────────────────────────────
    builder = StateGraph(CaseState)

    builder.add_node("patient_intake",      patient_intake)
    builder.add_node("specialist_response", specialist_response)
    builder.add_node("bayesian_update",     bayesian_update)
    builder.add_node("caddick_synthesis",   caddick_synthesis)
    builder.add_node("increment_round",     increment_round)
    builder.add_node("final_report",        final_report_node)

    builder.add_edge(START, "patient_intake")
    builder.add_conditional_edges("patient_intake", fan_out_speakers, ["specialist_response"])
    builder.add_edge("specialist_response", "bayesian_update")
    builder.add_edge("bayesian_update", "caddick_synthesis")
    builder.add_conditional_edges(
        "caddick_synthesis",
        convergence_decision,
        {"specialist_turn": "increment_round", "final_report": "final_report"},
    )
    builder.add_conditional_edges("increment_round", fan_out_speakers, ["specialist_response"])
    builder.add_edge("final_report", END)

    return builder.compile()
