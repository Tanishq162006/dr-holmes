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
}
_SPEC_TO_SPECIALTY = {
    "Hauser": "Lead diagnostician",
    "Forman": "Internal med / Neuro",
    "Carmen": "Immunology",
    "Chen":   "Surgical / ICU",
    "Wills":  "Oncology",
}


def load_fixture(fixture_path: str | Path) -> dict:
    return json.loads(Path(fixture_path).read_text())


def build_mock_agents(fixture: dict) -> tuple[dict, CaddickAgent]:
    """Returns (specialist_registry, caddick_agent) — both mock-mode.

    specialist_registry: {agent_name: MockSpecialistAgent}
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
        # Optionally fixtures provide a top-level synthesis text
        if "caddick_synthesis" in r:
            caddick_scripts.setdefault(rn, {})["synthesis"] = r["caddick_synthesis"]

    registry = {
        name: MockSpecialistAgent(
            name=name,
            specialty=_SPEC_TO_SPECIALTY[name],
            bias=_SPEC_TO_BIAS[name],
            scripted_rounds=per_agent[name],
        )
        for name in SPECIALISTS
    }

    caddick = CaddickAgent(mode="mock", mock_scripts=caddick_scripts)
    return registry, caddick
