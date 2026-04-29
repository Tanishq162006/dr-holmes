from __future__ import annotations
import json
from typing import Iterator, Callable
from openai import OpenAI
from dr_holmes.models.core import DiagnosticState, AgentMessage, ToolCall
from dr_holmes.intelligence.dispatcher import ToolDispatcher
from datetime import datetime


class BaseAgent:
    def __init__(self, client: OpenAI, model: str, dispatcher: ToolDispatcher | None = None):
        self.client = client
        self.model = model
        self.dispatcher = dispatcher

    @property
    def agent_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def system_prompt(self) -> str: ...

    def _build_messages(self, state: DiagnosticState, rag_context: str = "") -> list[dict]:
        case = state.case
        case_summary = (
            "PATIENT CASE:\n"
            f"Complaint: {case.presenting_complaint}\n"
            f"History: {case.history}\n"
            f"Vitals: {case.vitals}\n"
            f"Labs: {case.labs}\n"
            f"Imaging: {case.imaging}\n"
            f"Meds: {', '.join(case.medications) or 'none'}\n"
            f"Recent findings: {'; '.join(case.additional_findings) or 'none'}\n"
        )
        if rag_context:
            case_summary += f"\nRELEVANT LITERATURE:\n{rag_context}\n"

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.append({"role": "user", "content": case_summary})

        for msg in state.messages:
            if msg.role == "human":
                messages.append({"role": "user", "content": f"[DOCTOR]: {msg.content}"})
            elif msg.agent_id == self.agent_id:
                # Replay this agent's prior turns including any tool calls
                messages.append({"role": "assistant", "content": msg.content})
            else:
                messages.append({
                    "role": "user",
                    "content": f"[{msg.agent_name}]: {msg.content}",
                })

        return messages

    def stream_response(
        self,
        state: DiagnosticState,
        rag_context: str = "",
        on_token: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict, str], None] | None = None,
    ) -> tuple[str, list[ToolCall]]:
        """
        Returns (full_text, tool_calls_made).
        Handles multi-turn tool calling internally.
        """
        messages = self._build_messages(state, rag_context)
        tools = self.dispatcher.tool_schemas() if self.dispatcher else None
        tool_calls_made: list[ToolCall] = []
        _iterations = 0
        _MAX_TOOL_ITERATIONS = 7

        while True:
            if _iterations >= _MAX_TOOL_ITERATIONS:
                break
            _iterations += 1
            kwargs = dict(model=self.model, messages=messages, stream=True, max_tokens=800)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            stream = self.client.chat.completions.create(**kwargs)

            # Collect the full response (may be tool call or text)
            full_text = ""
            current_tool_calls: list[dict] = []
            finish_reason = None

            for chunk in stream:
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta

                if delta.content:
                    full_text += delta.content
                    if on_token:
                        on_token(delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        while len(current_tool_calls) <= idx:
                            current_tool_calls.append({"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            current_tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                current_tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                current_tool_calls[idx]["arguments"] += tc.function.arguments

            if finish_reason == "tool_calls" and current_tool_calls and self.dispatcher:
                # Execute each tool and feed results back
                assistant_msg: dict = {"role": "assistant", "content": None, "tool_calls": []}
                for tc in current_tool_calls:
                    if not tc["name"]:
                        continue
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    result_str = self.dispatcher.dispatch(tc["name"], args)

                    if on_tool_call:
                        on_tool_call(tc["name"], args, result_str)

                    tool_calls_made.append(ToolCall(
                        tool_name=tc["name"],
                        inputs=args,
                        output=result_str,
                        agent_id=self.agent_id,
                    ))

                    assistant_msg["tool_calls"].append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

                messages.append(assistant_msg)
                # Loop back — agent will now write its reasoning
                continue

            # Done — text response received
            return full_text, tool_calls_made

    def respond(
        self,
        state: DiagnosticState,
        rag_context: str = "",
        on_token: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict, str], None] | None = None,
    ) -> AgentMessage:
        full_content, tool_calls = self.stream_response(state, rag_context, on_token, on_tool_call)
        return AgentMessage(
            agent_id=self.agent_id,
            agent_name=self.name,
            role="agent",
            content=full_content,
            timestamp=datetime.now(),
            tool_calls=tool_calls,
        )
