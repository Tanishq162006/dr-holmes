"""Metric computation — case-level + run-level + bootstrap CIs."""
from __future__ import annotations
import re
import random
from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from pydantic import BaseModel

from dr_holmes.eval.baselines import BaselineResponse
from dr_holmes.eval.samplers import DDXPlusCase
from dr_holmes.schemas.responses import Differential


# ── Schemas ────────────────────────────────────────────────────────

class AgentTrace(BaseModel):
    agent_name: str
    n_turns: int = 0
    n_tool_calls: int = 0
    tools_used: dict[str, int] = {}
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    final_top_dx: str = ""
    final_top_prob: float = 0.0


class CaseMetrics(BaseModel):
    case_id: str
    condition: str
    ground_truth_dx: str
    ground_truth_ddx: list[str]
    final_dx: str
    final_top_5: list[str]
    final_probability_for_truth: float
    top_1_correct: bool
    top_3_correct: bool
    top_5_correct: bool
    reciprocal_rank: float
    confidence_at_top_1: float
    brier_loss: float
    converged: bool = False
    convergence_reason: str = ""
    rounds_to_converge: int | None = None
    hauser_dissent_present: bool = False
    hauser_dissent_was_correct: bool | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    wall_clock_seconds: float = 0.0
    n_llm_calls: int = 0
    n_tool_calls: int = 0
    cache_hits: int = 0
    failure_category: str = "correct"
    error: str | None = None


class ReliabilityBin(BaseModel):
    confidence_low: float
    confidence_high: float
    n_predictions: int
    actual_accuracy: float
    mean_predicted_prob: float


class DiseaseStats(BaseModel):
    disease: str
    n_cases: int
    top_1_accuracy: float
    top_3_accuracy: float
    mean_confidence_when_correct: float
    mean_confidence_when_wrong: float


class EvalRunMetrics(BaseModel):
    run_id: str
    timestamp: str
    config: dict
    git_sha: str = ""
    prompt_version: str = ""
    metric_version: str = "v1"
    n_cases_attempted: int
    n_cases_completed: int
    n_cases_timeout: int = 0
    n_cases_errored: int = 0

    top_1_accuracy: float
    top_3_accuracy: float
    top_5_accuracy: float
    mean_reciprocal_rank: float
    top_1_ci_low: float = 0.0
    top_1_ci_high: float = 0.0
    top_3_ci_low: float = 0.0
    top_3_ci_high: float = 0.0

    expected_calibration_error: float
    brier_score: float
    reliability_bins: list[ReliabilityBin] = []

    convergence_rate: float = 0.0
    mean_rounds: float = 0.0
    median_rounds: float = 0.0
    p95_rounds: int = 0

    mean_cost_per_case: float = 0.0
    median_cost_per_case: float = 0.0
    p95_cost_per_case: float = 0.0
    total_cost_usd: float = 0.0
    cache_hit_rate: float = 0.0
    mean_wall_clock: float = 0.0
    p95_wall_clock: float = 0.0

    per_disease_accuracy: dict[str, DiseaseStats] = {}
    failure_categories: dict[str, int] = {}
    cases_with_dissent: int = 0
    hauser_dissent_correct_rate: float | None = None


# ── Disease name normalization (matches Phase 3 token-set logic) ───

def _normalize_dx(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.split(r"[,:;]", s)[0]
    s = s.replace("'s", "").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _matches(pred: str, truth: str) -> bool:
    """Token-set containment match (matches Phase 3 _dx_tokens_match)."""
    p = set(_normalize_dx(pred).split())
    t = set(_normalize_dx(truth).split())
    if not p or not t:
        return False
    if p == t:
        return True
    shared = p & t
    if len(shared) < 2 and len(p) > 1 and len(t) > 1:
        return False
    return p.issubset(t) or t.issubset(p)


def _rank_in(pred_list: list[str], truth: str) -> int:
    """Returns 1-indexed rank of truth in pred_list, or 0 if absent."""
    for i, p in enumerate(pred_list, 1):
        if _matches(p, truth):
            return i
    return 0


# ── Case-level metric ──────────────────────────────────────────────

def score_case(response: BaselineResponse, case: DDXPlusCase) -> CaseMetrics:
    truth = case.pathology
    pred_names = [d.diagnosis for d in response.top_5]
    rank = _rank_in(pred_names, truth)

    top_1 = rank == 1
    top_3 = 1 <= rank <= 3
    top_5 = 1 <= rank <= 5
    rr = 1.0 / rank if rank else 0.0

    # Probability the model assigned to ground truth (0 if absent from top 5)
    p_truth = 0.0
    for d in response.top_5:
        if _matches(d.diagnosis, truth):
            p_truth = d.probability
            break

    # Brier loss: (P_assigned_to_top1 - I[top1_correct])²
    conf_top1 = response.top_5[0].probability if response.top_5 else 0.0
    brier = (conf_top1 - (1.0 if top_1 else 0.0)) ** 2

    # Failure category
    if response.error:
        failure = "schema_failure"
    elif top_1:
        failure = "correct"
    elif rank == 0:
        failure = "missed_obvious" if case.differential_size <= 3 else "hallucinated"
    elif rank > 3:
        failure = "hallucinated"
    else:
        failure = "premature_convergence"

    return CaseMetrics(
        case_id=case.case_id,
        condition=response.condition,
        ground_truth_dx=truth,
        ground_truth_ddx=case.differential_diagnosis,
        final_dx=pred_names[0] if pred_names else "",
        final_top_5=pred_names,
        final_probability_for_truth=p_truth,
        top_1_correct=top_1,
        top_3_correct=top_3,
        top_5_correct=top_5,
        reciprocal_rank=rr,
        confidence_at_top_1=conf_top1,
        brier_loss=brier,
        total_input_tokens=response.input_tokens,
        total_output_tokens=response.output_tokens,
        total_cost_usd=response.cost_usd,
        wall_clock_seconds=response.wall_clock_seconds,
        n_llm_calls=response.n_llm_calls,
        n_tool_calls=response.n_tool_calls,
        failure_category=failure,
        error=response.error,
    )


# ── Calibration ────────────────────────────────────────────────────

def reliability_bins(metrics: list[CaseMetrics], n_bins: int = 10) -> list[ReliabilityBin]:
    bins: list[list[CaseMetrics]] = [[] for _ in range(n_bins)]
    for m in metrics:
        idx = min(int(m.confidence_at_top_1 * n_bins), n_bins - 1)
        bins[idx].append(m)
    out = []
    for i, bucket in enumerate(bins):
        low, high = i / n_bins, (i + 1) / n_bins
        if not bucket:
            out.append(ReliabilityBin(
                confidence_low=low, confidence_high=high,
                n_predictions=0, actual_accuracy=0.0, mean_predicted_prob=0.0,
            ))
            continue
        acc = sum(1 for m in bucket if m.top_1_correct) / len(bucket)
        mean_p = sum(m.confidence_at_top_1 for m in bucket) / len(bucket)
        out.append(ReliabilityBin(
            confidence_low=low, confidence_high=high,
            n_predictions=len(bucket), actual_accuracy=acc, mean_predicted_prob=mean_p,
        ))
    return out


def expected_calibration_error(bins: list[ReliabilityBin]) -> float:
    total = sum(b.n_predictions for b in bins)
    if total == 0:
        return 0.0
    return sum(
        b.n_predictions / total * abs(b.actual_accuracy - b.mean_predicted_prob)
        for b in bins
    )


# ── Bootstrap CIs ──────────────────────────────────────────────────

def _bootstrap_ci(
    samples: list[float],
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    if not samples:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    n = len(samples)
    for _ in range(n_resamples):
        resample = [samples[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    lo = means[int((1 - ci) / 2 * n_resamples)]
    hi = means[int((1 + ci) / 2 * n_resamples)]
    return (lo, hi)


# ── Run-level aggregation ──────────────────────────────────────────

def aggregate_run(
    metrics: list[CaseMetrics],
    *,
    run_id: str,
    config: dict,
    git_sha: str = "",
    prompt_version: str = "",
    metric_version: str = "v1",
    cache_hits: int = 0,
    cache_total: int = 0,
) -> EvalRunMetrics:
    n = len(metrics)
    if n == 0:
        return EvalRunMetrics(
            run_id=run_id, timestamp=datetime.utcnow().isoformat(), config=config,
            git_sha=git_sha, prompt_version=prompt_version, metric_version=metric_version,
            n_cases_attempted=0, n_cases_completed=0,
            top_1_accuracy=0.0, top_3_accuracy=0.0, top_5_accuracy=0.0,
            mean_reciprocal_rank=0.0,
            expected_calibration_error=0.0, brier_score=0.0,
        )

    completed = [m for m in metrics if m.error is None]
    n_completed = len(completed)

    top_1 = [1.0 if m.top_1_correct else 0.0 for m in completed]
    top_3 = [1.0 if m.top_3_correct else 0.0 for m in completed]
    top_5 = [1.0 if m.top_5_correct else 0.0 for m in completed]

    bins = reliability_bins(completed)
    ece = expected_calibration_error(bins)
    brier = sum(m.brier_loss for m in completed) / n_completed if n_completed else 0.0
    mrr = sum(m.reciprocal_rank for m in completed) / n_completed if n_completed else 0.0

    t1_lo, t1_hi = _bootstrap_ci(top_1)
    t3_lo, t3_hi = _bootstrap_ci(top_3)

    # Cost / latency
    costs = [m.total_cost_usd for m in completed]
    walls = [m.wall_clock_seconds for m in completed]
    rounds = [m.rounds_to_converge for m in completed if m.rounds_to_converge]

    def _pct(xs: list[float], p: float) -> float:
        if not xs: return 0.0
        s = sorted(xs)
        return s[min(int(p * len(s)), len(s) - 1)]

    # Per-disease
    per_disease: dict[str, DiseaseStats] = {}
    by_dx: dict[str, list[CaseMetrics]] = defaultdict(list)
    for m in completed:
        by_dx[m.ground_truth_dx].append(m)
    for dx, ms in by_dx.items():
        n_dx = len(ms)
        n_correct = sum(1 for m in ms if m.top_1_correct)
        n_t3 = sum(1 for m in ms if m.top_3_correct)
        confs_correct = [m.confidence_at_top_1 for m in ms if m.top_1_correct]
        confs_wrong = [m.confidence_at_top_1 for m in ms if not m.top_1_correct]
        per_disease[dx] = DiseaseStats(
            disease=dx, n_cases=n_dx,
            top_1_accuracy=n_correct / n_dx,
            top_3_accuracy=n_t3 / n_dx,
            mean_confidence_when_correct=sum(confs_correct)/len(confs_correct) if confs_correct else 0.0,
            mean_confidence_when_wrong=sum(confs_wrong)/len(confs_wrong) if confs_wrong else 0.0,
        )

    # Failure categories
    failures: dict[str, int] = defaultdict(int)
    for m in metrics:
        failures[m.failure_category] += 1

    # Hauser dissent stats
    dissent_present = sum(1 for m in completed if m.hauser_dissent_present)
    dissent_correct = [m for m in completed if m.hauser_dissent_present and m.hauser_dissent_was_correct]
    hauser_correct_rate = (len(dissent_correct) / dissent_present) if dissent_present else None

    cache_hit_rate = (cache_hits / cache_total) if cache_total else 0.0

    return EvalRunMetrics(
        run_id=run_id,
        timestamp=datetime.utcnow().isoformat(),
        config=config,
        git_sha=git_sha,
        prompt_version=prompt_version,
        metric_version=metric_version,
        n_cases_attempted=n,
        n_cases_completed=n_completed,
        n_cases_errored=n - n_completed,
        top_1_accuracy=sum(top_1) / len(top_1) if top_1 else 0.0,
        top_3_accuracy=sum(top_3) / len(top_3) if top_3 else 0.0,
        top_5_accuracy=sum(top_5) / len(top_5) if top_5 else 0.0,
        mean_reciprocal_rank=mrr,
        top_1_ci_low=t1_lo, top_1_ci_high=t1_hi,
        top_3_ci_low=t3_lo, top_3_ci_high=t3_hi,
        expected_calibration_error=ece,
        brier_score=brier,
        reliability_bins=bins,
        convergence_rate=(sum(1 for m in completed if m.converged) / n_completed) if n_completed else 0.0,
        mean_rounds=sum(rounds) / len(rounds) if rounds else 0.0,
        median_rounds=_pct([float(r) for r in rounds], 0.5),
        p95_rounds=int(_pct([float(r) for r in rounds], 0.95)),
        mean_cost_per_case=sum(costs) / len(costs) if costs else 0.0,
        median_cost_per_case=_pct(costs, 0.5),
        p95_cost_per_case=_pct(costs, 0.95),
        total_cost_usd=sum(costs),
        cache_hit_rate=cache_hit_rate,
        mean_wall_clock=sum(walls) / len(walls) if walls else 0.0,
        p95_wall_clock=_pct(walls, 0.95),
        per_disease_accuracy=per_disease,
        failure_categories=dict(failures),
        cases_with_dissent=dissent_present,
        hauser_dissent_correct_rate=hauser_correct_rate,
    )
