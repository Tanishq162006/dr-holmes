"""Cost tracking with hard budget cap.

Pricing as of 2025-Q4. Update PRICES when models or pricing change.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel


# (provider, model) → (input_$/M_tokens, output_$/M_tokens)
PRICES: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-4o"):                       (2.50, 10.00),
    ("openai", "gpt-4o-mini"):                  (0.15,  0.60),
    # xAI current models (verified against xAI dashboard)
    ("xai",    "grok-4.3"):                     (1.25,  2.50),  # confirmed 1M ctx, $1.25/$2.50
    ("xai",    "grok-4-0709"):                  (3.00, 15.00),
    ("xai",    "grok-4-fast-non-reasoning"):    (0.20,  0.50),
    ("xai",    "grok-4-fast-reasoning"):        (0.20,  0.50),
    ("xai",    "grok-4-1-fast-non-reasoning"):  (0.20,  0.50),
    ("xai",    "grok-4-1-fast-reasoning"):      (0.20,  0.50),
    ("xai",    "grok-3"):                       (3.00, 15.00),
    ("xai",    "grok-3-mini"):                  (0.30,  0.50),
    # legacy (eval cache compatibility)
    ("xai",    "grok-2-1212"):                  (2.00, 10.00),
    ("xai",    "grok-beta"):                    (5.00, 15.00),
}


def price_for(provider: str, model: str) -> tuple[float, float]:
    """Returns (input_per_M, output_per_M). Defaults to gpt-4o pricing if unknown."""
    return PRICES.get((provider, model), PRICES[("openai", "gpt-4o")])


def estimate_cost(provider: str, model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = price_for(provider, model)
    return (in_tokens * p_in + out_tokens * p_out) / 1_000_000


class BudgetBreach(Exception):
    pass


class CostReport(BaseModel):
    total_cost_usd: float
    n_calls: int
    cache_hits: int
    by_case: dict[str, float]
    by_agent: dict[str, float]
    by_provider: dict[str, float]
    by_condition: dict[str, float]


@dataclass
class CostTracker:
    """Tracks LLM costs per-case, per-agent, per-provider, with hard budget cap."""
    budget_usd: float = 50.0
    halt_on_breach: bool = True

    _total: float = 0.0
    _n_calls: int = 0
    _n_cache_hits: int = 0
    _by_case:      dict[str, float] = field(default_factory=lambda: defaultdict(float))
    _by_agent:     dict[str, float] = field(default_factory=lambda: defaultdict(float))
    _by_provider:  dict[str, float] = field(default_factory=lambda: defaultdict(float))
    _by_condition: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def add(
        self,
        *,
        provider: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        case_id: str = "",
        agent_name: str = "",
        condition: str = "",
        cache_hit: bool = False,
    ) -> float:
        cost = 0.0 if cache_hit else estimate_cost(provider, model, in_tokens, out_tokens)
        self._total += cost
        self._n_calls += 1
        if cache_hit:
            self._n_cache_hits += 1
        if case_id:      self._by_case[case_id] += cost
        if agent_name:   self._by_agent[agent_name] += cost
        if provider:     self._by_provider[provider] += cost
        if condition:    self._by_condition[condition] += cost

        if self.halt_on_breach and self._total > self.budget_usd * 0.95:
            raise BudgetBreach(
                f"Budget {self.budget_usd:.2f} USD nearly exhausted "
                f"(spent {self._total:.2f} USD across {self._n_calls} calls)"
            )
        return cost

    @property
    def total(self) -> float:    return self._total
    @property
    def n_calls(self) -> int:    return self._n_calls
    @property
    def cache_hits(self) -> int: return self._n_cache_hits

    def cost_for_case(self, case_id: str) -> float:
        return self._by_case.get(case_id, 0.0)

    def report(self) -> CostReport:
        return CostReport(
            total_cost_usd=self._total,
            n_calls=self._n_calls,
            cache_hits=self._n_cache_hits,
            by_case=dict(self._by_case),
            by_agent=dict(self._by_agent),
            by_provider=dict(self._by_provider),
            by_condition=dict(self._by_condition),
        )
