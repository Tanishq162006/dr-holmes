"""Eval run browsing routes — for the frontend's /eval pages."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/eval", tags=["eval"])
_RUNS_ROOT = Path("./data/eval_runs")


@router.get("/runs")
async def list_runs() -> list[dict[str, Any]]:
    """List all eval runs by reading data/eval_runs/{run_id}/metrics.json."""
    if not _RUNS_ROOT.exists():
        return []
    out: list[dict[str, Any]] = []
    for run_dir in sorted(_RUNS_ROOT.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        metrics_file = run_dir / "metrics.json"
        if not metrics_file.exists():
            # The "compared" top-level dir might not have its own metrics.json
            # but the per-condition subdirs do. Aggregate them.
            sub_runs = []
            for sub in run_dir.iterdir():
                if sub.is_dir() and (sub / "metrics.json").exists():
                    try:
                        sub_runs.append(json.loads((sub / "metrics.json").read_text()))
                    except Exception:
                        continue
            if sub_runs:
                out.append({
                    "run_id": run_dir.name,
                    "is_multi_condition": True,
                    "n_conditions": len(sub_runs),
                    "conditions": [r.get("config", {}).get("conditions", []) for r in sub_runs],
                    "timestamp": sub_runs[0].get("timestamp"),
                    "n_cases_completed": sub_runs[0].get("n_cases_completed", 0),
                })
            continue
        try:
            data = json.loads(metrics_file.read_text())
            out.append({
                "run_id": run_dir.name,
                "is_multi_condition": False,
                "timestamp": data.get("timestamp"),
                "n_cases_completed": data.get("n_cases_completed", 0),
                "top_1_accuracy": data.get("top_1_accuracy", 0.0),
                "top_3_accuracy": data.get("top_3_accuracy", 0.0),
                "total_cost_usd": data.get("total_cost_usd", 0.0),
                "convergence_reason": data.get("convergence_reason"),
            })
        except Exception:
            continue
    return out


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Full run details — metrics + per-condition breakdown if multi-condition."""
    run_dir = _RUNS_ROOT / run_id
    if not run_dir.exists():
        raise HTTPException(404, f"Run {run_id!r} not found")

    out: dict[str, Any] = {"run_id": run_id, "conditions": {}}

    # Top-level metrics if exists
    if (run_dir / "metrics.json").exists():
        out["metrics"] = json.loads((run_dir / "metrics.json").read_text())

    # Per-condition subdirs
    for sub in sorted(run_dir.iterdir()):
        if not sub.is_dir() or sub.name == "charts":
            continue
        m_file = sub / "metrics.json"
        if not m_file.exists():
            continue
        try:
            out["conditions"][sub.name] = json.loads(m_file.read_text())
        except Exception:
            continue

    # List available chart paths
    charts: list[str] = []
    for sub in run_dir.rglob("charts"):
        if not sub.is_dir():
            continue
        for png in sub.glob("*.png"):
            charts.append(str(png.relative_to(_RUNS_ROOT)))
    out["chart_paths"] = charts
    return out


@router.get("/runs/{run_id}/cases")
async def list_run_cases(run_id: str, condition: str | None = None) -> list[dict[str, Any]]:
    """List per-case rows from per_case.csv for a run/condition."""
    run_dir = _RUNS_ROOT / run_id
    if not run_dir.exists():
        raise HTTPException(404, f"Run {run_id!r} not found")

    import csv
    rows: list[dict[str, Any]] = []
    targets = []
    if condition:
        targets = [run_dir / condition / "per_case.csv"]
    else:
        for sub in run_dir.iterdir():
            if sub.is_dir() and (sub / "per_case.csv").exists():
                targets.append(sub / "per_case.csv")

    for csv_path in targets:
        if not csv_path.exists():
            continue
        with csv_path.open() as f:
            for r in csv.DictReader(f):
                rows.append(r)
    return rows


@router.get("/runs/{run_id}/case/{case_id}/events")
async def get_case_events(run_id: str, case_id: str) -> list[dict[str, Any]]:
    """Return saved WSEvent stream for a case so the frontend can replay it.

    Looks first in Postgres audit_log (Phase 4), then falls back to a JSONL
    trace file under data/eval_runs/{run_id}/traces/{case_id}.json (if the
    eval run wrote one).
    """
    # Try Postgres audit_log
    try:
        from dr_holmes.api.persistence import get_sessionmaker, AuditLog
        from sqlalchemy import select
        sm = get_sessionmaker()
        async with sm() as session:
            rows = (await session.execute(
                select(AuditLog).where(AuditLog.case_id == case_id)
                                 .order_by(AuditLog.sequence)
            )).scalars().all()
        if rows:
            return [
                {"protocol_version": "v1",
                 "sequence": r.sequence,
                 "case_id": case_id,
                 "event_type": r.event_type,
                 "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                 "payload": r.payload}
                for r in rows
            ]
    except Exception:
        pass

    # Fallback: trace file from the eval run
    trace_file = _RUNS_ROOT / run_id / "traces" / f"{case_id}.json"
    if trace_file.exists():
        try:
            return json.loads(trace_file.read_text())
        except Exception:
            pass

    raise HTTPException(404, f"No event stream found for case {case_id!r}")
