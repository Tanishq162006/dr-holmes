"""Case runner — drives a LangGraph case to completion as an async task.

Bridges:
  LangGraph events  →  EventTranslator  →  Redis Stream + Pub/Sub  →  WS clients
                                       ↘  Postgres audit_log
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from dr_holmes.api.persistence import (
    get_sessionmaker, Case, AuditLog, AgentResponseRecord,
)
from dr_holmes.api.redis_client import (
    next_sequence, append_event, set_status, acquire_lock, release_lock,
)
from dr_holmes.api.translator import EventTranslator
from dr_holmes.orchestration.builder import build_phase3_graph, RenderHooks
from dr_holmes.orchestration.mock_agents import build_mock_agents, load_fixture


log = logging.getLogger("dr_holmes.runner")
MAX_CONCURRENT_CASES = 5
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CASES)
_active_tasks: dict[str, asyncio.Task] = {}


async def _emit(case_id: str, event: dict, owner_id: str = "dev") -> None:
    """Persist + fan-out a single event."""
    seq = await next_sequence(case_id)
    event["sequence"] = seq

    # Postgres audit (best-effort; don't fail the case if DB hiccups)
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            session.add(AuditLog(
                case_id=case_id,
                sequence=seq,
                event_type=event["event_type"],
                payload=event["payload"],
            ))
            await session.commit()
    except Exception as e:
        log.warning(f"audit_log write failed for {case_id} seq={seq}: {e}")

    # Redis Stream + pub/sub fan-out
    await append_event(case_id, event)


async def _run_mock_case(case_id: str, fixture_path: str, owner_id: str) -> None:
    """Execute a mock-mode case and stream events."""
    fixture = load_fixture(fixture_path)
    registry, caddick = build_mock_agents(fixture)

    translator = EventTranslator(case_id)

    async def emit_dict(d: dict):
        await _emit(case_id, d, owner_id)

    # Use sync hooks that schedule async emits
    loop = asyncio.get_event_loop()

    def run_coro_sync(coro):
        # Schedule on loop without awaiting; ordering preserved by sequence #
        asyncio.run_coroutine_threadsafe(coro, loop)

    def on_round_start(rn: int):
        ev = translator._ev("round_started", {"round_number": rn, "planned_speakers": []})
        run_coro_sync(emit_dict(ev))

    def on_agent_response(resp):
        rd = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        ev = translator._ev("agent_response", {
            "agent_name": rd.get("agent_name"),
            "response": rd,
        })
        run_coro_sync(emit_dict(ev))
        for ch in rd.get("challenges", []) or []:
            ev2 = translator._ev("challenge_raised", {
                "raiser": rd.get("agent_name"),
                "target": ch.get("target_agent"),
                "challenge_type": ch.get("challenge_type"),
                "content": ch.get("content"),
            })
            run_coro_sync(emit_dict(ev2))

    def on_caddick(synth_dict: dict):
        ev = translator._ev("caddick_routing", {
            "next_speakers": synth_dict.get("next_speakers", []),
            "routing_reason": synth_dict.get("routing_reason", ""),
            "synthesis_text": synth_dict.get("synthesis", ""),
        })
        run_coro_sync(emit_dict(ev))

    def on_team_dx(team_dx_list):
        if not team_dx_list:
            return
        top = team_dx_list[0]
        disease = top.disease if hasattr(top, "disease") else top.get("disease", "")
        prob = float(top.probability if hasattr(top, "probability") else top.get("probability", 0.0))
        prev = translator._last_top_prob
        ev = translator._ev("bayesian_update", {
            "top_dx": disease,
            "top_prob": prob,
            "deltas": [{"disease": disease, "prev": prev, "now": prob,
                        "change": (prob - prev) if prev is not None else 0.0}],
        })
        translator._last_top_prob = prob
        translator._last_top_dx = disease
        run_coro_sync(emit_dict(ev))

    def on_final(report):
        rd = report.model_dump() if hasattr(report, "model_dump") else dict(report)
        run_coro_sync(emit_dict(translator._ev("case_converged", {
            "consensus_dx": rd.get("consensus_dx", ""),
            "confidence": rd.get("confidence", 0.0),
            "convergence_reason": rd.get("convergence_reason", ""),
            "rounds_taken": rd.get("rounds_taken", 0),
        })))
        run_coro_sync(emit_dict(translator._ev("final_report", {"report": rd})))

    hooks = RenderHooks(
        on_round_start=on_round_start,
        on_agent_response=on_agent_response,
        on_caddick=on_caddick,
        on_team_dx=on_team_dx,
        on_final=on_final,
    )

    # Initial case_started event
    await emit_dict(translator._ev("case_started", {
        "patient_presentation": fixture.get("patient_presentation", {}),
        "agents": ["Hauser", "Forman", "Carmen", "Chen", "Wills", "Caddick"],
        "mock_mode": True,
        "fixture_path": fixture_path,
    }))

    # Phase 6: enable HITL with checkpointer + interrupt_after
    graph = build_phase3_graph(registry, caddick, hooks, enable_hitl=True)
    config = {"configurable": {"thread_id": case_id}, "recursion_limit": 80}

    # Initial state
    initial_state = {
        "case_id": case_id,
        "patient_presentation": fixture.get("patient_presentation", {}),
    }

    # ── HITL run loop: invoke until done, drain interventions at each pause ──
    from dr_holmes.api.interventions import (
        drain_pending, mark_applied, wait_for_resume as wait_resume,
        write_audit as audit,
    )
    from dr_holmes.orchestration.hitl import apply_interventions

    # Apply scripted human interventions (mock fixture's human_script)
    scripted_human = fixture.get("human_script", []) or []
    last_round_processed = 0

    state_or_resume: dict | None = initial_state
    iterations = 0
    MAX_ITERS = 40

    while iterations < MAX_ITERS:
        iterations += 1

        def _invoke(s=state_or_resume):
            return graph.invoke(s, config=config)

        result = await asyncio.to_thread(_invoke)
        state_or_resume = None  # subsequent invokes resume from checkpoint

        # If we've reached final report, we're done
        if result.get("final_report") or result.get("converged"):
            break

        # Determine current round; queue scripted interventions whose
        # `after_round` was just completed
        current_round = int(result.get("round_number", 0))
        for entry in scripted_human:
            ar = int(entry.get("after_round", 0))
            if ar > last_round_processed and ar <= current_round:
                # Build Intervention object and queue via Redis (or in-memory)
                from dr_holmes.api.interventions import (
                    enqueue_intervention, next_intervention_sequence,
                )
                from dr_holmes.schemas.responses import Intervention as _Intv
                intv_dict = entry.get("intervention", {})
                intv = _Intv(
                    case_id=case_id,
                    type=intv_dict.get("type"),  # type: ignore[arg-type]
                    payload=intv_dict.get("payload", {}),
                    sequence_number=await next_intervention_sequence(case_id),
                )
                await enqueue_intervention(intv)
                await audit(case_id=case_id, sequence=intv.sequence_number,
                            event_type=f"intervention_queued:{intv.type}",
                            payload={"intervention_id": intv.intervention_id,
                                     "payload": intv.payload, "scripted": True})
        last_round_processed = max(last_round_processed, current_round)

        # Drain pending interventions
        pending = await drain_pending(case_id)
        if pending:
            # Filter out any already-applied (idempotency)
            fresh = []
            for intv in pending:
                if await mark_applied(case_id, intv.intervention_id):
                    fresh.append(intv)
            if fresh:
                # Read current state, apply, write back via update_state
                snapshot = graph.get_state(config).values
                new_state, emitted = apply_interventions(snapshot, fresh)
                graph.update_state(config, new_state)
                # Emit each intervention event over WS
                for ev in emitted:
                    await _emit(case_id, translator._ev(ev["event_type"], ev["payload"]),
                                owner_id)
                    await audit(case_id=case_id,
                                sequence=ev["payload"].get("intervention_id", ""),  # type: ignore[arg-type]
                                event_type=f"intervention_applied:{ev['event_type']}",
                                payload=ev["payload"])

        # Check if we paused
        post_state = graph.get_state(config).values
        if post_state.get("case_status") == "paused":
            # Wait for resume signal
            await wait_resume(case_id, timeout=600.0)
            # Loop continues: graph.invoke(None) resumes from checkpoint

        # Forced conclusion — graph will route to final_report on next invoke
        if post_state.get("forced_conclusion"):
            continue

    result = graph.get_state(config).values

    # Persist final state to Postgres
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            row = (await session.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
            if row:
                row.status = "concluded"
                row.final_report = result.get("final_report")
                row.convergence_reason = result.get("convergence_reason")
                row.rounds_taken = result.get("round_number", 0)
                row.concluded_at = datetime.utcnow()
                await session.commit()
    except Exception as e:
        log.warning(f"final state persist failed for {case_id}: {e}")

    # Persist per-agent responses for fast querying
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            for agent, hist in (result.get("agent_responses") or {}).items():
                for r in hist:
                    rd = r.model_dump() if hasattr(r, "model_dump") else dict(r)
                    session.add(AgentResponseRecord(
                        case_id=case_id,
                        round_number=int(rd.get("turn_number", 0)),
                        agent_name=agent,
                        response=rd,
                    ))
            await session.commit()
    except Exception as e:
        log.warning(f"agent_responses persist failed for {case_id}: {e}")


async def run_case(case_id: str, mock_mode: bool, fixture_path: Optional[str],
                   owner_id: str = "dev") -> None:
    """Top-level case runner. Acquires lock, runs to completion, releases."""
    if not await acquire_lock(case_id, ttl=600):
        log.error(f"Could not acquire lock for case {case_id}")
        return

    try:
        async with _semaphore:
            await set_status(case_id, "running", owner_id)
            try:
                if mock_mode and fixture_path:
                    await _run_mock_case(case_id, fixture_path, owner_id)
                else:
                    # Live mode requires LLM keys — Phase 4.5+
                    err = {
                        "protocol_version": "v1", "sequence": -1, "case_id": case_id,
                        "event_type": "error",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "payload": {
                            "error_type": "live_mode_unavailable",
                            "message": "Live mode pending LLM provider integration. Use mock_mode=true.",
                            "recoverable": False,
                        },
                    }
                    await _emit(case_id, err, owner_id)
                await set_status(case_id, "concluded", owner_id)
            except Exception as e:
                log.exception(f"case {case_id} failed: {e}")
                err = {
                    "protocol_version": "v1", "sequence": -1, "case_id": case_id,
                    "event_type": "error",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "payload": {"error_type": type(e).__name__, "message": str(e),
                                "recoverable": False},
                }
                await _emit(case_id, err, owner_id)
                await set_status(case_id, "errored", owner_id)
    finally:
        await release_lock(case_id)
        _active_tasks.pop(case_id, None)


def schedule_case(case_id: str, mock_mode: bool, fixture_path: Optional[str],
                  owner_id: str = "dev") -> asyncio.Task:
    """Fire-and-forget case start. Returns the task for testing/cancel."""
    task = asyncio.create_task(run_case(case_id, mock_mode, fixture_path, owner_id))
    _active_tasks[case_id] = task
    return task
