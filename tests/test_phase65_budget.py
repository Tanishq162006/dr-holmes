"""Phase 6.5 — strict budget enforcement tests.

All tests run without making LLM calls — they verify the guard rails fire
correctly when triggered."""
from __future__ import annotations
import os

import pytest

from dr_holmes.safety import budget


@pytest.fixture(autouse=True)
def reset_budget_and_env():
    budget.reset_for_tests()
    saved = {
        k: os.environ.get(k) for k in (
            "DR_HOLMES_ALLOW_LIVE", "DR_HOLMES_MAX_BUDGET_USD",
            "DR_HOLMES_MAX_COST_PER_CASE_USD", "DR_HOLMES_MAX_TOKENS_PER_CALL",
        )
    }
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    budget.reset_for_tests()


def test_live_mode_disabled_by_default():
    os.environ.pop("DR_HOLMES_ALLOW_LIVE", None)
    assert budget.live_mode_enabled() is False
    with pytest.raises(budget.LiveModeDisabled):
        budget.assert_live_allowed()


def test_live_mode_enabled_with_env_var():
    os.environ["DR_HOLMES_ALLOW_LIVE"] = "true"
    assert budget.live_mode_enabled() is True
    budget.assert_live_allowed()  # no raise


def test_session_budget_breach():
    os.environ["DR_HOLMES_MAX_BUDGET_USD"] = "1.00"
    os.environ["DR_HOLMES_MAX_COST_PER_CASE_USD"] = "10.00"  # disable per-case for this test
    budget.reset_for_tests()
    # Just under cap — fine
    budget.assert_within_budget(case_id="c1", projected_cost=0.50)
    # Force two recorded calls totaling near session cap
    budget.record_call(case_id="c1", agent_name="A",
                       provider="openai", model="gpt-4o",
                       input_tokens=200_000, output_tokens=0)   # ~0.50 USD
    budget.record_call(case_id="c2", agent_name="A",
                       provider="openai", model="gpt-4o",
                       input_tokens=160_000, output_tokens=0)   # ~0.40 USD; total ~0.90
    # Now another call would push us past 95% × 1.00 = 0.95
    with pytest.raises(budget.SessionBudgetExceeded):
        budget.assert_within_budget(case_id="c3", projected_cost=0.10)


def test_per_case_budget_breach():
    os.environ["DR_HOLMES_MAX_BUDGET_USD"] = "10.00"
    os.environ["DR_HOLMES_MAX_COST_PER_CASE_USD"] = "0.20"
    budget.reset_for_tests()
    # Charge case_id="c1" up close to its limit
    budget.record_call(case_id="c1", agent_name="A",
                       provider="openai", model="gpt-4o-mini",
                       input_tokens=1_000_000, output_tokens=0)  # ~0.15 USD
    # Now 0.10 more on the same case would breach 0.95 × 0.20 = 0.19
    with pytest.raises(budget.CaseBudgetExceeded):
        budget.assert_within_budget(case_id="c1", projected_cost=0.10)
    # But a different case is fine
    budget.assert_within_budget(case_id="c2", projected_cost=0.05)


def test_record_call_updates_state():
    budget.reset_for_tests()
    cost = budget.record_call(
        case_id="c1", agent_name="Hauser",
        provider="openai", model="gpt-4o",
        input_tokens=1000, output_tokens=500,
    )
    assert cost > 0
    assert budget.session_total_usd() == cost
    assert budget.case_total_usd("c1") == cost


def test_max_tokens_per_call_default():
    os.environ.pop("DR_HOLMES_MAX_TOKENS_PER_CALL", None)
    assert budget.max_tokens_per_call() == 500


def test_max_tokens_per_call_override():
    os.environ["DR_HOLMES_MAX_TOKENS_PER_CALL"] = "200"
    assert budget.max_tokens_per_call() == 200


def test_session_halts_after_breach():
    os.environ["DR_HOLMES_MAX_BUDGET_USD"] = "0.05"
    budget.reset_for_tests()
    with pytest.raises(budget.SessionBudgetExceeded):
        budget.assert_within_budget(case_id="c", projected_cost=10.0)
    # Now even a tiny call should be rejected
    with pytest.raises(budget.SessionBudgetExceeded):
        budget.assert_within_budget(case_id="c", projected_cost=0.001)


def test_snapshot_shape():
    budget.reset_for_tests()
    snap = budget.snapshot()
    assert "live_mode_enabled" in snap
    assert "session_budget_usd" in snap
    assert "session_total_usd" in snap
    assert "max_tokens_per_call" in snap
    assert snap["n_calls"] == 0


def test_llm_call_guard_rejects_when_live_disabled():
    os.environ.pop("DR_HOLMES_ALLOW_LIVE", None)
    with pytest.raises(budget.LiveModeDisabled):
        with budget.llm_call_guard(
            case_id="c", agent_name="A", provider="openai",
            model="gpt-4o", expected_input_tokens=100,
        ):
            pass  # should never get here


def test_llm_call_guard_records_actual_usage():
    os.environ["DR_HOLMES_ALLOW_LIVE"] = "true"
    os.environ["DR_HOLMES_MAX_BUDGET_USD"] = "100"
    budget.reset_for_tests()
    with budget.llm_call_guard(
        case_id="c1", agent_name="A", provider="openai",
        model="gpt-4o-mini", expected_input_tokens=100,
    ) as guard:
        guard.set_actual(50, 25)
    assert budget.session_total_usd() > 0


def test_per_case_isolation():
    """Per-case tracking is keyed by case_id — different cases independent."""
    os.environ["DR_HOLMES_MAX_BUDGET_USD"] = "10"
    os.environ["DR_HOLMES_MAX_COST_PER_CASE_USD"] = "0.20"
    budget.reset_for_tests()
    budget.record_call(case_id="case_A", agent_name="X",
                       provider="openai", model="gpt-4o-mini",
                       input_tokens=500_000, output_tokens=0)  # ~0.075
    # case_A has spent ~0.075; case_B is fresh
    assert budget.case_total_usd("case_A") > 0.05
    assert budget.case_total_usd("case_B") == 0.0
