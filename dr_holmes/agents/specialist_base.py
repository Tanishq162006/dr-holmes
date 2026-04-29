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
    routing, convergence, Bayes, and CLI all execute on real code paths."""

    def __init__(self, name: str, specialty: str, bias: str, scripted_rounds: dict[int, dict]):
        self._name = name
        self._specialty = specialty
        self._bias = bias
        # scripted_rounds: {round_number: response_dict}
        self._scripts = scripted_rounds

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
