from __future__ import annotations
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


def should_continue(state: dict) -> str:
    if state.get("concluded", False):
        return END
    if state.get("pending_injection", ""):
        return "human_inject"
    speaker = state.get("current_speaker", "holmes")
    return speaker


def build_graph(holmes_node, foreman_node, human_inject_node):
    builder = StateGraph(dict)

    builder.add_node("holmes", holmes_node)
    builder.add_node("foreman", foreman_node)
    builder.add_node("human_inject", human_inject_node)

    builder.set_entry_point("holmes")

    builder.add_conditional_edges("holmes", should_continue, {
        "foreman": "foreman",
        "human_inject": "human_inject",
        END: END,
    })
    builder.add_conditional_edges("foreman", should_continue, {
        "holmes": "holmes",
        "human_inject": "human_inject",
        END: END,
    })
    builder.add_conditional_edges("human_inject", should_continue, {
        "holmes": "holmes",
        "foreman": "foreman",
        END: END,
    })

    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer, interrupt_before=["holmes"])
