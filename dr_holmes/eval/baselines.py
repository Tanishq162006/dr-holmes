"""Baseline runners — five conditions, uniform output schema.

Each condition implements run_case(case) → BaselineResponse. Output
normalization makes scoring uniform across conditions.

Conditions:
  1. gpt4o_solo       — single GPT-4o call, no tools
  2. grok_solo        — single Grok call, no tools (cross-provider sanity check)
  3. gpt4o_rag        — GPT-4o + ChromaDB retrieval
  4. gpt4o_mi_layer   — GPT-4o + full 9-tool MI dispatcher (no team)
  5. full_team        — Phase 3 multi-agent system
"""
from __future__ import annotations
import json
import os
import time
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from dr_holmes.eval.samplers import DDXPlusCase
from dr_holmes.eval.cache import LLMResponseCache
from dr_holmes.eval.cost import CostTracker
from dr_holmes.schemas.responses import Differential


class BaselineResponse(BaseModel):
    condition: str
    case_id: str
    top_5: list[Differential]
    confidence: float = 0.0
    n_llm_calls: int = 0
    n_tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    wall_clock_seconds: float = 0.0
    error: Optional[str] = None
    raw_output: str = ""


# ── Common case → prompt formatting ────────────────────────────────

def _format_case_for_prompt(case: DDXPlusCase) -> str:
    return (
        f"Patient: {case.age}yo {case.sex}\n"
        f"Findings: {'; '.join(case.evidence_labels[:30])}"
    )


_OUTPUT_SCHEMA_INSTRUCTION = """Output strictly JSON of the form:
{
  "differentials": [
    {"diagnosis": "<name>", "probability": 0.55, "rationale": "<short>"},
    ...up to 5 entries, sorted by probability descending, summing to ≤ 1.0
  ]
}
No prose outside JSON."""


def _parse_top_5(raw: str) -> list[Differential]:
    """Parse JSON output → list of Differentials. Tolerates noise around the JSON."""
    try:
        # find first { ... } block
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return []
        obj = json.loads(raw[start:end + 1])
        diffs = obj.get("differentials", [])[:5]
        return [Differential(
            diagnosis=str(d.get("diagnosis", "?")),
            probability=float(d.get("probability", 0.0)),
            rationale=str(d.get("rationale", ""))[:200],
        ) for d in diffs if d.get("diagnosis")]
    except Exception:
        return []


# ── Base class ─────────────────────────────────────────────────────

class BaselineRunner(ABC):
    condition_name: str = ""
    provider: str = ""
    model: str = ""

    def __init__(self, cache: LLMResponseCache, tracker: CostTracker,
                 prompt_version: str = "v1"):
        self.cache = cache
        self.tracker = tracker
        self.prompt_version = prompt_version

    @abstractmethod
    def run_case(self, case: DDXPlusCase) -> BaselineResponse: ...


# ── 1. gpt4o_solo + grok_solo (single-call baselines) ─────────────

_SOLO_SYSTEM_PROMPT = """You are a careful diagnostic AI. Given a patient case,
return the top 5 most likely diagnoses ranked by probability.

You have no tools, no external lookups. Reason from the case facts alone.
""" + _OUTPUT_SCHEMA_INSTRUCTION


class _SoloBaseline(BaselineRunner):
    """Single LLM call. Subclasses set provider/model/condition_name."""

    def _call_openai(self, messages: list[dict],
                     response_format: dict | None = None) -> tuple[dict, int, int, float]:
        """Single LLM call via OpenAI-compatible client (works for OpenAI + xAI)."""
        from openai import OpenAI
        if self.provider == "xai":
            client = OpenAI(api_key=os.getenv("XAI_API_KEY", ""), base_url="https://api.x.ai/v1")
        else:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        kwargs = dict(model=self.model, messages=messages,
                      temperature=0.0, max_tokens=600)
        if response_format:
            kwargs["response_format"] = response_format
        resp = client.chat.completions.create(**kwargs)
        in_tok = resp.usage.prompt_tokens
        out_tok = resp.usage.completion_tokens
        from dr_holmes.eval.cost import estimate_cost
        cost = estimate_cost(self.provider, self.model, in_tok, out_tok)
        return ({"content": resp.choices[0].message.content}, in_tok, out_tok, cost)

    def run_case(self, case: DDXPlusCase) -> BaselineResponse:
        start = time.time()
        messages = [
            {"role": "system", "content": _SOLO_SYSTEM_PROMPT},
            {"role": "user", "content": _format_case_for_prompt(case)},
        ]
        # Grok currently doesn't support response_format=json_object on all
        # models; OpenAI does. We pass it conditionally so the cache key stays
        # stable per-provider.
        rf = {"type": "json_object"} if self.provider == "openai" else None
        try:
            cached = self.cache.get_or_call(
                provider=self.provider,
                model=self.model,
                prompt_version=self.prompt_version,
                messages=messages,
                temperature=0.0,
                max_tokens=600,
                response_format=rf,
                call_fn=lambda: self._call_openai(messages, rf),
                metadata={"case_id": case.case_id, "condition": self.condition_name},
            )
            self.tracker.add(
                provider=self.provider, model=self.model,
                in_tokens=cached.input_tokens, out_tokens=cached.output_tokens,
                case_id=case.case_id, condition=self.condition_name,
                cache_hit=cached.cache_hit,
            )
            raw = cached.response.get("content", "")
            top_5 = _parse_top_5(raw)
            return BaselineResponse(
                condition=self.condition_name,
                case_id=case.case_id,
                top_5=top_5,
                confidence=top_5[0].probability if top_5 else 0.0,
                n_llm_calls=1,
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                cost_usd=cached.cost_usd if not cached.cache_hit else 0.0,
                wall_clock_seconds=time.time() - start,
                raw_output=raw[:500],
            )
        except Exception as e:
            return BaselineResponse(
                condition=self.condition_name,
                case_id=case.case_id, top_5=[],
                error=f"{type(e).__name__}: {e}",
                wall_clock_seconds=time.time() - start,
            )


class GPT4oSolo(_SoloBaseline):
    condition_name = "gpt4o_solo"
    provider = "openai"
    model = "gpt-4o"


class GrokSolo(_SoloBaseline):
    """Cross-provider sanity check: same prompt as gpt4o_solo, different family."""
    condition_name = "grok_solo"
    provider = "xai"
    model = "grok-2-1212"


# ── 3. gpt4o_rag — GPT-4o with ChromaDB retrieval ──────────────────

class GPT4oRAG(_SoloBaseline):
    condition_name = "gpt4o_rag"
    provider = "openai"
    model = "gpt-4o"

    def __init__(self, cache, tracker, chroma_collection, prompt_version="v1", top_k=5):
        super().__init__(cache, tracker, prompt_version)
        self.chroma = chroma_collection
        self.top_k = top_k

    def run_case(self, case: DDXPlusCase) -> BaselineResponse:
        start = time.time()
        # Retrieve top-K from ChromaDB
        query = " ".join(case.evidence_labels[:5])
        try:
            results = self.chroma.query(query_texts=[query], n_results=self.top_k)
            docs = results.get("documents", [[]])[0]
            rag_context = "\n---\n".join(docs)[:3000]
        except Exception:
            rag_context = ""

        messages = [
            {"role": "system", "content": _SOLO_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"{_format_case_for_prompt(case)}\n\n"
                f"Relevant case literature (retrieved):\n{rag_context}\n"
            )},
        ]
        # Reuse parent's cache + parse
        try:
            cached = self.cache.get_or_call(
                provider=self.provider, model=self.model,
                prompt_version=self.prompt_version,
                messages=messages, temperature=0.0, max_tokens=600,
                response_format={"type": "json_object"},
                call_fn=lambda: self._call_openai(messages, {"type": "json_object"}),
                metadata={"case_id": case.case_id, "condition": self.condition_name},
            )
            self.tracker.add(
                provider=self.provider, model=self.model,
                in_tokens=cached.input_tokens, out_tokens=cached.output_tokens,
                case_id=case.case_id, condition=self.condition_name,
                cache_hit=cached.cache_hit,
            )
            raw = cached.response.get("content", "")
            top_5 = _parse_top_5(raw)
            return BaselineResponse(
                condition=self.condition_name, case_id=case.case_id,
                top_5=top_5,
                confidence=top_5[0].probability if top_5 else 0.0,
                n_llm_calls=1,
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                cost_usd=cached.cost_usd if not cached.cache_hit else 0.0,
                wall_clock_seconds=time.time() - start,
                raw_output=raw[:500],
            )
        except Exception as e:
            return BaselineResponse(
                condition=self.condition_name, case_id=case.case_id, top_5=[],
                error=f"{type(e).__name__}: {e}",
                wall_clock_seconds=time.time() - start,
            )


# ── 4. gpt4o_mi_layer — single agent + full MI tools ───────────────

_MI_SYSTEM_PROMPT = """You are a diagnostic AI with access to a Medical Intelligence
toolset (Bayesian engine, knowledge graph, case literature, drug interactions,
red flags). Use the tools as needed, then return your final top-5 differential.

When you're done with tool calls, output your final answer as strict JSON of:
{"differentials": [{"diagnosis": "...", "probability": 0.X, "rationale": "..."}, ...]}
"""


class GPT4oMILayer(BaselineRunner):
    condition_name = "gpt4o_mi_layer"
    provider = "openai"
    model = "gpt-4o"

    def __init__(self, cache, tracker, dispatcher, prompt_version="v1", max_tool_iters=8):
        super().__init__(cache, tracker, prompt_version)
        self.dispatcher = dispatcher
        self.max_iters = max_tool_iters

    def run_case(self, case: DDXPlusCase) -> BaselineResponse:
        from openai import OpenAI
        from dr_holmes.eval.cost import estimate_cost
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        tools = self.dispatcher.tool_schemas()

        messages: list[dict] = [
            {"role": "system", "content": _MI_SYSTEM_PROMPT},
            {"role": "user",   "content": _format_case_for_prompt(case)},
        ]
        start = time.time()
        n_calls = 0
        n_tool_calls = 0
        in_tok_total = 0
        out_tok_total = 0
        final_raw = ""

        try:
            for _ in range(self.max_iters):
                # Cache key includes the running message list (tool-call loop creates unique prefixes)
                cached = self.cache.get_or_call(
                    provider=self.provider, model=self.model,
                    prompt_version=self.prompt_version,
                    messages=messages, tools=tools,
                    temperature=0.0, max_tokens=600,
                    call_fn=lambda: self._call_with_tools(client, messages, tools),
                    metadata={"case_id": case.case_id, "condition": self.condition_name},
                )
                self.tracker.add(
                    provider=self.provider, model=self.model,
                    in_tokens=cached.input_tokens, out_tokens=cached.output_tokens,
                    case_id=case.case_id, condition=self.condition_name,
                    cache_hit=cached.cache_hit,
                )
                in_tok_total += cached.input_tokens
                out_tok_total += cached.output_tokens
                n_calls += 1

                resp_dict = cached.response
                msg = resp_dict.get("message", {})
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    # Final answer
                    final_raw = msg.get("content") or ""
                    break

                # Append assistant tool-call message + each tool result
                messages.append({"role": "assistant", "content": msg.get("content"),
                                 "tool_calls": tool_calls})
                for tc in tool_calls:
                    n_tool_calls += 1
                    fn = tc.get("function", {})
                    args = json.loads(fn.get("arguments") or "{}")
                    result = self.dispatcher.dispatch(fn.get("name"), args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": result,
                    })

            top_5 = _parse_top_5(final_raw)
            return BaselineResponse(
                condition=self.condition_name, case_id=case.case_id,
                top_5=top_5,
                confidence=top_5[0].probability if top_5 else 0.0,
                n_llm_calls=n_calls,
                n_tool_calls=n_tool_calls,
                input_tokens=in_tok_total,
                output_tokens=out_tok_total,
                cost_usd=estimate_cost(self.provider, self.model, in_tok_total, out_tok_total),
                wall_clock_seconds=time.time() - start,
                raw_output=final_raw[:500],
            )
        except Exception as e:
            return BaselineResponse(
                condition=self.condition_name, case_id=case.case_id, top_5=[],
                error=f"{type(e).__name__}: {e}",
                n_llm_calls=n_calls, n_tool_calls=n_tool_calls,
                wall_clock_seconds=time.time() - start,
            )

    def _call_with_tools(self, client, messages, tools):
        from dr_holmes.eval.cost import estimate_cost
        resp = client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, tool_choice="auto",
            temperature=0.0, max_tokens=600,
        )
        msg = resp.choices[0].message
        # Serialize the message + tool_calls into a JSON-able dict
        msg_dict = {"content": msg.content}
        if msg.tool_calls:
            msg_dict["tool_calls"] = [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name,
                             "arguments": tc.function.arguments},
            } for tc in msg.tool_calls]
        in_tok = resp.usage.prompt_tokens
        out_tok = resp.usage.completion_tokens
        cost = estimate_cost(self.provider, self.model, in_tok, out_tok)
        return ({"message": msg_dict}, in_tok, out_tok, cost)


# ── 5. full_team — Phase 3 multi-agent system ──────────────────────

class FullTeamBaseline(BaselineRunner):
    """Wraps the Phase 3 LangGraph state machine.

    Live mode requires API keys for all 5 specialists + Caddick. Without keys,
    use mock mode (provide a fixture_path) — useful for sanity-testing the
    eval pipeline without LLM cost.
    """
    condition_name = "full_team"

    def __init__(self, cache, tracker, *, mock_fixture: Optional[str] = None,
                 prompt_version="v1"):
        super().__init__(cache, tracker, prompt_version)
        self.mock_fixture = mock_fixture

    def run_case(self, case: DDXPlusCase) -> BaselineResponse:
        from dr_holmes.orchestration.builder import build_phase3_graph, RenderHooks
        from dr_holmes.orchestration.mock_agents import build_mock_agents, load_fixture
        from dr_holmes.safety import budget as _budget

        start = time.time()

        # Capture safety-budget snapshot BEFORE the case so we can compute per-case cost
        cost_before = _budget.session_total_usd()
        calls_before = _budget.snapshot()["n_calls"]

        try:
            if self.mock_fixture:
                fixture = load_fixture(self.mock_fixture)
                registry, caddick = build_mock_agents(fixture)
            else:
                # Live mode — uses OPENAI_API_KEY + XAI_API_KEY from env.
                # Same path as the API runner's _run_live_case.
                from openai import OpenAI as _OAI
                from dr_holmes.agents.live_specialist import build_live_specialists
                from dr_holmes.agents.caddick import CaddickAgent
                _budget.assert_live_allowed()
                registry = build_live_specialists()
                caddick_client = _OAI(api_key=os.getenv("OPENAI_API_KEY", ""))
                caddick = CaddickAgent(mode="live", llm_client=caddick_client,
                                       llm_model="gpt-4o")
            final_holder = []
            hooks = RenderHooks(on_final=final_holder.append)
            graph = build_phase3_graph(registry, caddick, hooks)
            result = graph.invoke({
                "case_id": case.case_id,
                "patient_presentation": case.patient_presentation(),
            }, config={"recursion_limit": 80})

            final = final_holder[-1] if final_holder else None
            top_5: list[Differential] = []
            confidence = 0.0
            if final and final.recommended_workup is not None:
                # Pull team differential from final report
                report_dict = result.get("final_report") or {}
                consensus = report_dict.get("consensus_dx", "")
                conf = float(report_dict.get("confidence", 0.0))
                # The team differential isn't directly stored in FinalReport;
                # reconstruct top_5 from the last agent_response top picks.
                from collections import defaultdict
                votes: dict[str, list[float]] = defaultdict(list)
                for agent_hist in (result.get("agent_responses") or {}).values():
                    if not agent_hist:
                        continue
                    last = agent_hist[-1]
                    diffs = (last.differentials if hasattr(last, "differentials")
                             else last.get("differentials", []))
                    for d in (diffs or [])[:3]:
                        name = d.diagnosis if hasattr(d, "diagnosis") else d.get("diagnosis", "")
                        prob = float(d.probability if hasattr(d, "probability") else d.get("probability", 0.0))
                        if name:
                            votes[name].append(prob)
                # Average prob per dx, sort
                ranked = sorted(
                    [(name, sum(probs)/len(probs)) for name, probs in votes.items()],
                    key=lambda x: -x[1],
                )[:5]
                top_5 = [Differential(diagnosis=n, probability=p) for n, p in ranked]
                confidence = top_5[0].probability if top_5 else conf

            # Capture actual spend (live mode hits the in-process safety tracker
            # via call_live_specialist; mock mode is always $0)
            cost_delta = _budget.session_total_usd() - cost_before
            calls_delta = _budget.snapshot()["n_calls"] - calls_before
            # Also push to the eval's CostTracker for headline aggregation
            if cost_delta > 0 and self.tracker is not None:
                # Synthetic record: live agents already charged the safety budget,
                # but the eval's CostTracker needs an entry so per-condition totals
                # reflect reality.
                self.tracker._total += cost_delta  # noqa: SLF001
                self.tracker._n_calls += calls_delta
                self.tracker._by_case[case.case_id] += cost_delta
                self.tracker._by_condition[self.condition_name] += cost_delta

            return BaselineResponse(
                condition=self.condition_name, case_id=case.case_id,
                top_5=top_5, confidence=confidence,
                n_llm_calls=calls_delta,
                n_tool_calls=0,
                cost_usd=cost_delta,
                wall_clock_seconds=time.time() - start,
            )
        except Exception as e:
            return BaselineResponse(
                condition=self.condition_name, case_id=case.case_id, top_5=[],
                error=f"{type(e).__name__}: {e}",
                wall_clock_seconds=time.time() - start,
            )
