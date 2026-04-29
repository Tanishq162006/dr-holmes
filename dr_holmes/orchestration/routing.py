"""Caddick routing logic — pure Python, no LLM call.

LLM is used only to write the synthesis paragraph. Choosing who speaks next
is deterministic so it's testable, reproducible, and not flaky.
"""
from __future__ import annotations
from typing import Any
import re

from dr_holmes.orchestration.constants import (
    SPECIALISTS, SPECIALTY_LOOKUP,
)


def _classify_dx(diagnosis: str) -> list[str]:
    """Lightweight rule-based classifier — returns category keywords."""
    s = diagnosis.lower()
    cats: list[str] = []
    if any(k in s for k in ["lupus", "sjogren", "vasculitis", "autoimmune",
                            "sarcoid", "myositis", "rheumatoid", "scleroderma",
                            "psoriatic"]):
        cats.append("autoimmune")
    if any(k in s for k in ["cancer", "lymphoma", "leukemia", "carcinoma",
                            "malignant", "tumor", "neoplasm", "metastasis",
                            "myeloma", "sarcoma"]):
        cats.append("malignancy")
    if any(k in s for k in ["rupture", "obstruction", "torsion", "perforation",
                            "appendicitis", "cholangitis", "ischemia",
                            "abscess", "fracture", "dissection"]):
        cats.append("surgical")
    if any(k in s for k in ["stroke", "seizure", "migraine", "neuropathy",
                            "myasthenia", "guillain", "encephalitis",
                            "meningitis"]):
        cats.append("neurologic")
    if any(k in s for k in ["whipple", "porphyria", "pheochromocytoma",
                            "amyloidosis", "wilson disease", "fabry"]):
        cats.append("rare")
    return cats


def specialty_for_dx(diagnosis: str) -> str | None:
    cats = _classify_dx(diagnosis)
    for c in cats:
        if c in SPECIALTY_LOOKUP:
            return SPECIALTY_LOOKUP[c]
    return None


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def compute_confidence_deltas(
    agent_responses: dict[str, list[Any]],
) -> dict[str, float]:
    """Per-agent: |confidence delta from previous turn|. Big mover = likely
    has new info to share."""
    deltas: dict[str, float] = {}
    for agent, hist in agent_responses.items():
        if len(hist) < 2:
            continue
        cur = float(_get(hist[-1], "confidence", 0.5))
        prev = float(_get(hist[-2], "confidence", 0.5))
        deltas[agent] = abs(cur - prev)
    return deltas


def select_next_speakers(state: dict) -> tuple[list[str], str]:
    """Returns (speakers, reason). reason names which routing rule fired —
    useful for tests, debugging, and CLI display."""
    last_speakers = state.get("last_speakers", []) or []
    agent_responses = state.get("agent_responses", {}) or {}
    active_challenges = state.get("active_challenges", []) or []
    current_dx = state.get("current_differentials", []) or []

    # 1. Hauser interrupt privilege (once per case)
    if state.get("hauser_force_speak") and not state.get("hauser_interrupt_used"):
        return ["Hauser"], "hauser_interrupt"

    # 2. Floor requests
    floor: list[str] = []
    for agent, hist in agent_responses.items():
        if not hist:
            continue
        if _get(hist[-1], "request_floor", False) and agent not in last_speakers:
            floor.append(agent)
    if floor:
        return floor[:2], "floor_request"

    # 3. Unaddressed challenges
    targeted = []
    for ch in active_challenges:
        target = _get(ch, "target_agent")
        if target and target not in last_speakers and target in SPECIALISTS:
            targeted.append(target)
    if targeted:
        # dedupe preserving order
        seen, out = set(), []
        for t in targeted:
            if t not in seen:
                seen.add(t); out.append(t)
        return out[:2], "challenge_response"

    # 4. Specialty match against top differential
    if current_dx:
        top = current_dx[0]
        top_name = _get(top, "diagnosis") or _get(top, "disease") or ""
        match = specialty_for_dx(top_name)
        if match and match not in last_speakers:
            return [match], "specialty_match"

    # 5. Highest confidence delta
    deltas = compute_confidence_deltas(agent_responses)
    movers = [
        a for a, d in sorted(deltas.items(), key=lambda x: -x[1])
        if d > 0.05 and a not in last_speakers
    ]
    if movers:
        return movers[:2], "confidence_delta"

    # 6. Round-robin among silent specialists
    silent = [a for a in SPECIALISTS if a not in last_speakers]
    if silent:
        return [silent[0]], "round_robin"

    # Nothing left — start fresh round
    return [SPECIALISTS[0]], "reset_round_robin"
