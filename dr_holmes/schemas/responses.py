"""Phase 3 structured response schemas — what every agent returns."""
from __future__ import annotations
from typing import Literal, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


# ── Phase 6 turn-type taxonomy ─────────────────────────────────────────────

TurnType = Literal[
    "normal",
    "question_response",
    "correction_response",
    "evidence_acknowledgment",
    "forced_conclusion_dissent",
]


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

    # Phase 6: HITL fields
    turn_type: TurnType = "normal"
    responding_to: Optional[str] = None     # intervention_id this turn responds to


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
    convergence_reason: str = ""    # "team_agreement" | "max_rounds" | "stagnation" | "doctor_concluded" | "forced_by_human"
    full_responses: dict[str, list[AgentResponse]] = Field(default_factory=dict)
    # Phase 6
    forced_by_human: bool = False
    pre_conclusion_dissents: list[HauserDissent] = Field(default_factory=list)
    interventions_summary: list[dict[str, Any]] = Field(default_factory=list)


# ── Phase 6: Human-in-the-loop interventions ───────────────────────────────

InterventionType = Literal[
    "pause", "resume", "inject_evidence",
    "question_agent", "correct_agent", "conclude_now",
]


class Intervention(BaseModel):
    intervention_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    case_id: str
    type: InterventionType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence_number: int = 0                 # monotonic per case
    applied: bool = False
    applied_at: Optional[datetime] = None
    failure_reason: Optional[str] = None


class ScheduledTurn(BaseModel):
    """A turn that the routing layer must schedule next, ahead of normal rules.
    Populated by `human_intervention` when interventions are applied."""
    agent: str
    turn_type: TurnType = "normal"
    intervention_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceConflict(BaseModel):
    name: str
    prev_value: str
    new_value: str
    prev_ts: str
    new_ts: str
