"""Dr. Wills — oncology consult (OpenAI gpt-4o-mini)."""
from __future__ import annotations
from dr_holmes.agents.specialist_base import SpecialistAgent
from dr_holmes.schemas.responses import AgentResponse


SYSTEM_PROMPT = """You are Dr. James Wills, an oncology consultant.

PERSONALITY: Measured, careful, rules malignancy in/out methodically.
You don't let the team move on until cancer is properly considered or
ruled out — but you don't waste airtime when the case clearly isn't
oncologic.

SPECIALTY BIAS: malignancy.

TOOL USAGE:
- Call get_differentials_for_symptoms with bias='malignancy'
- Call search_case_reports for atypical presentations of common cancers
- Use get_typical_presentation when team proposes an oncologic dx
- Call update_probabilities when staging studies / biopsy results arrive

OUTPUT FORMAT: Structured AgentResponse JSON. Brief and specific. If you
have nothing to add this round, set defers_to_team=true and confidence=0.
"""


class WillsAgent(SpecialistAgent):
    """Live OpenAI gpt-4o-mini pending live-mode wiring (Phase 4.5)."""

    def __init__(self, openai_client=None, model: str = "gpt-4o-mini"):
        self.client = openai_client
        self.model = model

    @property
    def name(self) -> str:        return "Wills"
    @property
    def specialty(self) -> str:   return "Oncology"
    @property
    def bias(self) -> str:        return "malignancy"
    @property
    def system_prompt(self) -> str: return SYSTEM_PROMPT

    def respond(self, state: dict) -> AgentResponse:
        if self.client is None:
            raise RuntimeError(
                "WillsAgent has no OpenAI client. "
                "Use MockSpecialistAgent for now."
            )
        raise NotImplementedError("Live Wills pending OpenAI integration")
