"""Eval report generation — markdown summary + matplotlib charts."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive
import matplotlib.pyplot as plt

from dr_holmes.eval.metrics import (
    CaseMetrics, EvalRunMetrics, ReliabilityBin, DiseaseStats,
)


# ── Charts ─────────────────────────────────────────────────────────

def chart_accuracy_by_condition(
    runs: dict[str, EvalRunMetrics],
    out_path: Path,
):
    conditions = list(runs.keys())
    top_1 = [runs[c].top_1_accuracy for c in conditions]
    top_3 = [runs[c].top_3_accuracy for c in conditions]
    top_5 = [runs[c].top_5_accuracy for c in conditions]

    x = list(range(len(conditions)))
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - width for i in x], top_1, width, label="Top-1", color="#d62728")
    ax.bar(x,                       top_3, width, label="Top-3", color="#ff7f0e")
    ax.bar([i + width for i in x],  top_5, width, label="Top-5", color="#2ca02c")
    ax.set_xticks(x)
    ax.set_xticklabels(conditions, rotation=20)
    ax.set_ylabel("Accuracy")
    ax.set_ylim(0, 1)
    ax.set_title("Accuracy by condition")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def chart_reliability_diagram(
    bins: list[ReliabilityBin],
    ece: float,
    out_path: Path,
    title: str = "Reliability diagram",
):
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "--", color="#888", label="Perfect calibration")
    xs = [(b.confidence_low + b.confidence_high) / 2 for b in bins]
    ys = [b.actual_accuracy for b in bins]
    sizes = [max(20, b.n_predictions * 8) for b in bins]
    ax.scatter(xs, ys, s=sizes, alpha=0.7, color="#1f77b4", label="Observed")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed accuracy")
    ax.set_title(f"{title}  (ECE={ece:.3f})")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def chart_cost_distribution(
    costs: list[float],
    out_path: Path,
    title: str = "Cost per case",
):
    fig, ax = plt.subplots(figsize=(8, 4))
    if costs:
        ax.hist(costs, bins=30, color="#9467bd", alpha=0.8)
    ax.set_xlabel("USD per case")
    ax.set_ylabel("Count")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def chart_per_disease_accuracy(
    per_disease: dict[str, DiseaseStats],
    out_path: Path,
    top_n: int = 15,
):
    if not per_disease:
        return
    items = sorted(per_disease.values(), key=lambda d: -d.n_cases)[:top_n]
    names = [d.disease[:30] for d in items]
    accs = [d.top_1_accuracy for d in items]

    fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(names))))
    ax.barh(names, accs, color="#17becf")
    ax.set_xlim(0, 1)
    ax.set_xlabel("Top-1 accuracy")
    ax.set_title(f"Per-disease accuracy (top {top_n} by sample count)")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ── Markdown summary ───────────────────────────────────────────────

def write_summary_md(
    run: EvalRunMetrics,
    out_dir: Path,
    chart_paths: dict[str, str],
    comparison: dict[str, EvalRunMetrics] | None = None,
) -> Path:
    out = out_dir / "summary.md"
    lines = []
    lines.append(f"# Eval run: `{run.run_id}`\n")
    lines.append(f"> ⚠ NOT FOR CLINICAL USE.  Generated {run.timestamp}\n")
    lines.append(f"- git: `{run.git_sha or 'unknown'}`")
    lines.append(f"- prompt version: `{run.prompt_version or 'unknown'}`")
    lines.append(f"- metric version: `{run.metric_version}`")
    lines.append(f"- cases: {run.n_cases_completed} / {run.n_cases_attempted} completed")
    lines.append(f"- total cost: ${run.total_cost_usd:.2f}")
    lines.append(f"- cache hit rate: {run.cache_hit_rate:.1%}")
    lines.append("")

    lines.append("## Headline accuracy\n")
    lines.append("| Metric | Value | 95% CI |")
    lines.append("|---|---|---|")
    lines.append(f"| Top-1 | **{run.top_1_accuracy:.3f}** | [{run.top_1_ci_low:.3f}, {run.top_1_ci_high:.3f}] |")
    lines.append(f"| Top-3 | **{run.top_3_accuracy:.3f}** | [{run.top_3_ci_low:.3f}, {run.top_3_ci_high:.3f}] |")
    lines.append(f"| Top-5 | **{run.top_5_accuracy:.3f}** | — |")
    lines.append(f"| MRR   | {run.mean_reciprocal_rank:.3f} | — |")
    lines.append(f"| ECE   | {run.expected_calibration_error:.3f} | — |")
    lines.append(f"| Brier | {run.brier_score:.3f} | — |")
    lines.append("")

    if comparison:
        lines.append("## Baseline comparison\n")
        lines.append("| Condition | Top-1 | Top-3 | Top-5 | MRR | ECE | Cost/case |")
        lines.append("|---|---|---|---|---|---|---|")
        for cond, m in comparison.items():
            mark = " 🏆" if cond == run.run_id else ""
            lines.append(
                f"| {cond}{mark} | {m.top_1_accuracy:.3f} | {m.top_3_accuracy:.3f} | "
                f"{m.top_5_accuracy:.3f} | {m.mean_reciprocal_rank:.3f} | "
                f"{m.expected_calibration_error:.3f} | ${m.mean_cost_per_case:.3f} |"
            )
        lines.append("")

    if "accuracy_by_condition" in chart_paths:
        lines.append(f"![accuracy]({chart_paths['accuracy_by_condition']})\n")
    if "reliability" in chart_paths:
        lines.append("## Calibration\n")
        lines.append(f"![reliability]({chart_paths['reliability']})\n")

    lines.append("## Convergence\n")
    lines.append(f"- Convergence rate: {run.convergence_rate:.1%}")
    lines.append(f"- Mean rounds: {run.mean_rounds:.1f}")
    lines.append(f"- p95 rounds: {run.p95_rounds}")
    lines.append("")

    lines.append("## Cost / latency\n")
    lines.append(f"- Mean cost: ${run.mean_cost_per_case:.4f} | p95: ${run.p95_cost_per_case:.4f}")
    lines.append(f"- Mean wall: {run.mean_wall_clock:.2f}s | p95: {run.p95_wall_clock:.2f}s")
    if "cost" in chart_paths:
        lines.append(f"![cost]({chart_paths['cost']})")
    lines.append("")

    if run.failure_categories:
        lines.append("## Failure mode breakdown\n")
        lines.append("| Category | N | % |")
        lines.append("|---|---|---|")
        total = sum(run.failure_categories.values()) or 1
        for cat, n in sorted(run.failure_categories.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {n} | {n/total:.1%} |")
        lines.append("")

    if run.per_disease_accuracy:
        # top 10 + worst 5
        sorted_by_n = sorted(run.per_disease_accuracy.values(),
                             key=lambda d: -d.n_cases)
        worst_5 = sorted(run.per_disease_accuracy.values(),
                         key=lambda d: d.top_1_accuracy)[:5]
        lines.append("## Per-disease accuracy (top 10 by sample count)\n")
        lines.append("| Disease | N | Top-1 | Top-3 | Conf when ✓ | Conf when ✗ |")
        lines.append("|---|---|---|---|---|---|")
        for d in sorted_by_n[:10]:
            lines.append(
                f"| {d.disease[:35]} | {d.n_cases} | {d.top_1_accuracy:.2f} | "
                f"{d.top_3_accuracy:.2f} | {d.mean_confidence_when_correct:.2f} | "
                f"{d.mean_confidence_when_wrong:.2f} |"
            )
        lines.append("")
        lines.append("### Worst 5 by accuracy\n")
        lines.append("| Disease | N | Top-1 | Top-3 |")
        lines.append("|---|---|---|---|")
        for d in worst_5:
            lines.append(f"| {d.disease[:35]} | {d.n_cases} | {d.top_1_accuracy:.2f} | {d.top_3_accuracy:.2f} |")
        lines.append("")
        if "per_disease" in chart_paths:
            lines.append(f"![per-disease]({chart_paths['per_disease']})\n")

    if run.cases_with_dissent:
        lines.append("## Hauser dissent\n")
        lines.append(f"- Cases with dissent: {run.cases_with_dissent}")
        lines.append(f"- Dissent correct rate: {run.hauser_dissent_correct_rate:.1%}" if run.hauser_dissent_correct_rate is not None else "")
        lines.append("")

    out.write_text("\n".join(lines))
    return out


def write_per_case_csv(metrics: list[CaseMetrics], out_path: Path) -> None:
    if not metrics:
        out_path.write_text("")
        return
    fieldnames = list(metrics[0].model_dump().keys())
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in metrics:
            row = m.model_dump()
            for k, v in row.items():
                if isinstance(v, (list, dict)):
                    row[k] = json.dumps(v)
            writer.writerow(row)


def write_run_artifacts(
    run: EvalRunMetrics,
    case_metrics: list[CaseMetrics],
    out_dir: Path,
    comparison: dict[str, EvalRunMetrics] | None = None,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(exist_ok=True)

    chart_paths: dict[str, str] = {}

    # Reliability diagram (always for this run)
    rel_path = charts_dir / "reliability.png"
    chart_reliability_diagram(run.reliability_bins, run.expected_calibration_error, rel_path)
    chart_paths["reliability"] = "charts/reliability.png"

    # Cost distribution
    costs = [m.total_cost_usd for m in case_metrics]
    cost_path = charts_dir / "cost.png"
    chart_cost_distribution(costs, cost_path)
    chart_paths["cost"] = "charts/cost.png"

    # Per-disease
    if run.per_disease_accuracy:
        pd_path = charts_dir / "per_disease.png"
        chart_per_disease_accuracy(run.per_disease_accuracy, pd_path)
        chart_paths["per_disease"] = "charts/per_disease.png"

    # Comparison chart if multiple conditions
    if comparison and len(comparison) > 1:
        acc_path = charts_dir / "accuracy_by_condition.png"
        chart_accuracy_by_condition(comparison, acc_path)
        chart_paths["accuracy_by_condition"] = "charts/accuracy_by_condition.png"

    # CSV
    write_per_case_csv(case_metrics, out_dir / "per_case.csv")

    # JSON
    (out_dir / "metrics.json").write_text(run.model_dump_json(indent=2))

    # Markdown summary
    write_summary_md(run, out_dir, chart_paths, comparison=comparison)

    return chart_paths
