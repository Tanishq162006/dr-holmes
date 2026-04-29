from __future__ import annotations
from typing import Annotated
from langgraph.graph.message import add_messages
from dr_holmes.models.core import DiagnosticState


# LangGraph requires dict-based state; we wrap DiagnosticState fields here
def make_graph_state(state: DiagnosticState) -> dict:
    return {
        "case": state.case.model_dump(),
        "messages": [m.model_dump() for m in state.messages],
        "differentials": [d.model_dump() for d in state.differentials],
        "current_speaker": state.current_speaker,
        "round_number": state.round_number,
        "human_injection": state.human_injection,
        "concluded": state.concluded,
    }


def from_graph_state(data: dict) -> DiagnosticState:
    from dr_holmes.models.core import PatientCase, AgentMessage, Differential
    return DiagnosticState(
        case=PatientCase(**data["case"]),
        messages=[AgentMessage(**m) for m in data.get("messages", [])],
        differentials=[Differential(**d) for d in data.get("differentials", [])],
        current_speaker=data.get("current_speaker", ""),
        round_number=data.get("round_number", 0),
        human_injection=data.get("human_injection", ""),
        concluded=data.get("concluded", False),
    )
