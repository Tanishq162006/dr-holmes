from __future__ import annotations
import json
from typing import Callable, Any
from dr_holmes.models.core import AgentMessage, DiagnosticState, Differential
from dr_holmes.graph.state import from_graph_state
from datetime import datetime


def _make_node(agent, agent_id: str, next_speaker: str, on_token, on_tool_call):
    def node(state: dict) -> dict:
        ds = from_graph_state(state)

        def token_cb(token: str):
            if on_token:
                on_token(agent_id, token)

        def tool_cb(tool_name: str, args: dict, result: str):
            if on_tool_call:
                on_tool_call(agent_id, tool_name, args, result)

        if on_token:
            on_token(agent_id, None, start=True)

        full_content, tool_calls = agent.stream_response(
            ds,
            rag_context="",
            on_token=token_cb,
            on_tool_call=tool_cb,
        )

        if on_token:
            on_token(agent_id, None, end=True)

        msg = AgentMessage(
            agent_id=agent_id,
            agent_name=agent.name,
            role="agent",
            content=full_content,
            timestamp=datetime.now(),
            tool_calls=tool_calls,
        )

        # Sync dispatcher differentials to state
        updated_dx = state.get("differentials", [])
        if agent.dispatcher and agent.dispatcher._active_dx:
            updated_dx = [d.model_dump() for d in agent.dispatcher._active_dx]

        updated = state.copy()
        updated["messages"] = state["messages"] + [msg.model_dump()]
        updated["differentials"] = updated_dx
        updated["current_speaker"] = next_speaker
        updated["round_number"] = state.get("round_number", 0) + 1
        updated["human_injection"] = ""
        return updated

    return node


def make_hauser_node(agent, on_token=None, on_tool_call=None):
    return _make_node(agent, "hauser", "forman", on_token, on_tool_call)


def make_forman_node(agent, on_token=None, on_tool_call=None):
    return _make_node(agent, "forman", "hauser", on_token, on_tool_call)


def make_human_inject_node(on_inject=None):
    def human_inject_node(state: dict) -> dict:
        injection = state.get("pending_injection", "")
        if not injection:
            return state
        msg = AgentMessage(
            agent_id="human",
            agent_name="Doctor",
            role="human",
            content=injection,
            timestamp=datetime.now(),
        )
        updated = state.copy()
        updated["messages"] = state["messages"] + [msg.model_dump()]
        updated["human_injection"] = injection
        updated["pending_injection"] = ""
        if on_inject:
            on_inject(injection)
        return updated
    return human_inject_node
