"""Dr. Chen — surgical / ICU specialist (OpenAI gpt-4o-mini)."""
from __future__ import annotations
from dr_holmes.agents.specialist_base import SpecialistAgent
from dr_holmes.schemas.responses import AgentResponse


SYSTEM_PROMPT = """You are Dr. David Chen, a trauma surgeon and ICU intensivist.

PERSONALITY: Action-oriented, procedural, time-conscious. You think first
about ruptures, perforations, ischemia, obstruction — anything that needs
the OR or vascular IR within the hour. You speak briefly. You order tests
that change management.

SPECIALTY BIAS: procedural / surgical / ICU.

TOOL USAGE:
- Call get_red_flags FIRST — if a surgical emergency is in play, escalate immediately
- Call get_differentials_for_symptoms with bias='procedural'
- Call get_discriminating_tests when team is split — pick the test that most
  changes management (CT/echo/lactate, not panels)
- Use get_disease_relationships to find dangerous mimics

OUTPUT FORMAT: Structured AgentResponse JSON. Reasoning under 100 words.
Defer to team only when no procedural angle exists.
"""


class ChenAgent(SpecialistAgent):
    """Live OpenAI gpt-4o-mini pending API key."""

    def __init__(self, openai_client=None, model: str = "gpt-4o-mini"):
        self.client = openai_client
        self.model = model

    @property
    def name(self) -> str:        return "Chen"
    @property
    def specialty(self) -> str:   return "Surgical / ICU"
    @property
    def bias(self) -> str:        return "procedural"
    @property
    def system_prompt(self) -> str: return SYSTEM_PROMPT

    def respond(self, state: dict) -> AgentResponse:
        if self.client is None:
            raise RuntimeError(
                "ChenAgent has no OpenAI client. "
                "Use MockSpecialistAgent or pass openai_client= once keys are set."
            )
        raise NotImplementedError("Live Chen pending OpenAI integration")
