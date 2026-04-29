"""Dr. Caddick — moderator agent.

CRITICAL: Caddick does NOT propose his own differentials. He synthesizes the
team's positions, identifies disagreements, and (via the routing module)
decides who speaks next.

Routing is deterministic Python code (orchestration.routing.select_next_speakers).
Caddick's LLM is used ONLY to write the synthesis paragraph — the prose that
summarizes the team's current state for the user. This separation makes
routing testable and reproducible.

Mock mode: returns canned synthesis from fixture (under "Caddick" key in
scripted_rounds[*].responses) or generates a deterministic stub.
"""
from __future__ import annotations
import os
from typing import Optional

from dr_holmes.schemas.responses import CaddickSynthesis
from dr_holmes.orchestration.routing import select_next_speakers


SYNTHESIS_PROMPT = """You are Dr. Lisa Caddick, the moderator of a diagnostic team.

You do NOT propose your own differential. Your job is to:
1. Read the team's latest responses
2. Identify the SPECIFIC disagreements (not generic "they disagree")
3. Note which evidence is being weighted differently by which specialist
4. Flag any unaddressed challenges
5. Write 2-4 sentences synthesizing the team's current state

Your output is read by the lead doctor. Be concise, neutral, and surface
the real disagreements. Do not pick a side. Do not propose tests.

Format strictly: a single paragraph, 2-4 sentences. No bullet points.
"""


class CaddickAgent:
    def __init__(self, mode: str = "mock", llm_client=None, llm_model: str = "gpt-4o",
                 mock_scripts: dict[int, dict] | None = None):
        self.mode = mode
        self.client = llm_client
        self.model = llm_model
        self.mock_scripts = mock_scripts or {}

    @property
    def name(self) -> str:
        return "Caddick"

    def synthesize(self, state: dict) -> CaddickSynthesis:
        """Returns a CaddickSynthesis with synthesis text + next_speakers
        (chosen by deterministic routing module)."""
        round_n = state.get("round_number", 0)

        # Routing — deterministic, never an LLM call
        next_speakers, reason = select_next_speakers(state)

        # Synthesis text — LLM in live mode, fixture/stub in mock mode
        if self.mode == "mock":
            canned = self.mock_scripts.get(round_n) or self.mock_scripts.get(str(round_n))
            text = canned.get("synthesis", "") if canned else self._stub_synthesis(state)
        else:
            text = self._live_synthesis(state)

        return CaddickSynthesis(
            round_number=round_n,
            synthesis=text,
            next_speakers=next_speakers,
            routing_reason=reason,
        )

    def _stub_synthesis(self, state: dict) -> str:
        """Deterministic fallback when no scripted text is provided."""
        rn = state.get("round_number", 0)
        ddx = state.get("current_differentials", []) or []
        if not ddx:
            return f"Round {rn}: team taking initial positions; no consensus yet."
        top = ddx[0]
        if isinstance(top, dict):
            top_name = top.get("disease") or top.get("diagnosis") or "?"
            top_prob = float(top.get("probability", 0.0))
        else:
            top_name = (getattr(top, "disease", None)
                        or getattr(top, "diagnosis", None) or "?")
            top_prob = float(getattr(top, "probability", 0.0))
        n_active = len(state.get("active_challenges", []) or [])
        return (f"Round {rn}: top differential {top_name} at {top_prob:.0%}. "
                f"{n_active} unresolved challenge(s). Continuing deliberation.")

    def _live_synthesis(self, state: dict) -> str:
        """Live LLM synthesis. Requires OpenAI client."""
        if self.client is None:
            return self._stub_synthesis(state)

        # Build a compact context for the LLM
        def _name(d):
            if isinstance(d, dict): return d.get("disease") or d.get("diagnosis") or "?"
            return (getattr(d, "disease", None) or getattr(d, "diagnosis", None) or "?")
        def _prob(d):
            if isinstance(d, dict): return float(d.get("probability", 0.0))
            return float(getattr(d, "probability", 0.0))

        ddx = state.get("current_differentials", []) or []
        ddx_text = "\n".join(
            f"  {i+1}. {_name(d)} ({_prob(d):.0%})"
            for i, d in enumerate(ddx[:5])
        ) or "  (no team-level differential yet)"

        responses = state.get("agent_responses", {}) or {}
        last_per_agent = []
        for agent, hist in responses.items():
            if not hist:
                continue
            last = hist[-1]
            top_dx = ""
            if hasattr(last, "differentials") and last.differentials:
                top_dx = f"top: {last.differentials[0].diagnosis} ({last.differentials[0].probability:.0%})"
            elif isinstance(last, dict) and last.get("differentials"):
                d = last["differentials"][0]
                top_dx = f"top: {d['diagnosis']} ({d['probability']:.0%})"
            last_per_agent.append(f"  {agent}: {top_dx}")

        ctx = (
            f"Team state at round {state.get('round_number', 0)}:\n\n"
            f"Current team differential:\n{ddx_text}\n\n"
            f"Each specialist's top:\n" + "\n".join(last_per_agent)
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYNTHESIS_PROMPT},
                    {"role": "user", "content": ctx},
                ],
                max_tokens=200,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return self._stub_synthesis(state) + f" [LLM error: {e}]"
