"""Eval orchestration — loops over cases × conditions, persists artifacts."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from dr_holmes.eval.baselines import (
    BaselineRunner, BaselineResponse,
    GPT4oSolo, SonnetSolo, GPT4oRAG, GPT4oMILayer, FullTeamBaseline,
)
from dr_holmes.eval.cache import LLMResponseCache
from dr_holmes.eval.cost import CostTracker, BudgetBreach
from dr_holmes.eval.metrics import (
    CaseMetrics, EvalRunMetrics, score_case, aggregate_run,
)
from dr_holmes.eval.reports import write_run_artifacts
from dr_holmes.eval.samplers import DDXPlusSampler, DDXPlusCase


class EvalRunConfig(BaseModel):
    run_id: str = ""
    tier: str = "smoke"             # smoke | standard | headline
    n_cases: int = 20
    conditions: list[str] = []      # e.g. ["gpt4o_solo", "full_team"]
    sampling_mode: str = "proportional"
    seed: int = 42
    max_budget_usd: float = 5.0
    timeout_per_case_seconds: int = 300
    cache_db_path: str = "./data/llm_cache.db"
    eval_runs_root: str = "./data/eval_runs"

    # full_team specific
    full_team_mock_fixture: Optional[str] = None

    # MI layer specific
    mi_max_tool_iters: int = 8


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
        ).decode().strip()[:12]
    except Exception:
        return "unknown"


def _prompt_version_hash() -> str:
    """Hash of all agent system prompts + tool schemas — for cache invalidation."""
    parts = []
    try:
        from dr_holmes.agents.hauser import HauserAgent
        parts.append(HauserAgent.__init__.__doc__ or "")
        # Read system prompts from string definitions
        import dr_holmes.agents.hauser as h
        import dr_holmes.agents.forman as f
        import dr_holmes.agents.carmen as c
        import dr_holmes.agents.chen as ch
        import dr_holmes.agents.wills as w
        import dr_holmes.agents.caddick as cd
        for mod in (h, f, c, ch, w, cd):
            for attr in ("SYSTEM_PROMPT", "SYNTHESIS_PROMPT"):
                if hasattr(mod, attr):
                    parts.append(getattr(mod, attr))
    except Exception:
        pass
    blob = "|".join(parts).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _build_runner(
    condition: str,
    cache: LLMResponseCache,
    tracker: CostTracker,
    config: EvalRunConfig,
    prompt_version: str,
) -> BaselineRunner:
    if condition == "gpt4o_solo":
        return GPT4oSolo(cache, tracker, prompt_version=prompt_version)
    if condition == "sonnet_solo":
        return SonnetSolo(cache, tracker, prompt_version=prompt_version)
    if condition == "gpt4o_rag":
        # Lazy-load chroma collection
        from dr_holmes.rag.retriever import get_retriever
        chroma = get_retriever(os.getenv("CHROMA_PATH", "./data/chroma"))
        return GPT4oRAG(cache, tracker, chroma_collection=chroma, prompt_version=prompt_version)
    if condition == "gpt4o_mi_layer":
        from dr_holmes.intelligence.medical import MedicalIntelligence
        from dr_holmes.intelligence.dispatcher import ToolDispatcher
        from dr_holmes.db.schema import get_engine, get_session
        engine = get_engine()
        session = get_session(engine)
        mi = MedicalIntelligence(bayes_session=session)
        dispatcher = ToolDispatcher(mi)
        return GPT4oMILayer(
            cache, tracker, dispatcher=dispatcher,
            prompt_version=prompt_version, max_tool_iters=config.mi_max_tool_iters,
        )
    if condition == "full_team":
        return FullTeamBaseline(
            cache, tracker,
            mock_fixture=config.full_team_mock_fixture,
            prompt_version=prompt_version,
        )
    raise ValueError(f"Unknown condition: {condition}")


def run_eval(config: EvalRunConfig, cases: list[DDXPlusCase]) -> dict[str, EvalRunMetrics]:
    """Run eval across all conditions × all cases. Returns {condition: EvalRunMetrics}."""
    if not config.run_id:
        config.run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    out_dir = Path(config.eval_runs_root) / config.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(config.model_dump_json(indent=2))

    cache = LLMResponseCache(db_path=config.cache_db_path)
    tracker = CostTracker(budget_usd=config.max_budget_usd, halt_on_breach=True)
    git_sha = _git_sha()
    prompt_version = _prompt_version_hash()

    results: dict[str, EvalRunMetrics] = {}
    all_metrics_by_condition: dict[str, list[CaseMetrics]] = {}

    for condition in config.conditions:
        print(f"\n══ Condition: {condition} ══")
        try:
            runner = _build_runner(condition, cache, tracker, config, prompt_version)
        except Exception as e:
            print(f"  failed to build runner: {e}")
            continue

        case_metrics: list[CaseMetrics] = []
        for i, case in enumerate(cases, 1):
            try:
                t0 = time.time()
                resp = runner.run_case(case)
                if time.time() - t0 > config.timeout_per_case_seconds:
                    resp.error = "timeout"
                m = score_case(resp, case)
                case_metrics.append(m)
                if i % 10 == 0 or i == len(cases):
                    correct = sum(1 for c in case_metrics if c.top_1_correct)
                    print(f"  [{i:>4}/{len(cases)}]  top1={correct/len(case_metrics):.2%}  "
                          f"cost=${tracker.total:.3f}  hits={cache.stats()['hits']}")
            except BudgetBreach as e:
                print(f"  ⚠ budget breach: {e}")
                break
            except Exception as e:
                print(f"  case {case.case_id} errored: {e}")
                # Synthesize a failed metric so it counts toward the denominator
                case_metrics.append(CaseMetrics(
                    case_id=case.case_id, condition=condition,
                    ground_truth_dx=case.pathology,
                    ground_truth_ddx=case.differential_diagnosis,
                    final_dx="", final_top_5=[],
                    final_probability_for_truth=0.0,
                    top_1_correct=False, top_3_correct=False, top_5_correct=False,
                    reciprocal_rank=0.0, confidence_at_top_1=0.0, brier_loss=1.0,
                    failure_category="schema_failure",
                    error=f"{type(e).__name__}: {e}",
                ))

        cache_stats = cache.stats()
        run_metrics = aggregate_run(
            case_metrics,
            run_id=f"{config.run_id}/{condition}",
            config=config.model_dump(),
            git_sha=git_sha,
            prompt_version=prompt_version,
            cache_hits=cache_stats["hits"],
            cache_total=cache_stats["hits"] + cache_stats["misses"],
        )
        results[condition] = run_metrics
        all_metrics_by_condition[condition] = case_metrics

        cond_dir = out_dir / condition
        cond_dir.mkdir(exist_ok=True)
        write_run_artifacts(run_metrics, case_metrics, cond_dir)

    # Comparison artifacts at the run root
    if len(results) > 1:
        # Combine all case metrics for run-level summary
        flat = [m for ms in all_metrics_by_condition.values() for m in ms]
        combined = aggregate_run(
            flat, run_id=config.run_id, config=config.model_dump(),
            git_sha=git_sha, prompt_version=prompt_version,
            cache_hits=cache.stats()["hits"],
            cache_total=cache.stats()["hits"] + cache.stats()["misses"],
        )
        write_run_artifacts(combined, flat, out_dir, comparison=results)

    print(f"\n✓ Run complete: {out_dir}")
    print(f"  Total cost: ${tracker.total:.3f}")
    print(f"  Cache hit rate: {cache.stats()['hit_rate']:.1%}")
    return results
