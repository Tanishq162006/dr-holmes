"""FastAPI lifespan — startup/shutdown."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from dr_holmes.api.persistence import init_engine, close_engine
from dr_holmes.api.redis_client import init_redis, close_redis

log = logging.getLogger("dr_holmes.lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting Dr. Holmes API server")

    # ── DB ──────────────────────────────────────────────────────────
    try:
        await init_engine()
        log.info("DB engine initialized")
    except Exception as e:
        log.error(f"DB init failed: {e}")

    # ── Redis ───────────────────────────────────────────────────────
    try:
        client = await init_redis()
        if client:
            log.info("Redis connected")
        else:
            log.warning("Redis unavailable — running without fan-out / replay buffer")
    except Exception as e:
        log.error(f"Redis init failed: {e}")

    yield

    # ── Shutdown ────────────────────────────────────────────────────
    log.info("shutting down")
    await close_redis()
    await close_engine()
