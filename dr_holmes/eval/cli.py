"""Eval CLI entry point.

Usage:
    python -m dr_holmes.eval --tier smoke --conditions full_team \
        --full-team-mock-fixture fixtures/case_01_easy_mi.json

    python -m dr_holmes.eval --tier standard --all-conditions --budget 30

    python -m dr_holmes.eval --report --run-id run_20260429_120000
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


_TIER_PRESETS = {
    "smoke":    {"n_cases": 20,   "max_budget_usd":  5.0},
    "standard": {"n_cases": 200,  "max_budget_usd": 40.0},
    "headline": {"n_cases": 1000, "max_budget_usd": 250.0},
}

_ALL_CONDITIONS = ["gpt4o_solo", "sonnet_solo", "gpt4o_rag", "gpt4o_mi_layer", "full_team"]


def main():
    p = argparse.ArgumentParser(prog="dr_holmes.eval")
    p.add_argument("--tier", choices=list(_TIER_PRESETS), default="smoke")
    p.add_argument("--conditions", default="", help="Comma-separated conditions")
    p.add_argument("--all-conditions", action="store_true",
                   help="Run all 5 baselines + full_team")
    p.add_argument("--budget", type=float, default=None,
                   help="Override tier default budget (USD)")
    p.add_argument("--n", type=int, default=None,
                   help="Override tier default case count")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--sampling", choices=["proportional", "uniform_per_disease"],
                   default="proportional")
    p.add_argument("--run-id", default="")
    p.add_argument("--full-team-mock-fixture", default=None,
                   help="Path to a mock fixture (for full_team without LLM keys)")
    p.add_argument("--mi-max-iters", type=int, default=8)

    p.add_argument("--report", action="store_true",
                   help="Re-render report from existing run_id")
    p.add_argument("--re-score", action="store_true",
                   help="Re-score from cached BaselineResponses (zero LLM cost)")

    args = p.parse_args()

    # Re-render mode
    if args.report:
        if not args.run_id:
            print("--report requires --run-id"); sys.exit(1)
        # For now, re-rendering reads metrics.json and emits the same report
        from dr_holmes.eval.metrics import EvalRunMetrics
        from dr_holmes.eval.reports import write_summary_md
        run_dir = Path("./data/eval_runs") / args.run_id
        if not run_dir.exists():
            print(f"Run not found: {run_dir}"); sys.exit(1)
        metrics = EvalRunMetrics.model_validate_json((run_dir / "metrics.json").read_text())
        write_summary_md(metrics, run_dir, chart_paths={})
        print(f"Wrote {run_dir / 'summary.md'}")
        return

    # Decide conditions
    if args.all_conditions:
        conditions = list(_ALL_CONDITIONS)
    elif args.conditions:
        conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    else:
        conditions = ["gpt4o_solo"]

    # Apply tier preset
    preset = _TIER_PRESETS[args.tier]
    n_cases = args.n or preset["n_cases"]
    budget = args.budget or preset["max_budget_usd"]

    print(f"Eval run: tier={args.tier} n={n_cases} budget=${budget:.2f}")
    print(f"Conditions: {conditions}")

    # Sample DDXPlus
    from dr_holmes.eval.samplers import DDXPlusSampler
    sampler = DDXPlusSampler(split="test")
    print(f"Loading DDXPlus test split...")
    sampler.load(max_cases=max(50_000, n_cases * 10))   # upper bound for sampling pool
    print(f"  loaded {len(sampler.cases):,} cases")
    cases = sampler.stratified_sample(n=n_cases, seed=args.seed, mode=args.sampling)
    print(f"  sampled {len(cases)} cases")

    # Build config
    from dr_holmes.eval.runner import EvalRunConfig, run_eval
    config = EvalRunConfig(
        run_id=args.run_id,
        tier=args.tier,
        n_cases=n_cases,
        conditions=conditions,
        sampling_mode=args.sampling,
        seed=args.seed,
        max_budget_usd=budget,
        full_team_mock_fixture=args.full_team_mock_fixture,
        mi_max_tool_iters=args.mi_max_iters,
    )

    results = run_eval(config, cases)

    # Print headline
    print("\n══ Headline ══")
    print(f"{'Condition':<22} {'Top-1':>8} {'Top-3':>8} {'Top-5':>8} {'MRR':>6} {'ECE':>6}")
    for cond, m in results.items():
        print(f"{cond:<22} {m.top_1_accuracy:>8.3f} {m.top_3_accuracy:>8.3f} "
              f"{m.top_5_accuracy:>8.3f} {m.mean_reciprocal_rank:>6.3f} "
              f"{m.expected_calibration_error:>6.3f}")


if __name__ == "__main__":
    main()
