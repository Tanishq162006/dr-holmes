"""Phase 7 eval tests — deterministic, no LLM calls.

Tests cache, cost tracker, sampler, metrics, calibration with synthetic data.
Plus an end-to-end pipeline test using full_team mock-fixture mode.
"""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from dr_holmes.eval.cache import LLMResponseCache, derive_cache_key
from dr_holmes.eval.cost import (
    CostTracker, BudgetBreach, estimate_cost, price_for, PRICES,
)
from dr_holmes.eval.samplers import DDXPlusCase, _age_bracket
from dr_holmes.eval.baselines import BaselineResponse, _parse_top_5
from dr_holmes.eval.metrics import (
    score_case, _normalize_dx, _matches, _rank_in,
    reliability_bins, expected_calibration_error,
    aggregate_run, _bootstrap_ci,
)
from dr_holmes.schemas.responses import Differential


# ── Cache ──────────────────────────────────────────────────────────

def test_cache_key_deterministic(tmp_path):
    k1 = derive_cache_key(
        provider="openai", model="gpt-4o", prompt_version="v1",
        messages=[{"role": "user", "content": "hi"}],
    )
    k2 = derive_cache_key(
        provider="openai", model="gpt-4o", prompt_version="v1",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_cache_key_changes_on_prompt_version_bump():
    k1 = derive_cache_key(provider="openai", model="gpt-4o", prompt_version="v1",
                          messages=[{"role": "user", "content": "hi"}])
    k2 = derive_cache_key(provider="openai", model="gpt-4o", prompt_version="v2",
                          messages=[{"role": "user", "content": "hi"}])
    assert k1 != k2


def test_cache_get_miss_then_hit(tmp_path):
    db = tmp_path / "test_cache.db"
    cache = LLMResponseCache(db_path=str(db))

    calls = {"n": 0}
    def fake_call():
        calls["n"] += 1
        return ({"text": "hello"}, 100, 50, 0.01)

    r1 = cache.get_or_call(
        provider="openai", model="gpt-4o", prompt_version="v1",
        messages=[{"role": "user", "content": "hi"}],
        call_fn=fake_call,
    )
    assert r1.cache_hit is False
    assert calls["n"] == 1
    assert r1.response["text"] == "hello"

    r2 = cache.get_or_call(
        provider="openai", model="gpt-4o", prompt_version="v1",
        messages=[{"role": "user", "content": "hi"}],
        call_fn=fake_call,
    )
    assert r2.cache_hit is True
    assert calls["n"] == 1   # not called again
    assert cache.stats()["hits"] == 1
    assert cache.stats()["misses"] == 1


# ── Cost ───────────────────────────────────────────────────────────

def test_estimate_cost_gpt4o():
    cost = estimate_cost("openai", "gpt-4o", 1_000_000, 0)
    assert abs(cost - 2.50) < 0.01

def test_estimate_cost_unknown_model_falls_back():
    cost = estimate_cost("unknown", "unknown-model", 1_000_000, 0)
    assert cost > 0   # falls back to gpt-4o pricing

def test_cost_tracker_aggregates():
    t = CostTracker(budget_usd=100.0)
    t.add(provider="openai", model="gpt-4o", in_tokens=1000, out_tokens=500,
          case_id="c1", agent_name="Hauser", condition="full_team")
    t.add(provider="openai", model="gpt-4o", in_tokens=2000, out_tokens=1000,
          case_id="c1", agent_name="Forman", condition="full_team")
    r = t.report()
    assert r.n_calls == 2
    assert r.by_case["c1"] > 0
    assert r.by_agent["Hauser"] > 0
    assert r.by_agent["Forman"] > r.by_agent["Hauser"]   # 2x tokens

def test_cost_tracker_budget_breach():
    t = CostTracker(budget_usd=0.01)   # tiny budget
    with pytest.raises(BudgetBreach):
        t.add(provider="openai", model="gpt-4o", in_tokens=1_000_000, out_tokens=0)

def test_cost_tracker_cache_hit_doesnt_charge():
    t = CostTracker(budget_usd=10.0)
    t.add(provider="openai", model="gpt-4o", in_tokens=1_000_000, out_tokens=0,
          cache_hit=True)
    assert t.total == 0.0
    assert t.cache_hits == 1


# ── Sampler ────────────────────────────────────────────────────────

def test_age_bracket():
    assert _age_bracket(10)  == "<18"
    assert _age_bracket(25)  == "18-34"
    assert _age_bracket(45)  == "35-54"
    assert _age_bracket(65)  == "55-74"
    assert _age_bracket(80)  == "75+"


# ── Metrics: normalization + ranking ───────────────────────────────

def test_normalize_drops_parentheticals_and_punctuation():
    assert _normalize_dx("Anterior STEMI (proximal LAD)") == "anterior stemi"
    assert _normalize_dx("Whipple's Disease") == "whipple disease"

def test_matches_token_set_overlap():
    assert _matches("Anterior STEMI", "STEMI (anterior wall)")
    assert _matches("SLE with lupus nephritis", "SLE")
    assert not _matches("URTI", "STEMI")

def test_rank_in_finds_truth():
    pred = ["URTI", "Influenza", "Bronchitis", "Pneumonia"]
    assert _rank_in(pred, "URTI") == 1
    assert _rank_in(pred, "Bronchitis") == 3
    assert _rank_in(pred, "Whipple disease") == 0


# ── Score case ─────────────────────────────────────────────────────

def _mk_case(pathology: str = "URTI", differential: list[str] | None = None) -> DDXPlusCase:
    return DDXPlusCase(
        case_id="t1", age=30, sex="F",
        pathology=pathology,
        differential_diagnosis=differential or [],
        evidences=[], evidence_labels=["fever", "cough"],
        initial_evidence="", n_evidences=2, differential_size=0,
    )

def _mk_response(condition: str, top: list[tuple[str, float]],
                 case_id: str = "t1") -> BaselineResponse:
    return BaselineResponse(
        condition=condition, case_id=case_id,
        top_5=[Differential(diagnosis=n, probability=p, rationale="") for n, p in top],
        confidence=top[0][1] if top else 0.0,
    )

def test_score_case_top1_correct():
    case = _mk_case("URTI")
    resp = _mk_response("gpt4o_solo", [("URTI", 0.6), ("Flu", 0.2), ("Bronchitis", 0.1)])
    m = score_case(resp, case)
    assert m.top_1_correct
    assert m.top_3_correct
    assert m.top_5_correct
    assert m.reciprocal_rank == 1.0
    assert m.failure_category == "correct"

def test_score_case_top3_only():
    case = _mk_case("Bronchitis")
    resp = _mk_response("gpt4o_solo", [("URTI", 0.5), ("Flu", 0.3), ("Bronchitis", 0.15)])
    m = score_case(resp, case)
    assert not m.top_1_correct
    assert m.top_3_correct
    assert m.reciprocal_rank == pytest.approx(1/3)

def test_score_case_missed():
    case = _mk_case("Whipple disease")
    resp = _mk_response("gpt4o_solo", [("URTI", 0.7), ("Flu", 0.2)])
    m = score_case(resp, case)
    assert not m.top_5_correct
    assert m.reciprocal_rank == 0.0
    assert m.final_probability_for_truth == 0.0
    assert m.failure_category in ("missed_obvious", "hallucinated")


# ── Calibration ────────────────────────────────────────────────────

def test_reliability_bins_perfect_calibration():
    """If predicted=actual, ECE → 0."""
    metrics = []
    for confidence in [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]:
        # half should be correct at this bin, matched to the prob
        n = 100
        n_correct = int(round(confidence * n))
        for i in range(n):
            case = _mk_case("URTI")
            top = [("URTI", confidence)] if i < n_correct else [("Other", confidence)]
            resp = _mk_response("test", top)
            metrics.append(score_case(resp, case))
    bins = reliability_bins(metrics)
    ece = expected_calibration_error(bins)
    assert ece < 0.05, f"Expected near-zero ECE, got {ece}"

def test_reliability_bins_overconfident():
    """Always says 0.95 confidence, only right 50% of the time."""
    metrics = []
    for i in range(100):
        case = _mk_case("URTI")
        top = [("URTI", 0.95)] if i < 50 else [("Other", 0.95)]
        resp = _mk_response("test", top)
        metrics.append(score_case(resp, case))
    bins = reliability_bins(metrics)
    ece = expected_calibration_error(bins)
    assert ece > 0.4, f"Expected large ECE for overconfidence, got {ece}"


# ── Bootstrap CI ───────────────────────────────────────────────────

def test_bootstrap_ci_envelope():
    samples = [1.0] * 80 + [0.0] * 20    # 80% accuracy
    lo, hi = _bootstrap_ci(samples, n_resamples=500, seed=1)
    assert 0.65 < lo < 0.80
    assert 0.80 < hi < 0.92


# ── Aggregate run ──────────────────────────────────────────────────

def test_aggregate_run_basic():
    metrics = []
    for i in range(20):
        case = _mk_case("URTI")
        # 14/20 correct
        top = [("URTI", 0.7)] if i < 14 else [("Other", 0.4)]
        resp = _mk_response("gpt4o_solo", top)
        metrics.append(score_case(resp, case))
    run = aggregate_run(metrics, run_id="t", config={}, cache_hits=10, cache_total=20)
    assert run.top_1_accuracy == 0.7
    assert run.n_cases_completed == 20
    assert run.cache_hit_rate == 0.5
    assert run.top_1_ci_low < 0.7 < run.top_1_ci_high


# ── Top-5 parser ───────────────────────────────────────────────────

def test_parse_top5_clean_json():
    raw = '{"differentials": [{"diagnosis": "URTI", "probability": 0.6, "rationale": "x"}]}'
    out = _parse_top_5(raw)
    assert len(out) == 1
    assert out[0].diagnosis == "URTI"

def test_parse_top5_handles_prose_around_json():
    raw = 'Sure! Here is my answer: {"differentials": [{"diagnosis": "URTI", "probability": 0.6}]} hope this helps'
    out = _parse_top_5(raw)
    assert len(out) == 1

def test_parse_top5_returns_empty_on_garbage():
    assert _parse_top_5("not json at all") == []
    assert _parse_top_5("") == []


# ── End-to-end pipeline (uses full_team mock fixture, no LLM calls) ────

def test_e2e_eval_pipeline_with_full_team_mock(tmp_path):
    """Full eval pipeline: sample → run → score → aggregate → write artifacts.
    Uses full_team mock fixture so no API keys are needed."""
    from dr_holmes.eval.runner import EvalRunConfig, run_eval

    fixture = Path(__file__).parent.parent / "fixtures" / "case_01_easy_mi.json"

    # Build a synthetic DDXPlusCase that matches fixture topic (STEMI)
    case = DDXPlusCase(
        case_id="ddx_test_0000001", age=58, sex="M",
        pathology="STEMI",   # ground truth
        differential_diagnosis=["STEMI", "Aortic dissection"],
        evidences=[], evidence_labels=["chest pain", "diaphoresis"],
        initial_evidence="", n_evidences=2, differential_size=2,
    )

    cfg = EvalRunConfig(
        run_id="test_e2e",
        tier="smoke",
        n_cases=1,
        conditions=["full_team"],
        max_budget_usd=1.0,
        cache_db_path=str(tmp_path / "cache.db"),
        eval_runs_root=str(tmp_path / "runs"),
        full_team_mock_fixture=str(fixture),
    )
    results = run_eval(cfg, [case])

    assert "full_team" in results
    run = results["full_team"]
    assert run.n_cases_completed == 1
    # Mock fixture's top dx is "Anterior STEMI..." which token-set matches "STEMI"
    assert run.top_1_accuracy == 1.0 or run.top_5_accuracy == 1.0

    # Artifacts written
    artifacts = tmp_path / "runs" / "test_e2e" / "full_team"
    assert (artifacts / "summary.md").exists()
    assert (artifacts / "metrics.json").exists()
    assert (artifacts / "per_case.csv").exists()
    assert (artifacts / "charts" / "reliability.png").exists()
    assert (artifacts / "charts" / "cost.png").exists()
