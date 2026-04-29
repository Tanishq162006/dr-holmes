"""Phase 3 structured response schemas — what every agent returns."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Reused / extended from Phase 2 ─────────────────────────────────────────

class Differential(BaseModel):
    diagnosis: str
    probability: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class TestProposal(BaseModel):
    test_name: str
    rationale: str = ""
    expected_information_gain: float = 0.0
    rules_in: list[str] = Field(default_factory=list)
    rules_out: list[str] = Field(default_factory=list)


class Challenge(BaseModel):
    target_agent: str
    challenge_type: Literal[
        "disagree_dx", "disagree_test", "missing_consideration",
        "evidence_mismatch", "personality_call",
    ]
    content: str


class AgentResponse(BaseModel):
    agent_name: str
    turn_number: int = 0
    reasoning: str = ""
    differentials: list[Differential] = Field(default_factory=list)
    proposed_tests: list[TestProposal] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    defers_to_team: bool = False
    request_floor: bool = False
    force_speak: bool = False  # Hauser-only privilege


# ── Caddick (moderator) ────────────────────────────────────────────────────

class CaddickSynthesis(BaseModel):
    """Caddick's per-round artifact: synthesis paragraph + (deterministic)
    next_speakers chosen by routing logic, not by Caddick's LLM."""
    round_number: int
    synthesis: str = ""           # LLM-generated paragraph
    next_speakers: list[str] = Field(default_factory=list)   # set by router
    routing_reason: str = ""      # which routing rule fired


# ── Final output ───────────────────────────────────────────────────────────

class HauserDissent(BaseModel):
    hauser_dx: str
    hauser_confidence: float
    rationale: str
    recommended_test: Optional[TestProposal] = None


class FinalReport(BaseModel):
    case_id: str
    consensus_dx: str
    confidence: float
    rounds_taken: int
    hauser_dissent: Optional[HauserDissent] = None
    recommended_workup: list[TestProposal] = Field(default_factory=list)
    deliberation_summary: str = ""
    convergence_reason: str = ""    # "team_agreement" | "max_rounds" | "stagnation" | "doctor_concluded"
    full_responses: dict[str, list[AgentResponse]] = Field(default_factory=dict)
