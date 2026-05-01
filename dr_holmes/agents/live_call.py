"""Shared live-LLM call helper — every agent's respond() routes through here.

Why one helper:
- Single place to enforce the budget guard
- Single place to add the special-turn-type system prompt addendum
- Single place to validate AgentResponse JSON
- Single place to handle Grok's xAI API (OpenAI-compatible)
"""
from __future__ import annotations
import json
import os
from typing import Any

from openai import OpenAI

from dr_holmes.safety import budget
from dr_holmes.schemas.responses import (
    AgentResponse, Differential, TestProposal, Challenge, TurnType,
)


# ── Special turn type prompt addendum (Phase 6) ────────────────────────────

_SPECIAL_TURN_ADDENDUM = """

PROBABILITY FORMAT (CRITICAL):
- All `probability` and `confidence` fields are decimals between 0.0 and 1.0.
- 85% confidence is `0.85`, NEVER `85` or `85.0`.
- Outputs above 1.0 are rejected by the API and crash the case.

CONCISENESS (HARD LIMITS — output truncation breaks JSON parsing):
- reasoning: 1-2 sentences MAX
- differentials: at most 3 entries, ranked by probability descending
- each differential's rationale: ≤80 chars
- proposed_tests: at most 2 entries
- challenges: at most 1 per turn (empty list is fine)
- supporting_evidence / contradicting_evidence / rules_in / rules_out: ≤2 items each

USE STANDARD ABBREVIATIONS where commonly used:
- "STEMI" not "ST-elevation myocardial infarction" or "Acute Myocardial Infarction"
- "PE" not "Pulmonary embolism"
- "AAA" not "Abdominal aortic aneurysm"
- "SLE" not "Systemic lupus erythematosus"
- "DKA", "PE", "MI", "CHF" — pick one canonical form per case and stick with it.

SPECIAL TURN TYPES (Phase 6 HITL):
- If the case state has `_active_scheduled_turn` with `turn_type='question_response'`,
  the attending physician asked you a DIRECT QUESTION (in payload.question).
  Answer concisely (2-4 sentences). Do NOT re-emit a full Ddx unless directly
  relevant. Stay in character.

- If `turn_type='correction_response'`, the attending CORRECTED you
  (in payload.correction). You must:
  1. ONE-sentence acknowledgment — no defensive bullshit.
  2. Re-emit your differential with the correction applied.
  3. Note any dx that became more/less likely as a result.

- If `turn_type='evidence_acknowledgment'` (Caddick only), the attending
  injected new evidence (payload.evidence_name + evidence_value). Acknowledge
  briefly and route to the most relevant specialist.

- If `turn_type='forced_conclusion_dissent'`, the team is force-concluding.
  If your top dx differs from the team consensus, give ONE final dissent
  paragraph. Otherwise defer.
"""


# ── Output schema for structured output (per-agent) ────────────────────────

# OpenAI strict mode requires EVERY property to be in `required` (no
# optionals at the property level — use empty list / default value instead).
_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "differentials": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "diagnosis": {"type": "string"},
                    "probability": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                    "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                    "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["diagnosis", "probability", "rationale",
                             "supporting_evidence", "contradicting_evidence"],
                "additionalProperties": False,
            },
        },
        "proposed_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string"},
                    "rationale": {"type": "string"},
                    "rules_in": {"type": "array", "items": {"type": "string"}},
                    "rules_out": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["test_name", "rationale", "rules_in", "rules_out"],
                "additionalProperties": False,
            },
        },
        "challenges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_agent": {"type": "string"},
                    "challenge_type": {
                        "type": "string",
                        "enum": ["disagree_dx", "disagree_test",
                                "missing_consideration", "evidence_mismatch",
                                "personality_call"],
                    },
                    "content": {"type": "string"},
                },
                "required": ["target_agent", "challenge_type", "content"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "defers_to_team": {"type": "boolean"},
        "request_floor": {"type": "boolean"},
        "force_speak": {"type": "boolean"},
    },
    "required": ["reasoning", "differentials", "proposed_tests", "challenges",
                 "confidence", "defers_to_team", "request_floor", "force_speak"],
    "additionalProperties": False,
}


def _format_case_for_prompt(state: dict) -> str:
    """Compact case summary the agent sees as user-message context."""
    case = state.get("patient_presentation", {}) or {}
    rn = state.get("round_number", 0)
    parts = [
        f"=== Round {rn} ===",
        f"Chief complaint: {case.get('presenting_complaint','—')}",
    ]
    if case.get("history"):
        parts.append(f"History: {case['history']}")
    if case.get("vitals"):
        parts.append(f"Vitals: {case['vitals']}")
    if case.get("labs"):
        parts.append(f"Labs: {case['labs']}")
    if case.get("imaging"):
        parts.append(f"Imaging: {case['imaging']}")
    if case.get("medications"):
        parts.append(f"Meds: {', '.join(case['medications'])}")

    # Evidence log additions
    ev_log = state.get("evidence_log", []) or []
    if ev_log:
        recent = ev_log[-5:]
        parts.append("Recent evidence:")
        for e in recent:
            parts.append(f"  - {e.get('name','?')} = {e.get('value','?')} ({e.get('type','')})")

    # Team context: what others said in their last turns
    responses = state.get("agent_responses", {}) or {}
    if responses:
        parts.append("\nTeam's latest positions:")
        for agent, hist in responses.items():
            if not hist:
                continue
            last = hist[-1]
            diffs = (last.get("differentials") if isinstance(last, dict)
                     else getattr(last, "differentials", []))
            if diffs:
                top = diffs[0]
                tdx = top.get("diagnosis") if isinstance(top, dict) else getattr(top, "diagnosis", "")
                tp  = top.get("probability") if isinstance(top, dict) else getattr(top, "probability", 0)
                parts.append(f"  {agent}: {tdx} ({tp:.0%})")

    # Phase 6: special turn payload
    sched = state.get("_active_scheduled_turn")
    if sched:
        ttype = sched.get("turn_type")
        payload = sched.get("payload", {})
        if ttype == "question_response":
            parts.append(f"\n[ATTENDING ASKS YOU]: {payload.get('question','')}")
        elif ttype == "correction_response":
            parts.append(f"\n[ATTENDING CORRECTS YOU]: {payload.get('correction','')}")
        elif ttype == "evidence_acknowledgment":
            parts.append(f"\n[NEW EVIDENCE INJECTED]: {payload.get('evidence_name','')} = {payload.get('evidence_value','')}")

    return "\n".join(parts)


def _safe_parse_response(raw_text: str, agent_name: str, turn_number: int,
                        turn_type: TurnType, intervention_id: str | None) -> AgentResponse:
    """Parse LLM JSON output → AgentResponse with safe defaults."""
    try:
        # Find JSON block (LLM may wrap it)
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON found")
        obj = json.loads(raw_text[start:end + 1])
    except Exception:
        # Fallback: minimal response so the graph doesn't crash
        return AgentResponse(
            agent_name=agent_name, turn_number=turn_number,
            reasoning=f"[parse failure] {raw_text[:200]}",
            confidence=0.0, defers_to_team=True,
            turn_type=turn_type, responding_to=intervention_id,
        )

    # Defensive parsing — Grok models without strict schema sometimes emit
    # nested fields as strings instead of objects. Guard every access.
    def _as_dict(x):
        return x if isinstance(x, dict) else {}
    def _as_list(x):
        return x if isinstance(x, list) else []

    diffs_raw = _as_list(obj.get("differentials"))
    diffs: list[Differential] = []
    for d in diffs_raw[:5]:
        d = _as_dict(d)
        if not d.get("diagnosis"):
            continue
        try:
            prob = float(d.get("probability", 0.0))
        except (TypeError, ValueError):
            prob = 0.0
        # Clamp to [0, 1] in case model emits 50.0 etc.
        prob = max(0.0, min(1.0, prob))
        diffs.append(Differential(
            diagnosis=str(d.get("diagnosis", "?")),
            probability=prob,
            rationale=str(d.get("rationale", ""))[:300],
            supporting_evidence=[str(s) for s in _as_list(d.get("supporting_evidence"))],
            contradicting_evidence=[str(s) for s in _as_list(d.get("contradicting_evidence"))],
        ))

    tests_raw = _as_list(obj.get("proposed_tests"))
    tests: list[TestProposal] = []
    for t in tests_raw[:5]:
        t = _as_dict(t)
        if not t.get("test_name"):
            continue
        tests.append(TestProposal(
            test_name=str(t.get("test_name", "")),
            rationale=str(t.get("rationale", ""))[:200],
            rules_in=[str(s) for s in _as_list(t.get("rules_in"))],
            rules_out=[str(s) for s in _as_list(t.get("rules_out"))],
        ))

    chals_raw = _as_list(obj.get("challenges"))
    chals: list[Challenge] = []
    valid_types = {"disagree_dx", "disagree_test", "missing_consideration",
                   "evidence_mismatch", "personality_call"}
    for c in chals_raw[:3]:
        c = _as_dict(c)
        target = c.get("target_agent")
        if not target:
            continue
        ctype = c.get("challenge_type", "missing_consideration")
        if ctype not in valid_types:
            ctype = "missing_consideration"
        chals.append(Challenge(
            target_agent=str(target),
            challenge_type=ctype,
            content=str(c.get("content", ""))[:500],
        ))

    try:
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))

    return AgentResponse(
        agent_name=agent_name,
        turn_number=turn_number,
        reasoning=str(obj.get("reasoning", ""))[:1500],
        differentials=diffs,
        proposed_tests=tests,
        challenges=chals,
        confidence=conf,
        defers_to_team=bool(obj.get("defers_to_team", False)),
        request_floor=bool(obj.get("request_floor", False)),
        force_speak=bool(obj.get("force_speak", False)),
        turn_type=turn_type,
        responding_to=intervention_id,
    )


# ── The one call helper ──────────────────────────────────────────────────

def call_live_specialist(
    *,
    agent_name: str,
    system_prompt: str,
    state: dict,
    provider: str,                   # "openai" | "xai"
    model: str,
    api_key: str,
    base_url: str | None = None,
) -> AgentResponse:
    """Make a single live LLM call to produce an AgentResponse.

    Enforces all budget guards. Validates output. Stamps turn_type from
    state['_active_scheduled_turn'] if present (Phase 6 HITL).
    """
    if not api_key:
        raise RuntimeError(f"{agent_name}: no API key configured (provider={provider})")

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    case_id = state.get("case_id", "unknown")
    rn = int(state.get("round_number", 0))

    sched = state.get("_active_scheduled_turn") or {}
    turn_type: TurnType = sched.get("turn_type", "normal")  # type: ignore[assignment]
    intervention_id = sched.get("intervention_id")

    full_system = system_prompt + _SPECIAL_TURN_ADDENDUM
    user_msg = _format_case_for_prompt(state) + (
        "\n\nReturn ONLY JSON of the AgentResponse schema. "
        "No prose outside JSON."
    )

    # Cheap projection: ~1.3x the prompt length
    expected_input_tokens = (len(full_system) + len(user_msg)) // 4

    with budget.llm_call_guard(
        case_id=case_id, agent_name=agent_name,
        provider=provider, model=model,
        expected_input_tokens=expected_input_tokens,
    ) as guard:
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=guard.max_tokens,
        )
        # OpenAI: use proper strict structured outputs — guarantees the schema
        # or fails the request. Grok keeps prompt-based JSON (xAI doesn't fully
        # support OpenAI's strict json_schema mode).
        if provider == "openai":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "AgentResponse",
                    "schema": _RESPONSE_JSON_SCHEMA,
                    "strict": True,
                },
            }

        resp = client.chat.completions.create(**kwargs)
        guard.set_actual(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        raw = resp.choices[0].message.content or ""

    return _safe_parse_response(raw, agent_name, rn, turn_type, intervention_id)
