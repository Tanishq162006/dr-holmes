"""Process-global budget guard. Every live LLM call goes through here.

Eight guards (per architecture):
  1. Live mode requires DR_HOLMES_ALLOW_LIVE=true
  2. Hard session budget (DR_HOLMES_MAX_BUDGET_USD)
  3. Per-case cap (DR_HOLMES_MAX_COST_PER_CASE_USD)
  4. Per-call max_tokens cap (DR_HOLMES_MAX_TOKENS_PER_CALL)
  5. Pre-flight estimator (estimate(case) ≤ remaining * 0.5 to start)
  6. Persistent cost log (data/llm_calls.db)
  7. Single live case at a time (semaphore=1)
  8. Confirmation header on POST /api/cases for live mode

This module enforces 1, 2, 3, 4, 6. Guards 5, 7, 8 live in api/routes/cases.py
where they have access to request context.
"""
from __future__ import annotations
import os
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dr_holmes.eval.cost import estimate_cost


# ── Env-driven configuration ──────────────────────────────────────────────

def _flag(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").lower().strip()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _floatenv(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _intenv(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def live_mode_enabled() -> bool:
    """Guard 1: live mode is opt-in via env var."""
    return _flag("DR_HOLMES_ALLOW_LIVE", False)


def session_budget_usd() -> float:
    return _floatenv("DR_HOLMES_MAX_BUDGET_USD", 2.0)


def per_case_budget_usd() -> float:
    return _floatenv("DR_HOLMES_MAX_COST_PER_CASE_USD", 0.50)


def max_tokens_per_call() -> int:
    """Guard 4. Agents must clamp max_tokens to this before LLM call."""
    return _intenv("DR_HOLMES_MAX_TOKENS_PER_CALL", 500)


# ── Errors ────────────────────────────────────────────────────────────────

class LiveModeDisabled(Exception):
    """Raised when a live LLM call is attempted but DR_HOLMES_ALLOW_LIVE != true."""


class SessionBudgetExceeded(Exception):
    """Raised when the global session budget would be breached."""


class CaseBudgetExceeded(Exception):
    """Raised when an individual case has hit its per-case cap."""


# ── Persistent cost log ───────────────────────────────────────────────────

_DB_PATH = os.getenv("LLM_CALL_LOG_PATH", "./data/llm_calls.db")


def _init_log_db():
    Path(os.path.dirname(_DB_PATH) or ".").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT NOT NULL,
            case_id       TEXT,
            agent_name    TEXT,
            provider      TEXT NOT NULL,
            model         TEXT NOT NULL,
            input_tokens  INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd      REAL NOT NULL,
            session_total REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_llm_calls_case ON llm_calls (case_id);
        CREATE INDEX IF NOT EXISTS ix_llm_calls_ts   ON llm_calls (timestamp);
        """)


# ── Process-global state ──────────────────────────────────────────────────

@dataclass
class _BudgetState:
    session_total: float = 0.0
    per_case_total: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    n_calls: int = 0
    halted: bool = False


_STATE = _BudgetState()
_LOCK = threading.Lock()


def session_total_usd() -> float:
    return _STATE.session_total


def case_total_usd(case_id: str) -> float:
    return _STATE.per_case_total.get(case_id, 0.0)


def remaining_session_budget() -> float:
    return max(0.0, session_budget_usd() - _STATE.session_total)


def remaining_case_budget(case_id: str) -> float:
    return max(0.0, per_case_budget_usd() - case_total_usd(case_id))


def reset_for_tests() -> None:
    """Test helper — zero out global state."""
    with _LOCK:
        _STATE.session_total = 0.0
        _STATE.per_case_total.clear()
        _STATE.n_calls = 0
        _STATE.halted = False


# ── Pre-flight check ──────────────────────────────────────────────────────

def assert_live_allowed() -> None:
    """Guard 1 — always check before any live LLM call."""
    if not live_mode_enabled():
        raise LiveModeDisabled(
            "Live mode is disabled. Set DR_HOLMES_ALLOW_LIVE=true to enable. "
            "Use mock_mode=True for free testing."
        )


def assert_within_budget(*, case_id: str, projected_cost: float) -> None:
    """Guards 2 + 3 — refuse the call if it would breach either cap.

    Trips at 95% of either limit so we always have headroom for in-flight calls.
    """
    if _STATE.halted:
        raise SessionBudgetExceeded("Session already halted — restart process.")

    new_session = _STATE.session_total + projected_cost
    if new_session > session_budget_usd() * 0.95:
        _STATE.halted = True
        raise SessionBudgetExceeded(
            f"Session budget {session_budget_usd():.2f} USD would be exceeded "
            f"(running={_STATE.session_total:.4f} + projected={projected_cost:.4f})."
        )

    new_case = _STATE.per_case_total.get(case_id, 0.0) + projected_cost
    if new_case > per_case_budget_usd() * 0.95:
        raise CaseBudgetExceeded(
            f"Per-case budget {per_case_budget_usd():.2f} USD would be exceeded "
            f"(case={case_id}, running={case_total_usd(case_id):.4f} + "
            f"projected={projected_cost:.4f})."
        )


def project_cost(provider: str, model: str, in_tokens: int, out_tokens: int) -> float:
    return estimate_cost(provider, model, in_tokens, out_tokens)


def project_max_cost(provider: str, model: str, prompt_tokens: int) -> float:
    """Worst-case projection: assume the model emits up to max_tokens output tokens."""
    return estimate_cost(provider, model, prompt_tokens, max_tokens_per_call())


# ── Record a call ─────────────────────────────────────────────────────────

def record_call(
    *,
    case_id: str = "",
    agent_name: str = "",
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Update in-memory totals + persist to SQLite. Returns the cost."""
    cost = estimate_cost(provider, model, input_tokens, output_tokens)
    with _LOCK:
        _STATE.session_total += cost
        if case_id:
            _STATE.per_case_total[case_id] += cost
        _STATE.n_calls += 1
        # Persist
        try:
            _init_log_db()
            with sqlite3.connect(_DB_PATH) as c:
                c.execute(
                    "INSERT INTO llm_calls "
                    "(timestamp, case_id, agent_name, provider, model, "
                    " input_tokens, output_tokens, cost_usd, session_total) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (datetime.utcnow().isoformat(), case_id, agent_name,
                     provider, model, input_tokens, output_tokens,
                     cost, _STATE.session_total),
                )
        except Exception:
            # Logging failure must never block a call — record in memory only
            pass
    return cost


# ── Context manager around a single call ──────────────────────────────────

@contextmanager
def llm_call_guard(
    *,
    case_id: str,
    agent_name: str,
    provider: str,
    model: str,
    expected_input_tokens: int,
):
    """Wraps a live LLM call. Pre-flights guards 1-4, yields control to caller,
    then records actual usage on completion.

    Usage:
        with llm_call_guard(...) as guard:
            response = client.chat.completions.create(..., max_tokens=guard.max_tokens)
            guard.set_actual(response.usage.prompt_tokens, response.usage.completion_tokens)
    """
    assert_live_allowed()
    projected = project_max_cost(provider, model, expected_input_tokens)
    assert_within_budget(case_id=case_id, projected_cost=projected)

    class _Guard:
        max_tokens = max_tokens_per_call()
        actual_in = 0
        actual_out = 0
        def set_actual(self, in_tok: int, out_tok: int):
            self.actual_in = in_tok
            self.actual_out = out_tok

    g = _Guard()
    yield g
    if g.actual_in or g.actual_out:
        record_call(
            case_id=case_id, agent_name=agent_name,
            provider=provider, model=model,
            input_tokens=g.actual_in, output_tokens=g.actual_out,
        )


# ── Snapshot for UI / debug ───────────────────────────────────────────────

def snapshot() -> dict:
    return {
        "live_mode_enabled": live_mode_enabled(),
        "session_budget_usd": session_budget_usd(),
        "session_total_usd": _STATE.session_total,
        "session_remaining_usd": remaining_session_budget(),
        "per_case_budget_usd": per_case_budget_usd(),
        "max_tokens_per_call": max_tokens_per_call(),
        "n_calls": _STATE.n_calls,
        "halted": _STATE.halted,
        "per_case_totals": dict(_STATE.per_case_total),
    }
