"""LangGraph event → WSEvent translator.

Listens to graph.astream_events(version='v2'). Converts node-level events into
the wire schema. Tracks state needed to derive synthetic events (round_started,
challenge_resolved, etc.).
"""
from __future__ import annotations
from typing import Iterator, AsyncIterator, Any
from datetime import datetime

from dr_holmes.api.schemas.events import WSEvent


class EventTranslator:
    """Stateful translator. One instance per case run."""

    def __init__(self, case_id: str):
        self.case_id = case_id
        self._last_round = 0
        self._last_top_prob: float | None = None
        self._last_top_dx: str | None = None
        self._known_challenges: set[str] = set()
        self._round_announced: set[int] = set()
        self._tool_call_starts: dict[str, float] = {}    # tool_call_id → start_ts

    def _ev(self, event_type: str, payload: dict) -> dict:
        """Build a WSEvent dict (sequence assigned by caller)."""
        return {
            "protocol_version": "v1",
            "sequence": -1,        # filled in by writer
            "case_id": self.case_id,
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": payload,
        }

    def translate(self, lg_event: dict) -> Iterator[dict]:
        """Yield zero or more WSEvent dicts for a single LangGraph event."""
        ev_name = lg_event.get("event", "")
        name    = lg_event.get("name", "")
        data    = lg_event.get("data", {}) or {}

        # ── LLM token streaming ──────────────────────────────────────
        if ev_name == "on_chat_model_stream":
            chunk = data.get("chunk")
            txt = ""
            if chunk is not None:
                txt = getattr(chunk, "content", None)
                if not txt and hasattr(chunk, "text"):
                    txt = chunk.text
                if not txt:
                    txt = str(chunk) if chunk else ""
            if txt:
                # Best-effort agent attribution from metadata (LangGraph runnable_name)
                metadata = lg_event.get("metadata", {}) or {}
                agent = (metadata.get("agent_name") or
                         metadata.get("ls_run_name") or "")
                yield self._ev("agent_thinking", {
                    "agent_name": agent,
                    "partial_text": txt,
                })
            return

        # ── Tool calls ───────────────────────────────────────────────
        if ev_name == "on_tool_start":
            run_id = lg_event.get("run_id", "")
            self._tool_call_starts[run_id] = datetime.utcnow().timestamp()
            yield self._ev("tool_call", {
                "tool_call_id": str(run_id),
                "tool_name": name,
                "args": data.get("input", {}),
            })
            return

        if ev_name == "on_tool_end":
            run_id = lg_event.get("run_id", "")
            start = self._tool_call_starts.pop(run_id, None)
            latency = int((datetime.utcnow().timestamp() - start) * 1000) if start else None
            output = data.get("output", "")
            preview = str(output)[:300]
            yield self._ev("tool_result", {
                "tool_call_id": str(run_id),
                "result_preview": preview,
                "latency_ms": latency,
            })
            return

        # ── Node-level chain events ──────────────────────────────────
        if ev_name == "on_chain_start" and name == "patient_intake":
            input_state = data.get("input", {}) or {}
            yield self._ev("case_started", {
                "patient_presentation": input_state.get("patient_presentation", {}),
                "agents": ["Hauser", "Forman", "Carmen", "Chen", "Wills", "Caddick"],
                "mock_mode": True,
            })
            return

        if ev_name == "on_chain_end" and name == "patient_intake":
            output = data.get("output", {}) or {}
            rn = output.get("round_number", 1)
            if rn not in self._round_announced:
                self._round_announced.add(rn)
                yield self._ev("round_started", {
                    "round_number": rn,
                    "planned_speakers": output.get("next_speakers", []),
                })
            return

        if ev_name == "on_chain_end" and name == "specialist_response":
            output = data.get("output", {}) or {}
            responses = output.get("agent_responses", {})
            for agent, hist in responses.items():
                if not hist:
                    continue
                last = hist[-1]
                resp_dict = (last.model_dump() if hasattr(last, "model_dump")
                             else dict(last))
                yield self._ev("agent_response", {
                    "agent_name": agent,
                    "response": resp_dict,
                })
                # Emit challenge_raised for each new challenge
                for ch in resp_dict.get("challenges", []) or []:
                    key = f"{agent}->{ch.get('target_agent','')}@{resp_dict.get('turn_number',0)}:{ch.get('content','')[:40]}"
                    if key in self._known_challenges:
                        continue
                    self._known_challenges.add(key)
                    yield self._ev("challenge_raised", {
                        "raiser": agent,
                        "target": ch.get("target_agent"),
                        "challenge_type": ch.get("challenge_type"),
                        "content": ch.get("content"),
                    })
            return

        if ev_name == "on_chain_end" and name == "bayesian_update":
            output = data.get("output", {}) or {}
            ddx = output.get("current_differentials", []) or []
            if not ddx:
                return
            top = ddx[0]
            disease = (top.disease if hasattr(top, "disease")
                       else top.get("disease", "?") if isinstance(top, dict) else "?")
            prob = float(top.probability if hasattr(top, "probability")
                         else top.get("probability", 0.0) if isinstance(top, dict) else 0.0)
            change = (prob - self._last_top_prob) if self._last_top_prob is not None else 0.0
            yield self._ev("bayesian_update", {
                "top_dx": disease,
                "top_prob": prob,
                "deltas": [{"disease": disease,
                            "prev": self._last_top_prob,
                            "now":  prob,
                            "change": change}],
            })
            self._last_top_prob = prob
            self._last_top_dx   = disease
            return

        if ev_name == "on_chain_end" and name == "caddick_synthesis":
            output = data.get("output", {}) or {}
            history = output.get("caddick_synthesis_history", []) or []
            if history:
                synth = history[-1]
                synth_dict = (synth.model_dump() if hasattr(synth, "model_dump")
                              else dict(synth))
                yield self._ev("caddick_routing", {
                    "next_speakers": synth_dict.get("next_speakers", []),
                    "routing_reason": synth_dict.get("routing_reason", ""),
                    "synthesis_text": synth_dict.get("synthesis", ""),
                })
            return

        if ev_name == "on_chain_end" and name == "increment_round":
            output = data.get("output", {}) or {}
            rn = output.get("round_number", 0)
            if rn and rn not in self._round_announced:
                self._round_announced.add(rn)
                yield self._ev("round_started", {
                    "round_number": rn,
                    "planned_speakers": [],
                })
            return

        if ev_name == "on_chain_end" and name == "final_report":
            output = data.get("output", {}) or {}
            report = output.get("final_report") or {}
            yield self._ev("case_converged", {
                "consensus_dx": report.get("consensus_dx", ""),
                "confidence": report.get("confidence", 0.0),
                "convergence_reason": report.get("convergence_reason", ""),
                "rounds_taken": report.get("rounds_taken", 0),
            })
            yield self._ev("final_report", {"report": report})
            return
