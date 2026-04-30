"""WebSocket endpoint — live deliberation stream."""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from dr_holmes.api.dependencies import get_ws_user
from dr_holmes.api.persistence import get_sessionmaker, AuditLog
from dr_holmes.api.redis_client import get_redis, replay_events, _ch_stream

log = logging.getLogger("dr_holmes.ws")
router = APIRouter()


async def _send_handshake(ws: WebSocket, case_id: str) -> None:
    await ws.send_json({
        "type": "handshake",
        "protocol_version": "v1",
        "server_version": "0.4.0",
        "case_id": case_id,
        "accepted_commands": [
            "pause", "resume", "inject_evidence",
            "question_agent", "correct_agent",
            "conclude_now", "ack",
        ],
    })


async def _replay_from_postgres(ws: WebSocket, case_id: str, from_seq: int) -> int:
    """Replay events from Postgres audit log. Returns last sequence sent."""
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (await session.execute(
            select(AuditLog).where(
                AuditLog.case_id == case_id,
                AuditLog.sequence > from_seq,
            ).order_by(AuditLog.sequence)
        )).scalars().all()
    last_seq = from_seq
    for r in rows:
        ev = {
            "protocol_version": "v1",
            "sequence": r.sequence,
            "case_id": case_id,
            "event_type": r.event_type,
            "timestamp": r.timestamp.isoformat() if r.timestamp else datetime.utcnow().isoformat(),
            "payload": r.payload,
        }
        await ws.send_json(ev)
        last_seq = r.sequence
    return last_seq


async def _live_tail(ws: WebSocket, case_id: str, last_seq: int):
    """Subscribe to Redis pub/sub for live events. Skip events ≤ last_seq."""
    r = get_redis()
    if r is None:
        # No Redis — poll Postgres every 500ms as fallback
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=0.5)
                await _handle_command(case_id, msg)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                return
            new_last = await _replay_from_postgres(ws, case_id, last_seq)
            if new_last > last_seq:
                last_seq = new_last

    pubsub = r.pubsub()
    await pubsub.subscribe(_ch_stream(case_id))
    try:
        while True:
            # Check for client commands non-blocking
            try:
                msg_text = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
                try:
                    cmd = json.loads(msg_text)
                    await _handle_command(case_id, cmd)
                except json.JSONDecodeError:
                    pass
            except asyncio.TimeoutError:
                pass

            try:
                pub_msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if pub_msg is None:
                continue
            try:
                event = json.loads(pub_msg.get("data", "{}"))
                if int(event.get("sequence", 0)) <= last_seq:
                    continue
                await ws.send_json(event)
                last_seq = int(event.get("sequence", last_seq))
            except Exception as e:
                log.warning(f"failed to forward event: {e}")
    finally:
        try:
            await pubsub.unsubscribe(_ch_stream(case_id))
            await pubsub.aclose()
        except Exception:
            pass


async def _handle_command(case_id: str, cmd: dict) -> None:
    """Phase 6: validate, enqueue an Intervention, and signal resume if needed."""
    from dr_holmes.api.interventions import (
        enqueue_intervention, signal_resume, write_audit, next_intervention_sequence,
    )
    from dr_holmes.schemas.responses import Intervention

    command = cmd.get("command", "")
    payload = cmd.get("payload", {}) or {}
    log.info(f"WS command for {case_id}: {command}")

    if command not in {"pause", "resume", "inject_evidence",
                       "question_agent", "correct_agent", "conclude_now", "ack"}:
        log.warning(f"Unknown WS command: {command}")
        return

    if command == "ack":
        return  # heartbeat, no action

    try:
        intv = Intervention(
            case_id=case_id,
            type=command,  # type: ignore[arg-type]
            payload=payload,
            sequence_number=await next_intervention_sequence(case_id),
        )
    except Exception as e:
        log.warning(f"Bad WS command payload: {e}")
        return

    await enqueue_intervention(intv)
    await write_audit(
        case_id=case_id, sequence=intv.sequence_number,
        event_type=f"intervention_queued:{command}",
        payload={"intervention_id": intv.intervention_id, "payload": payload},
    )

    # Resume signal: pause/resume both unblock the runner's await_resume() —
    # pause is a no-op there but resume actually wakes it.
    if command == "resume":
        await signal_resume(case_id)


@router.websocket("/ws/cases/{case_id}")
async def case_stream(
    ws: WebSocket,
    case_id: str,
    from_sequence: int = Query(default=0),
    replay: bool = Query(default=False),
    token: Optional[str] = Query(default=None),
):
    user = await get_ws_user(token=token)
    await ws.accept()
    await _send_handshake(ws, case_id)

    try:
        last_seq = from_sequence
        # 1. Replay from Redis Stream first (if available)
        replay_buffered = await replay_events(case_id, from_sequence)
        for ev in replay_buffered:
            await ws.send_json(ev)
            last_seq = max(last_seq, int(ev.get("sequence", 0)))

        # 2. If --replay or beyond Redis Stream, fall back to Postgres
        if replay or not replay_buffered:
            last_seq = max(last_seq, await _replay_from_postgres(ws, case_id, last_seq))

        if replay:
            # Replay-only mode: don't subscribe to live stream
            await ws.send_json({
                "type": "replay_complete",
                "case_id": case_id,
                "last_sequence": last_seq,
            })
            return

        # 3. Live tail
        await _live_tail(ws, case_id, last_seq)

    except WebSocketDisconnect:
        log.info(f"client disconnected from {case_id}")
    except Exception as e:
        log.exception(f"WS error for {case_id}: {e}")
        try:
            await ws.send_json({
                "protocol_version": "v1",
                "sequence": 0, "case_id": case_id, "event_type": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "payload": {"error_type": type(e).__name__, "message": str(e),
                            "recoverable": False},
            })
        except Exception:
            pass
