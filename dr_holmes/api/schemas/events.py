"""Pydantic schemas for WebSocket events and client commands."""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, Field


WSEventType = Literal[
    "case_started", "round_started",
    "agent_thinking", "agent_response",
    "tool_call", "tool_result",
    "bayesian_update",
    "challenge_raised", "challenge_resolved",
    "caddick_routing", "convergence_check",
    # Phase 6 HITL
    "case_paused", "case_resumed", "evidence_injected",
    "question_asked", "correction_applied",
    "forced_conclusion", "intervention_failed",
    # Phase 6.6 followup-on-concluded
    "case_reopened",
    "case_converged", "final_report",
    "error",
]


class WSEvent(BaseModel):
    protocol_version: Literal["v1"] = "v1"
    sequence:    int
    case_id:     str
    event_type:  WSEventType
    timestamp:   datetime = Field(default_factory=datetime.utcnow)
    payload:     dict[str, Any]


class WSCommand(BaseModel):
    """Client → server messages."""
    command: Literal[
        "pause", "resume", "inject_evidence",
        "question_agent", "correct_agent",
        "conclude_now", "ack",
    ]
    case_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    client_id: str | None = None


class WSHandshake(BaseModel):
    protocol_version: Literal["v1"] = "v1"
    server_version:   str
    case_id:          str
    last_known_sequence: int = 0
    accepted_commands: list[str] = Field(default_factory=lambda: [
        "pause", "resume", "inject_evidence",
        "question_agent", "correct_agent", "conclude_now", "ack",
    ])
