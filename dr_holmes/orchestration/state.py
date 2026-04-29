"""Phase 3 LangGraph state — TypedDict with reducers for parallel branches."""
from __future__ import annotations
from typing import TypedDict, Annotated, Optional
from operator import add

from dr_holmes.models.core import PatientCase, Evidence, Differential
from dr_holmes.schemas.responses import (
    AgentResponse, Challenge, TestProposal, CaddickSynthesis, HauserDissent,
)


def merge_responses(a: dict, b: dict) -> dict:
    """Reducer for agent_responses: append-merge per agent_name key."""
    out = {**a}
    for k, v in (b or {}).items():
        out[k] = out.get(k, []) + (v if isinstance(v, list) else [v])
    return out


def replace(_a, b):
    """Override reducer — used for fields that fully overwrite each round."""
    return b


class CaseState(TypedDict, total=False):
    case_id: str
    patient_presentation: dict          # PatientCase.model_dump()

    evidence_log: Annotated[list, add]  # list[Evidence] — appends
    agent_responses: Annotated[dict, merge_responses]   # {agent: [AgentResponse,...]}

    current_differentials: list        # list[Differential] — replaced each round
    active_challenges: list            # list[Challenge]
    proposed_tests: list               # list[TestProposal]

    round_number: int
    next_speakers: list                # set by Caddick routing
    last_speakers: list                # who spoke previous round (no replays)

    last_round_top_delta: float        # |Δ probability of top dx|
    prev_round_top_delta: float        # one before that (for stagnation check)
    evidence_added_this_round: bool
    evidence_added_prev_round: bool

    hauser_force_speak: bool
    hauser_interrupt_used: bool

    converged: bool
    convergence_reason: str            # "team_agreement" | "max_rounds" | "stagnation" | "doctor_concluded"

    caddick_synthesis_history: Annotated[list, add]  # list[CaddickSynthesis]
    final_report: Optional[dict]
