"""Agent metadata endpoints."""
from fastapi import APIRouter, HTTPException
from dr_holmes.api.schemas.requests import AgentProfile

router = APIRouter(prefix="/api/agents", tags=["agents"])

_AGENTS: dict[str, AgentProfile] = {
    "Hauser":  AgentProfile(name="Hauser",  specialty="Lead diagnostician",
                            bias="rare",       model_provider="xai",
                            model_id="grok-2-1212",
                            description="Contrarian, blunt, hunts zebras."),
    "Forman":  AgentProfile(name="Forman",  specialty="Internal med / Neuro",
                            bias="common",     model_provider="openai",
                            model_id="gpt-4o",
                            description="Evidence-based, methodical, base rates."),
    "Carmen":  AgentProfile(name="Carmen",  specialty="Immunology",
                            bias="autoimmune", model_provider="anthropic",
                            model_id="claude-3-5-sonnet-20241022",
                            description="Empathetic but rigorous on autoimmune workup."),
    "Chen":    AgentProfile(name="Chen",    specialty="Surgical / ICU",
                            bias="procedural", model_provider="openai",
                            model_id="gpt-4o-mini",
                            description="Action-oriented, time-critical."),
    "Wills":   AgentProfile(name="Wills",   specialty="Oncology",
                            bias="malignancy", model_provider="anthropic",
                            model_id="claude-3-5-haiku-20241022",
                            description="Rules malignancy in/out methodically."),
    "Caddick": AgentProfile(name="Caddick", specialty="Moderator",
                            bias="n/a",        model_provider="openai",
                            model_id="gpt-4o",
                            description="Moderator. Synthesis only — does not propose Ddx."),
}


@router.get("", response_model=list[AgentProfile])
async def list_agents():
    return list(_AGENTS.values())


@router.get("/{name}/profile", response_model=AgentProfile)
async def agent_profile(name: str):
    if name not in _AGENTS:
        raise HTTPException(404, f"Agent {name!r} not found")
    return _AGENTS[name]
