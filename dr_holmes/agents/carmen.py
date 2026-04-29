"""Dr. Carmen — immunology / autoimmune specialist (Anthropic Claude Sonnet)."""
from __future__ import annotations
from dr_holmes.agents.specialist_base import SpecialistAgent, MockSpecialistAgent
from dr_holmes.schemas.responses import AgentResponse


SYSTEM_PROMPT = """You are Dr. Allison Carmen, an immunologist on a diagnostic team.

PERSONALITY: Empathetic, rigorous, considers nuanced presentations. You are
the voice for autoimmune and rare immune-mediated conditions. You push back
on Forman when he over-weights base rates and ignores serology.

SPECIALTY BIAS: autoimmune / rheumatologic / immunologic.

TOOL USAGE:
- Call get_differentials_for_symptoms with bias='autoimmune'
- Call get_typical_presentation for any autoimmune dx you're considering
- Call update_probabilities every time serology / complement / biopsy results arrive
- Call get_red_flags first if presentation has any acute features

OUTPUT FORMAT (strict): A structured AgentResponse JSON. You may challenge
specific colleagues by name; specify challenge_type accurately. Keep
reasoning under 150 words. confidence ∈ [0,1]; defers_to_team only if
your top dx has prob < 0.30.
"""


class CarmenAgent(SpecialistAgent):
    """Live Anthropic Claude implementation pending API key.
    Until then, instantiate via MockSpecialistAgent.from_fixture."""

    def __init__(self, anthropic_client=None, model: str = "claude-3-5-sonnet-20241022"):
        self.client = anthropic_client
        self.model = model

    @property
    def name(self) -> str:        return "Carmen"
    @property
    def specialty(self) -> str:   return "Immunology / Autoimmune"
    @property
    def bias(self) -> str:        return "autoimmune"
    @property
    def system_prompt(self) -> str: return SYSTEM_PROMPT

    def respond(self, state: dict) -> AgentResponse:
        if self.client is None:
            raise RuntimeError(
                "CarmenAgent has no Anthropic client. "
                "Use MockSpecialistAgent for now, or pass anthropic_client= once you have a key."
            )
        # TODO: wire Anthropic structured output when keys are available
        raise NotImplementedError("Live Carmen pending Anthropic integration")
