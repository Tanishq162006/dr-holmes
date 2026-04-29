"""Async Redis client for live case state, event streams, pub/sub fan-out."""
from __future__ import annotations
import os
import json
from typing import Optional

import redis.asyncio as aioredis


_client: Optional[aioredis.Redis] = None
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_TTL_SECONDS = 24 * 3600
_STREAM_MAXLEN = 500


async def init_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(_REDIS_URL, decode_responses=True)
        try:
            await _client.ping()
        except Exception:
            # Mark as unavailable but don't crash startup; routes degrade gracefully
            _client = None
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> Optional[aioredis.Redis]:
    return _client


# ── Per-case key helpers ────────────────────────────────────────────────

def _k_state(case_id: str) -> str:    return f"case:{case_id}:state"
def _k_seq(case_id: str) -> str:      return f"case:{case_id}:seq"
def _k_events(case_id: str) -> str:   return f"case:{case_id}:events"
def _k_status(case_id: str) -> str:   return f"case:{case_id}:status"
def _k_owner(case_id: str) -> str:    return f"case:{case_id}:owner"
def _k_lock(case_id: str) -> str:     return f"case:{case_id}:lock"
def _k_active() -> str:               return "cases:active"
def _ch_stream(case_id: str) -> str:  return f"case:{case_id}:stream"


# ── High-level operations ───────────────────────────────────────────────

async def next_sequence(case_id: str) -> int:
    r = get_redis()
    if r is None:
        return 0
    val = await r.incr(_k_seq(case_id))
    await r.expire(_k_seq(case_id), _TTL_SECONDS)
    return int(val)


async def append_event(case_id: str, event: dict) -> None:
    """Append event to Redis Stream + publish to channel for live subscribers."""
    r = get_redis()
    if r is None:
        return
    # Streams require flat string fields — wrap payload as JSON string
    await r.xadd(
        _k_events(case_id),
        {"event": json.dumps(event)},
        maxlen=_STREAM_MAXLEN,
        approximate=True,
    )
    await r.expire(_k_events(case_id), _TTL_SECONDS)
    await r.publish(_ch_stream(case_id), json.dumps(event))


async def replay_events(case_id: str, from_sequence: int = 0) -> list[dict]:
    """Read buffered events with sequence > from_sequence."""
    r = get_redis()
    if r is None:
        return []
    raw = await r.xrange(_k_events(case_id))
    out = []
    for _stream_id, fields in raw:
        try:
            ev = json.loads(fields.get("event", "{}"))
            if int(ev.get("sequence", 0)) > from_sequence:
                out.append(ev)
        except Exception:
            continue
    return out


async def set_status(case_id: str, status: str, owner_id: str = "dev") -> None:
    r = get_redis()
    if r is None:
        return
    await r.setex(_k_status(case_id), _TTL_SECONDS, status)
    await r.setex(_k_owner(case_id), _TTL_SECONDS, owner_id)
    if status == "running":
        await r.sadd(_k_active(), case_id)
    elif status in ("concluded", "errored", "interrupted"):
        await r.srem(_k_active(), case_id)


async def get_status(case_id: str) -> Optional[str]:
    r = get_redis()
    if r is None:
        return None
    val = await r.get(_k_status(case_id))
    return val


async def acquire_lock(case_id: str, ttl: int = 30) -> bool:
    r = get_redis()
    if r is None:
        return True  # no Redis = single-process, no contention
    val = os.getpid()
    return bool(await r.set(_k_lock(case_id), str(val), nx=True, ex=ttl))


async def release_lock(case_id: str) -> None:
    r = get_redis()
    if r is None:
        return
    await r.delete(_k_lock(case_id))


async def list_active() -> list[str]:
    r = get_redis()
    if r is None:
        return []
    return list(await r.smembers(_k_active()))
