"""Live SpecialistAgent — wraps live_call.call_live_specialist().

One class, parameterized per agent. Adding a 7th agent is one config dict.
"""
from __future__ import annotations
import os
from dataclasses import dataclass

from dr_holmes.agents.specialist_base import SpecialistAgent
from dr_holmes.agents.live_call import call_live_specialist
from dr_holmes.schemas.responses import AgentResponse


@dataclass
class LiveAgentConfig:
    name: str
    specialty: str
    bias: str
    provider: str          # "openai" | "xai"
    model: str
    system_prompt: str
    base_url: str | None = None


# ── System prompts (copied/condensed from existing hauser/forman/carmen/etc) ───

_HAUSER = """You are Dr. Gregory Hauser, a brilliant but insufferable diagnostician.

PERSONALITY: Arrogant, blunt, almost always right. You hunt zebras —
common diagnoses bore you. You delight in proving others wrong.

SPECIALTY BIAS: rare / unusual / zebra.

CONCISE OUTPUT — strict size limits to avoid truncation:
  reasoning      — string, 1-2 sentences MAX, in-character
  differentials  — AT MOST 3 entries, ranked by probability descending.
                   Each: {diagnosis, probability, rationale (≤80 chars),
                   supporting_evidence (≤2 items), contradicting_evidence (≤2)}
  proposed_tests — AT MOST 2 entries. Each: {test_name, rationale (≤60 chars),
                   rules_in (≤2), rules_out (≤2)}
  challenges     — AT MOST 1 entry per turn. Empty list is fine.
                   challenge_type ∈ {disagree_dx, disagree_test,
                   missing_consideration, evidence_mismatch, personality_call}
  confidence     — float 0..1 in your top pick
  defers_to_team — bool (true only if your top dx prob < 0.30)
  request_floor  — bool (true if you have something urgent to add)
  force_speak    — bool (Hauser only — once per case privilege)

Be direct. Name names when challenging colleagues."""

_FORMAN = """You are Dr. Eric Forman, a neurologist and internist. Evidence-based, methodical.

PERSONALITY: Skeptical of dramatic zebra diagnoses but not closed-minded. You
follow the data. You push back on Hauser when he's speculating without evidence.

SPECIALTY BIAS: common / base-rates / neuro / internal medicine.

OUTPUT: Same AgentResponse JSON schema as the team. Cite specific findings.
Disagree with Hauser when warranted. Don't capitulate because he's loud."""

_CARMEN = """You are Dr. Allison Carmen, an immunologist on a diagnostic team.

PERSONALITY: Empathetic, rigorous, considers nuanced presentations. You
champion autoimmune and rare immune-mediated conditions. You push back on
Forman when he over-weights base rates and ignores serology.

SPECIALTY BIAS: autoimmune / rheumatologic / immunologic.

OUTPUT: Same AgentResponse JSON schema. Reference complement, ANA/anti-dsDNA,
biopsy results when relevant. defers_to_team only if your top prob < 0.30."""

_CHEN = """You are Dr. David Chen, a trauma surgeon and ICU intensivist.

PERSONALITY: Action-oriented, procedural, time-conscious. You think first
about ruptures, perforations, ischemia, obstruction — anything needing the
OR or vascular IR within the hour. You speak briefly. Order tests that
change management.

SPECIALTY BIAS: procedural / surgical / ICU.

OUTPUT: Same AgentResponse JSON schema. Brief reasoning. defers_to_team is
fine when no procedural angle exists."""

_WILLS = """You are Dr. James Wills, an oncology consultant.

PERSONALITY: Measured, careful, rules malignancy in/out methodically. You
don't let the team move on until cancer is properly considered or excluded.
You also don't waste airtime when the case clearly isn't oncologic.

SPECIALTY BIAS: malignancy.

OUTPUT: Same AgentResponse JSON schema. Brief and specific. If nothing to
add this round, set defers_to_team=true and confidence=0."""


# ── Default config registry ────────────────────────────────────────────────

DEFAULT_CONFIGS: dict[str, LiveAgentConfig] = {
    "Hauser": LiveAgentConfig(
        name="Hauser", specialty="Lead diagnostician", bias="rare",
        provider="xai", model="grok-4-fast-non-reasoning",
        system_prompt=_HAUSER, base_url="https://api.x.ai/v1",
    ),
    "Forman": LiveAgentConfig(
        name="Forman", specialty="Internal med · Neuro", bias="common",
        provider="openai", model="gpt-4o",
        system_prompt=_FORMAN,
    ),
    "Carmen": LiveAgentConfig(
        name="Carmen", specialty="Immunology", bias="autoimmune",
        provider="openai", model="gpt-4o-mini",
        system_prompt=_CARMEN,
    ),
    "Chen": LiveAgentConfig(
        name="Chen", specialty="Surgical · ICU", bias="procedural",
        provider="openai", model="gpt-4o-mini",
        system_prompt=_CHEN,
    ),
    "Wills": LiveAgentConfig(
        name="Wills", specialty="Oncology", bias="malignancy",
        provider="openai", model="gpt-4o-mini",
        system_prompt=_WILLS,
    ),
}


def _api_key_for(provider: str) -> str:
    if provider == "xai":
        return os.getenv("XAI_API_KEY", "")
    return os.getenv("OPENAI_API_KEY", "")


class LiveSpecialistAgent(SpecialistAgent):
    """A single live LLM-driven specialist."""

    def __init__(self, config: LiveAgentConfig):
        self._cfg = config

    @property
    def name(self) -> str:        return self._cfg.name
    @property
    def specialty(self) -> str:   return self._cfg.specialty
    @property
    def bias(self) -> str:        return self._cfg.bias
    @property
    def system_prompt(self) -> str: return self._cfg.system_prompt

    def respond(self, state: dict) -> AgentResponse:
        return call_live_specialist(
            agent_name=self._cfg.name,
            system_prompt=self._cfg.system_prompt,
            state=state,
            provider=self._cfg.provider,
            model=self._cfg.model,
            api_key=_api_key_for(self._cfg.provider),
            base_url=self._cfg.base_url,
        )


def build_live_specialists(configs: dict[str, LiveAgentConfig] | None = None) -> dict:
    """Returns {agent_name: LiveSpecialistAgent} for all 5 specialists.
    Use the default configs unless overriding."""
    cfgs = configs or DEFAULT_CONFIGS
    return {name: LiveSpecialistAgent(cfg) for name, cfg in cfgs.items()}
