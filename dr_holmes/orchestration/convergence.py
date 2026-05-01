"""Convergence + escalation + stagnation checks — all deterministic."""
from __future__ import annotations
import re

from dr_holmes.orchestration.constants import (
    CONVERGENCE_PROB, AGREEMENT_COUNT, AGREEMENT_PROB, STABILITY_DELTA,
    MAX_ROUNDS, MIN_ROUNDS_BEFORE_CONVERGE,
    STAGNATION_DELTA, STAGNATION_ROUNDS,
    SPECIALISTS,
)


def _normalize_dx(name: str) -> str:
    """Loose match: lowercase, drop parentheticals/qualifiers/punctuation,
    then canonicalize known abbreviations (STEMI ↔ MI, PE, SLE, etc.)."""
    from dr_holmes.orchestration.aggregation import _canonicalize
    s = (name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)             # drop parenthetical clarifiers
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.split(r"[,:;]", s)[0]                  # drop trailing qualifier
    s = s.replace("'s", "").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _canonicalize(s)


def _dx_tokens_match(team_name: str, spec_name: str) -> bool:
    """Token-set overlap: spec dx matches team dx if their normalized token
    sets have a containment relationship in either direction (handles
    'SLE' ⊆ 'SLE with lupus nephritis' as a match)."""
    t = set(_normalize_dx(team_name).split())
    s = set(_normalize_dx(spec_name).split())
    if not t or not s:
        return False
    if t == s:
        return True
    # require ≥2 shared tokens for partial match (avoid spurious 1-word hits)
    shared = t & s
    if len(shared) < 2 and len(t) > 1 and len(s) > 1:
        return False
    return t.issubset(s) or s.issubset(t)


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _dx_name(obj) -> str:
    """Pull the disease name regardless of which Differential class it is."""
    return _get(obj, "diagnosis") or _get(obj, "disease") or ""


def has_converged(state: dict) -> tuple[bool, str]:
    """Returns (converged, reason). reason explains for logs / final report."""
    rn = state.get("round_number", 0)
    if rn < MIN_ROUNDS_BEFORE_CONVERGE:
        return False, ""

    current_dx = state.get("current_differentials", []) or []
    if not current_dx:
        return False, ""

    top = current_dx[0]
    top_prob = float(_get(top, "probability", 0.0))
    if top_prob < CONVERGENCE_PROB:
        return False, ""

    top_name_raw = _dx_name(top)

    # Cross-specialist agreement check
    responses = state.get("agent_responses", {}) or {}
    agree = 0
    for sp in SPECIALISTS:
        hist = responses.get(sp, [])
        if not hist:
            continue
        last = hist[-1]
        diffs = _get(last, "differentials", []) or []
        for d in diffs[:3]:
            d_name_raw = _dx_name(d)
            d_prob = float(_get(d, "probability", 0.0))
            if _dx_tokens_match(top_name_raw, d_name_raw) and d_prob > AGREEMENT_PROB:
                agree += 1
                break
    if agree < AGREEMENT_COUNT:
        return False, ""

    # No active challenges
    if state.get("active_challenges"):
        return False, ""

    # Last round must be quiet on top dx
    if abs(state.get("last_round_top_delta", 0.0)) > STABILITY_DELTA:
        return False, ""

    return True, "team_agreement"


def has_stagnated(state: dict) -> bool:
    """2 consecutive rounds with delta < STAGNATION_DELTA AND no new evidence
    in either round. If true, force a discriminating test order."""
    if state.get("round_number", 0) < STAGNATION_ROUNDS + 1:
        return False
    last  = abs(state.get("last_round_top_delta",  0.0))
    prev  = abs(state.get("prev_round_top_delta",  0.0))
    if last >= STAGNATION_DELTA or prev >= STAGNATION_DELTA:
        return False
    if state.get("evidence_added_this_round") or state.get("evidence_added_prev_round"):
        return False
    return True


def escalation_reason(state: dict) -> str | None:
    rn = state.get("round_number", 0)
    if rn >= MAX_ROUNDS:
        return "max_rounds"
    if has_stagnated(state):
        return "stagnation_force_test_order"
    current_dx = state.get("current_differentials", []) or []
    if rn >= 3 and len(current_dx) >= 2:
        a = float(_get(current_dx[0], "probability", 0.0))
        b = float(_get(current_dx[1], "probability", 0.0))
        if abs(a - b) < 0.10:
            return "tied_top_2_after_3_rounds"
    return None
