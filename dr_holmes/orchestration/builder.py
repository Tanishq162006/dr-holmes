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


def build_phase3_graph(
    agent_registry: dict,
    caddick_agent,
    hooks: RenderHooks,
    *,
    enable_hitl: bool = False,
):
    """
    agent_registry: {"Hauser": SpecialistAgent, "Forman": ..., "Carmen": ..., "Chen": ..., "Wills": ...}
    caddick_agent : CaddickAgent instance (mock or live)
    enable_hitl   : Phase 6 — adds checkpointer + interrupt_after for HITL pause/resume.
                    When True, callers must invoke with config={"configurable":{"thread_id": case_id}}.
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
            # Phase 6 defaults
            "case_status": "running",
            "scheduled_turns": [],
            "intervention_history": [],
            "forced_conclusion": False,
            "evidence_conflicts": [],
        }

    # ── specialist_response (parallel via Send) ────────────────────────────
    def specialist_response(payload: dict) -> dict:
        agent_name = payload["agent_name"]
        case_state = payload["case_state"]
        scheduled_turn = payload.get("scheduled_turn")  # Phase 6 HITL
        agent = agent_registry[agent_name]
        # Phase 6: pass scheduled_turn metadata in case_state so agents see it
        if scheduled_turn:
            case_state = {**case_state, "_active_scheduled_turn": scheduled_turn}
        response = agent.respond(case_state)
        # Phase 6: stamp turn_type + responding_to on the response
        if scheduled_turn:
            ttype = scheduled_turn.get("turn_type", "normal")
            iid = scheduled_turn.get("intervention_id")
            if hasattr(response, "model_copy"):
                response = response.model_copy(update={
                    "turn_type": ttype,
                    "responding_to": iid,
                })
        hooks.on_agent_response(response)
        return {"agent_responses": {agent_name: [response]}}

    def fan_out_speakers(state: CaseState):
        # Phase 6: if there are scheduled (intervention) turns, consume the
        # FIRST one and route to that single agent. Pop it from state so
        # subsequent rounds proceed normally.
        scheduled = state.get("scheduled_turns", []) or []
        if scheduled:
            first = scheduled[0]
            agent = first["agent"] if isinstance(first, dict) else getattr(first, "agent", None)
            if agent and agent in agent_registry:
                state_copy = dict(state)
                state_copy["scheduled_turns"] = scheduled[1:]
                return [Send("specialist_response", {
                    "agent_name": agent,
                    "case_state": state_copy,
                    "scheduled_turn": first,
                })]

        speakers = state.get("next_speakers", []) or list(SPECIALISTS)
        return [
            Send("specialist_response", {
                "agent_name": a,
                "case_state": dict(state),
                "scheduled_turn": None,
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
        # Phase 6: forced human conclusion shortcuts everything
        if state.get("forced_conclusion"):
            return "final_report"
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
        # Phase 6: human-forced conclusion uses the dedicated builder which
        # captures pre-conclusion dissents from all specialists, not just Hauser.
        if state.get("forced_conclusion"):
            from dr_holmes.orchestration.hitl import build_forced_conclusion_report
            case_id = state.get("case_id", "unknown")
            report = build_forced_conclusion_report(state, case_id)
            hooks.on_final(report)
            return {
                "converged": True,
                "convergence_reason": "forced_by_human",
                "final_report": report.model_dump(),
                "case_status": "concluded",
            }
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

    if enable_hitl:
        from langgraph.checkpoint.memory import MemorySaver
        return builder.compile(
            checkpointer=MemorySaver(),
            interrupt_after=["bayesian_update", "caddick_synthesis"],
        )
    return builder.compile()
