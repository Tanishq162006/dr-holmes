"""Build mock agent registry from a fixture file.

A fixture's `scripted_rounds` is reshaped per-agent into the
{round_number: response_dict} format that MockSpecialistAgent expects.
"""
from __future__ import annotations
import json
from pathlib import Path

from dr_holmes.agents.specialist_base import MockSpecialistAgent
from dr_holmes.agents.caddick import CaddickAgent
from dr_holmes.orchestration.constants import SPECIALISTS


_SPEC_TO_BIAS = {
    "Hauser": "rare",
    "Forman": "common",
    "Carmen": "autoimmune",
    "Chen":   "procedural",
    "Wills":  "malignancy",
    "Park":   "common",
}
_SPEC_TO_SPECIALTY = {
    "Hauser": "Lead diagnostician",
    "Forman": "Internal med / Neuro",
    "Carmen": "Immunology",
    "Chen":   "Surgical / ICU",
    "Wills":  "Oncology",
    "Park":   "Primary care / Outpatient",
}


def load_fixture(fixture_path: str | Path) -> dict:
    return json.loads(Path(fixture_path).read_text())


def build_mock_agents(fixture: dict) -> tuple[dict, CaddickAgent]:
    """Returns (specialist_registry, caddick_agent) — both mock-mode.

    specialist_registry: {agent_name: MockSpecialistAgent}

    Phase 6: also reads `intervention_responses` from the fixture and indexes
    per-agent so MockSpecialistAgent can pick up scripted reactions to
    interventions (questions, corrections, evidence acknowledgments).
    """
    rounds = fixture.get("scripted_rounds", []) or []

    # Reshape into {agent_name: {round_n: response_dict}}
    per_agent: dict[str, dict[int, dict]] = {a: {} for a in SPECIALISTS}
    caddick_scripts: dict[int, dict] = {}

    for r in rounds:
        rn = int(r.get("round", 0))
        responses = r.get("responses", {}) or {}
        for agent_name, resp in responses.items():
            if agent_name in per_agent:
                per_agent[agent_name][rn] = resp
        if "Caddick" in responses:
            caddick_scripts[rn] = responses["Caddick"]
        if "caddick_synthesis" in r:
            caddick_scripts.setdefault(rn, {})["synthesis"] = r["caddick_synthesis"]

    # Phase 6: per-agent intervention responses
    int_responses_raw: dict[str, dict] = fixture.get("intervention_responses", {}) or {}
    per_agent_int: dict[str, dict[str, dict]] = {a: {} for a in SPECIALISTS}
    caddick_int_responses: dict[str, dict] = {}
    for key, by_agent in int_responses_raw.items():
        for agent_name, resp in (by_agent or {}).items():
            if agent_name in per_agent_int:
                per_agent_int[agent_name][key] = resp
            elif agent_name == "Caddick":
                caddick_int_responses[key] = resp

    registry = {
        name: MockSpecialistAgent(
            name=name,
            specialty=_SPEC_TO_SPECIALTY[name],
            bias=_SPEC_TO_BIAS[name],
            scripted_rounds=per_agent[name],
            intervention_responses=per_agent_int[name],
        )
        for name in SPECIALISTS
    }

    caddick = CaddickAgent(
        mode="mock",
        mock_scripts=caddick_scripts,
        mock_intervention_responses=caddick_int_responses,
    )
    return registry, caddick
