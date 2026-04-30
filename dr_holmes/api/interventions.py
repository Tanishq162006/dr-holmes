"""Redis intervention queue + audit helpers for Phase 6 HITL.

Schema (per case):
  case:{id}:interventions   LIST    pending Intervention JSONs (FIFO)
  case:{id}:applied_ids     SET     intervention_ids already applied (idempotency)
  case:{id}:int_seq         COUNTER monotonic sequence per case
  case:{id}:resume_signal   PUB/SUB channel woken on resume

In-memory fallback used when Redis is unavailable so unit tests don't need
a Redis container.
"""
from __future__ import annotations
import json
import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from dr_holmes.api.persistence import get_sessionmaker, AuditLog
from dr_holmes.api.redis_client import get_redis
from dr_holmes.schemas.responses import Intervention


log = logging.getLogger("dr_holmes.interventions")


# ── In-memory fallback (single-process tests) ──────────────────────────────
_mem_queues: dict[str, deque[str]] = defaultdict(deque)
_mem_applied: dict[str, set[str]] = defaultdict(set)
_mem_seq: dict[str, int] = defaultdict(int)


def _k_queue(case_id: str) -> str:    return f"case:{case_id}:interventions"
def _k_applied(case_id: str) -> str:  return f"case:{case_id}:applied_ids"
def _k_seq(case_id: str) -> str:      return f"case:{case_id}:int_seq"
def _ch_resume(case_id: str) -> str:  return f"case:{case_id}:resume_signal"


# ── Sequence ───────────────────────────────────────────────────────────────

async def next_intervention_sequence(case_id: str) -> int:
    r = get_redis()
    if r is None:
        _mem_seq[case_id] += 1
        return _mem_seq[case_id]
    val = await r.incr(_k_seq(case_id))
    return int(val)


# ── Enqueue ────────────────────────────────────────────────────────────────

async def enqueue_intervention(intv: Intervention) -> None:
    """RPUSH to FIFO queue. Idempotent: silently drops if intervention_id already applied."""
    if intv.sequence_number == 0:
        intv.sequence_number = await next_intervention_sequence(intv.case_id)

    payload = intv.model_dump_json()
    r = get_redis()
    if r is None:
        if intv.intervention_id in _mem_applied[intv.case_id]:
            return
        _mem_queues[intv.case_id].append(payload)
        return

    # If already applied, skip enqueue (idempotency at edge)
    if await r.sismember(_k_applied(intv.case_id), intv.intervention_id):
        return
    await r.rpush(_k_queue(intv.case_id), payload)
    await r.expire(_k_queue(intv.case_id), 24 * 3600)


# ── Atomic drain ───────────────────────────────────────────────────────────

async def drain_pending(case_id: str) -> list[Intervention]:
    """Atomically read + clear pending interventions for a case.

    Filters out any intervention_id already in applied_ids (handles concurrent
    duplicate enqueues).
    """
    r = get_redis()
    if r is None:
        items = list(_mem_queues[case_id])
        _mem_queues[case_id].clear()
        out: list[Intervention] = []
        for raw in items:
            intv = Intervention.model_validate_json(raw)
            if intv.intervention_id in _mem_applied[case_id]:
                continue
            out.append(intv)
        return out

    # Redis: pipeline LRANGE + DEL atomically
    async with r.pipeline(transaction=True) as pipe:
        pipe.lrange(_k_queue(case_id), 0, -1)
        pipe.delete(_k_queue(case_id))
        results = await pipe.execute()
    raw_items: list[str] = results[0] or []

    out: list[Intervention] = []
    for raw in raw_items:
        try:
            intv = Intervention.model_validate_json(raw)
        except Exception as e:
            log.warning(f"Bad intervention JSON in queue for {case_id}: {e}")
            continue
        if await r.sismember(_k_applied(case_id), intv.intervention_id):
            continue
        out.append(intv)
    return out


# ── Mark applied ───────────────────────────────────────────────────────────

async def mark_applied(case_id: str, intervention_id: str) -> bool:
    """Returns True if newly marked, False if already was applied."""
    r = get_redis()
    if r is None:
        if intervention_id in _mem_applied[case_id]:
            return False
        _mem_applied[case_id].add(intervention_id)
        return True
    # SADD returns 1 if added, 0 if already present
    added = await r.sadd(_k_applied(case_id), intervention_id)
    if added:
        await r.expire(_k_applied(case_id), 24 * 3600)
    return bool(added)


# ── Resume signal ──────────────────────────────────────────────────────────

async def signal_resume(case_id: str) -> None:
    r = get_redis()
    if r is None:
        return  # in-memory tests don't actually pause
    await r.publish(_ch_resume(case_id), "resume")


async def wait_for_resume(case_id: str, timeout: float = 600.0) -> None:
    """Block until a resume signal arrives or timeout."""
    r = get_redis()
    if r is None:
        return
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(_ch_resume(case_id))
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                return
    finally:
        try:
            await pubsub.unsubscribe(_ch_resume(case_id))
            await pubsub.aclose()
        except Exception:
            pass


# ── Audit log ──────────────────────────────────────────────────────────────

async def write_audit(case_id: str, sequence: int, event_type: str, payload: dict) -> None:
    """Append-only audit log row. Best-effort; logs warning on failure."""
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            session.add(AuditLog(
                case_id=case_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
            ))
            await session.commit()
    except Exception as e:
        log.warning(f"audit_log write failed for {case_id} ({event_type}): {e}")


# ── Test-only helper ───────────────────────────────────────────────────────

def _reset_for_tests() -> None:
    """Clear in-memory state. Call from test fixtures."""
    _mem_queues.clear()
    _mem_applied.clear()
    _mem_seq.clear()
