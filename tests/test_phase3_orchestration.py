"""Phase 3 deterministic orchestration tests — no LLM, no API keys needed."""
import pytest
from dr_holmes.orchestration.routing import (
    select_next_speakers, specialty_for_dx, compute_confidence_deltas,
)
from dr_holmes.orchestration.convergence import (
    has_converged, has_stagnated, escalation_reason, _normalize_dx,
)
from dr_holmes.orchestration.aggregation import (
    aggregate_team_differential, collect_active_challenges,
)
from dr_holmes.orchestration.constants import (
    CONVERGENCE_PROB, AGREEMENT_COUNT, AGREEMENT_PROB, STABILITY_DELTA,
    MAX_ROUNDS, STAGNATION_DELTA, STAGNATION_ROUNDS, SPECIALISTS,
)
from dr_holmes.schemas.responses import (
    AgentResponse, Differential as SpecDifferential, TestProposal, Challenge,
)
from dr_holmes.models.core import Differential as TeamDifferential


# ── Routing ─────────────────────────────────────────────────────────────────

def test_specialty_for_dx_autoimmune():
    assert specialty_for_dx("Systemic lupus erythematosus") == "Carmen"
    assert specialty_for_dx("Vasculitis") == "Carmen"

def test_specialty_for_dx_malignancy():
    assert specialty_for_dx("B-cell lymphoma") == "Wills"

def test_specialty_for_dx_surgical():
    assert specialty_for_dx("Aortic dissection") == "Chen"

def test_specialty_for_dx_zebra():
    assert specialty_for_dx("Whipple disease") == "Hauser"

def test_specialty_for_dx_unknown():
    assert specialty_for_dx("hiccups") is None


def _resp(agent, prob=0.5, dx="X", confidence=0.5, request_floor=False, force=False):
    return AgentResponse(
        agent_name=agent, turn_number=1,
        differentials=[SpecDifferential(diagnosis=dx, probability=prob)],
        confidence=confidence, request_floor=request_floor, force_speak=force,
    )


def test_routing_hauser_interrupt_wins_over_everything():
    state = {
        "hauser_force_speak": True, "hauser_interrupt_used": False,
        "agent_responses": {"Carmen": [_resp("Carmen", request_floor=True)]},
        "active_challenges": [{"target_agent": "Forman", "challenge_type": "disagree_dx", "content": "x"}],
        "current_differentials": [], "last_speakers": [],
    }
    speakers, reason = select_next_speakers(state)
    assert speakers == ["Hauser"]
    assert reason == "hauser_interrupt"


def test_routing_floor_request():
    state = {
        "agent_responses": {"Carmen": [_resp("Carmen", request_floor=True)]},
        "active_challenges": [], "current_differentials": [],
        "last_speakers": [], "hauser_force_speak": False,
    }
    speakers, reason = select_next_speakers(state)
    assert "Carmen" in speakers
    assert reason == "floor_request"


def test_routing_challenge_response():
    state = {
        "agent_responses": {},
        "active_challenges": [
            {"target_agent": "Forman", "challenge_type": "disagree_dx", "content": "x"},
            {"target_agent": "Carmen", "challenge_type": "missing_consideration", "content": "y"},
        ],
        "current_differentials": [], "last_speakers": [],
        "hauser_force_speak": False,
    }
    speakers, reason = select_next_speakers(state)
    assert speakers == ["Forman", "Carmen"]
    assert reason == "challenge_response"


def test_routing_specialty_match():
    state = {
        "agent_responses": {},
        "active_challenges": [],
        "current_differentials": [TeamDifferential(disease="Systemic lupus", probability=0.7)],
        "last_speakers": [], "hauser_force_speak": False,
    }
    speakers, reason = select_next_speakers(state)
    assert speakers == ["Carmen"]
    assert reason == "specialty_match"


def test_routing_excludes_last_speakers():
    state = {
        "agent_responses": {},
        "active_challenges": [
            {"target_agent": "Forman", "challenge_type": "disagree_dx", "content": "x"},
        ],
        "current_differentials": [],
        "last_speakers": ["Forman"],
        "hauser_force_speak": False,
    }
    speakers, reason = select_next_speakers(state)
    # Forman was just last speaker, can't be picked via challenge
    assert "Forman" not in speakers


# ── Convergence ─────────────────────────────────────────────────────────────

def test_normalize_dx_handles_punctuation_and_articles():
    assert _normalize_dx("The S.L.E.") == "s l e"
    assert _normalize_dx("Whipple's Disease") == "whipple disease"


def _state_for_convergence(top_prob=0.85, agree=4, delta=0.0, rn=3, challenges=None):
    """Helper: build a state that should converge unless tweaked."""
    dx_name = "SLE"
    cur_dx = [TeamDifferential(disease=dx_name, probability=top_prob)]
    responses = {}
    for i, sp in enumerate(SPECIALISTS):
        if i < agree:
            responses[sp] = [AgentResponse(
                agent_name=sp, turn_number=rn,
                differentials=[SpecDifferential(diagnosis=dx_name, probability=0.7)],
                confidence=0.7,
            )]
        else:
            responses[sp] = [AgentResponse(
                agent_name=sp, turn_number=rn,
                differentials=[SpecDifferential(diagnosis="Other", probability=0.4)],
                confidence=0.4,
            )]
    return {
        "round_number": rn,
        "current_differentials": cur_dx,
        "agent_responses": responses,
        "active_challenges": challenges or [],
        "last_round_top_delta": delta,
    }


def test_convergence_happy_path():
    state = _state_for_convergence()
    converged, reason = has_converged(state)
    assert converged is True
    assert reason == "team_agreement"


def test_no_convergence_below_prob_threshold():
    state = _state_for_convergence(top_prob=0.70)
    converged, _ = has_converged(state)
    assert converged is False


def test_no_convergence_too_few_specialists_agree():
    state = _state_for_convergence(agree=2)
    converged, _ = has_converged(state)
    assert converged is False


def test_no_convergence_with_active_challenges():
    state = _state_for_convergence(challenges=[
        {"target_agent": "Carmen", "challenge_type": "disagree_dx", "content": "x"}
    ])
    converged, _ = has_converged(state)
    assert converged is False


def test_no_convergence_with_big_recent_delta():
    state = _state_for_convergence(delta=0.20)
    converged, _ = has_converged(state)
    assert converged is False


def test_no_convergence_round_1():
    state = _state_for_convergence(rn=1)
    converged, _ = has_converged(state)
    assert converged is False


# ── Stagnation ──────────────────────────────────────────────────────────────

def test_stagnation_triggers_after_2_quiet_rounds():
    state = {
        "round_number": 4,
        "last_round_top_delta": 0.005,
        "prev_round_top_delta": 0.01,
        "evidence_added_this_round": False,
        "evidence_added_prev_round": False,
    }
    assert has_stagnated(state) is True
    assert escalation_reason(state) == "stagnation_force_test_order"


def test_stagnation_blocked_by_new_evidence():
    state = {
        "round_number": 4,
        "last_round_top_delta": 0.005,
        "prev_round_top_delta": 0.01,
        "evidence_added_this_round": True,
        "evidence_added_prev_round": False,
    }
    assert has_stagnated(state) is False


# ── Aggregation ─────────────────────────────────────────────────────────────

def test_aggregation_normalizes_total_probability():
    responses = {
        "Hauser": [AgentResponse(
            agent_name="Hauser", turn_number=1,
            differentials=[SpecDifferential(diagnosis="A", probability=0.8)],
            confidence=0.8,
        )],
        "Forman": [AgentResponse(
            agent_name="Forman", turn_number=1,
            differentials=[SpecDifferential(diagnosis="A", probability=0.7)],
            confidence=0.7,
        )],
    }
    team = aggregate_team_differential(responses)
    assert len(team) == 1
    assert team[0].probability <= 1.0
    assert team[0].probability > 0.5


def test_aggregation_merges_same_dx_different_specialists():
    responses = {
        sp: [AgentResponse(
            agent_name=sp, turn_number=1,
            differentials=[SpecDifferential(diagnosis="SLE", probability=0.6)],
            confidence=0.6,
        )]
        for sp in ["Hauser", "Forman", "Carmen"]
    }
    team = aggregate_team_differential(responses)
    assert len(team) == 1
    assert team[0].disease == "SLE"
    # Multi-specialist agreement boosts probability
    assert team[0].probability > 0.6


# ── Hauser dissent (smoke test, full integration verified in e2e) ───────────

def test_normalize_dx_matches_hauser_with_team():
    assert _normalize_dx("Whipple disease") == _normalize_dx("Whipple's Disease")
