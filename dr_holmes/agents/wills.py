"""Dr. Wills — oncology consult (Anthropic Claude Haiku)."""
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
    """Live Anthropic Claude Haiku pending API key."""

    def __init__(self, anthropic_client=None, model: str = "claude-3-5-haiku-20241022"):
        self.client = anthropic_client
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
                "WillsAgent has no Anthropic client. "
                "Use MockSpecialistAgent or pass anthropic_client= once keys are set."
            )
        raise NotImplementedError("Live Wills pending Anthropic integration")
