"""Phase 3 specialist base — produces structured AgentResponse via tool-call LLM,
or via mock-fixture replay when running in mock mode.

Phase 1/2 agents (Hauser, Forman) use a different tool-streaming base; we keep
them intact and adopt this richer interface for Phase 3 + going forward."""
from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod
from typing import Optional

from dr_holmes.schemas.responses import (
    AgentResponse, Differential, TestProposal, Challenge,
)


class SpecialistAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def specialty(self) -> str: ...

    @property
    @abstractmethod
    def bias(self) -> str:
        """Default bias passed to MI tool calls — "rare", "common", etc."""

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def respond(self, state: dict) -> AgentResponse: ...


# ── Mock agent ─────────────────────────────────────────────────────────────

class MockSpecialistAgent(SpecialistAgent):
    """Replays canned responses from a fixture. Real state machine still runs:
    routing, convergence, Bayes, and CLI all execute on real code paths.

    Phase 6: also supports `intervention_responses` keyed by intervention type +
    target/name. When the runner schedules a turn (via `_active_scheduled_turn`
    in state), we look up the matching response."""

    def __init__(self, name: str, specialty: str, bias: str,
                 scripted_rounds: dict[int, dict],
                 intervention_responses: dict[str, dict] | None = None):
        self._name = name
        self._specialty = specialty
        self._bias = bias
        self._scripts = scripted_rounds
        self._int_responses = intervention_responses or {}

    @property
    def name(self) -> str:        return self._name
    @property
    def specialty(self) -> str:   return self._specialty
    @property
    def bias(self) -> str:        return self._bias
    @property
    def system_prompt(self) -> str:
        return f"[mock {self._name}]"

    def respond(self, state: dict) -> AgentResponse:
        rn = int(state.get("round_number", 0))

        # Phase 6: intervention turn?
        scheduled = state.get("_active_scheduled_turn")
        if scheduled:
            ttype = scheduled.get("turn_type", "normal")
            payload = scheduled.get("payload", {}) or {}
            key = self._intervention_key(ttype, payload)
            canned_for_int = self._int_responses.get(key)
            if canned_for_int:
                return self._build_response(rn, canned_for_int, ttype, scheduled.get("intervention_id"))
            # Deterministic stub if no scripted response
            return self._stub_intervention_response(rn, ttype, payload, scheduled.get("intervention_id"))

        canned = self._scripts.get(rn) or self._scripts.get(str(rn))

        if not canned:
            return AgentResponse(
                agent_name=self._name,
                turn_number=rn,
                reasoning="(no scripted response for this round)",
                differentials=[],
                proposed_tests=[],
                challenges=[],
                confidence=0.0,
                defers_to_team=True,
            )

        return AgentResponse(
            agent_name=self._name,
            turn_number=rn,
            reasoning=canned.get("reasoning", ""),
            differentials=[Differential(**d) for d in canned.get("differentials", [])],
            proposed_tests=[TestProposal(**t) for t in canned.get("proposed_tests", [])],
            challenges=[Challenge(**c) for c in canned.get("challenges", [])],
            confidence=float(canned.get("confidence", 0.5)),
            defers_to_team=bool(canned.get("defers_to_team", False)),
            request_floor=bool(canned.get("request_floor", False)),
            force_speak=bool(canned.get("force_speak", False)),
        )

    # ── Phase 6 helpers ─────────────────────────────────────────────

    @staticmethod
    def _intervention_key(turn_type: str, payload: dict) -> str:
        """Deterministic key for fixture lookup. Same scheme used by fixture authors."""
        if turn_type == "evidence_acknowledgment":
            return f"inject_evidence:{payload.get('evidence_name','').lower().replace(' ','_')}"
        if turn_type == "question_response":
            q = payload.get("question", "")
            tag = q.lower()[:30].replace(" ", "_").replace("?", "").replace(",", "")
            return f"question:{tag}"
        if turn_type == "correction_response":
            c = payload.get("correction", "")
            tag = c.lower()[:30].replace(" ", "_")
            return f"correction:{tag}"
        if turn_type == "forced_conclusion_dissent":
            return "forced_conclusion_dissent"
        return f"{turn_type}:{payload}"

    def _build_response(self, rn: int, canned: dict, turn_type: str,
                        intervention_id: str | None) -> AgentResponse:
        return AgentResponse(
            agent_name=self._name,
            turn_number=rn,
            reasoning=canned.get("reasoning", ""),
            differentials=[Differential(**d) for d in canned.get("differentials", [])],
            proposed_tests=[TestProposal(**t) for t in canned.get("proposed_tests", [])],
            challenges=[Challenge(**c) for c in canned.get("challenges", [])],
            confidence=float(canned.get("confidence", 0.5)),
            defers_to_team=bool(canned.get("defers_to_team", False)),
            request_floor=bool(canned.get("request_floor", False)),
            force_speak=bool(canned.get("force_speak", False)),
            turn_type=turn_type,  # type: ignore[arg-type]
            responding_to=intervention_id,
        )

    def _stub_intervention_response(self, rn: int, turn_type: str, payload: dict,
                                    intervention_id: str | None) -> AgentResponse:
        """Deterministic stub when no scripted response. Used for tests."""
        if turn_type == "question_response":
            text = f"[Mock {self._name}] re: question — '{payload.get('question','')[:80]}'"
            return AgentResponse(
                agent_name=self._name, turn_number=rn,
                reasoning=text, confidence=0.5,
                turn_type="question_response", responding_to=intervention_id,
            )
        if turn_type == "correction_response":
            text = f"[Mock {self._name}] acknowledged correction — '{payload.get('correction','')[:80]}'"
            return AgentResponse(
                agent_name=self._name, turn_number=rn,
                reasoning=text, confidence=0.5,
                turn_type="correction_response", responding_to=intervention_id,
            )
        if turn_type == "evidence_acknowledgment":
            text = f"[Mock Caddick] new finding {payload.get('evidence_name','')} acknowledged."
            return AgentResponse(
                agent_name=self._name, turn_number=rn,
                reasoning=text, confidence=0.5,
                turn_type="evidence_acknowledgment", responding_to=intervention_id,
            )
        return AgentResponse(
            agent_name=self._name, turn_number=rn, defers_to_team=True,
            confidence=0.0, turn_type=turn_type,  # type: ignore[arg-type]
            responding_to=intervention_id,
        )
