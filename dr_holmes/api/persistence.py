"""Postgres / SQLite async persistence + Redis client.

Falls back to SQLite (./data/cases.db) if DATABASE_URL is unset.
"""
from __future__ import annotations
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Text, Integer, BigInteger, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Index, JSON, func,
)

# SQLite autoincrement requires plain INTEGER PK; for portability across
# Postgres + SQLite we declare BigInteger.with_variant(Integer(), "sqlite").
_AUTOINC_BIGINT = BigInteger().with_variant(Integer(), "sqlite")
from sqlalchemy.ext.asyncio import (
    AsyncSession, AsyncEngine, create_async_engine, async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Async ORM models ──────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    id:                   Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id:             Mapped[str] = mapped_column(String(64), default="dev", index=True)
    # Status:
    #   pending | running | paused | concluded (reversible — doctor can add findings)
    #   | finalized (terminal — doctor has locked it) | errored | interrupted
    status:               Mapped[str] = mapped_column(String(16), index=True)
    mock_mode:            Mapped[bool] = mapped_column(Boolean, default=False)
    fixture_path:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    patient_presentation: Mapped[dict] = mapped_column(JSON)
    # `final_report` = the most recent assessment (updates each round on followup)
    final_report:         Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # `assessment_history` = list of every prior FinalReport snapshot (Phase 6.6)
    assessment_history:   Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # `finalized_report` = immutable copy frozen when doctor locks the case
    finalized_report:     Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Per-case persistent evidence log so followup cycles can rebuild state
    evidence_log:         Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    convergence_reason:   Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rounds_taken:         Mapped[int] = mapped_column(Integer, default=0)
    followup_count:       Mapped[int] = mapped_column(Integer, default=0)
    created_at:           Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:           Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    concluded_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id:         Mapped[int] = mapped_column(_AUTOINC_BIGINT, primary_key=True, autoincrement=True)
    case_id:    Mapped[str] = mapped_column(String(64), ForeignKey("cases.id", ondelete="CASCADE"))
    sequence:   Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    payload:    Mapped[dict] = mapped_column(JSON)
    timestamp:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("case_id", "sequence", name="uq_case_seq"),
        Index("ix_audit_case_seq", "case_id", "sequence"),
        Index("ix_audit_event_type", "event_type"),
    )


class AgentResponseRecord(Base):
    __tablename__ = "agent_responses"
    id:           Mapped[int] = mapped_column(_AUTOINC_BIGINT, primary_key=True, autoincrement=True)
    case_id:      Mapped[str] = mapped_column(String(64), ForeignKey("cases.id", ondelete="CASCADE"))
    round_number: Mapped[int] = mapped_column(Integer)
    agent_name:   Mapped[str] = mapped_column(String(32))
    response:     Mapped[dict] = mapped_column(JSON)
    timestamp:    Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_responses_case_round", "case_id", "round_number"),)


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"
    id:           Mapped[int] = mapped_column(_AUTOINC_BIGINT, primary_key=True, autoincrement=True)
    case_id:      Mapped[str] = mapped_column(String(64), ForeignKey("cases.id", ondelete="CASCADE"))
    round_number: Mapped[int] = mapped_column(Integer)
    agent_name:   Mapped[str] = mapped_column(String(32))
    tool_name:    Mapped[str] = mapped_column(String(64))
    args:         Mapped[dict] = mapped_column(JSON)
    result:       Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    latency_ms:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timestamp:    Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Engine factory ────────────────────────────────────────────────────────

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _resolve_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        # Normalize postgres URLs to async driver
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    # SQLite fallback for dev
    os.makedirs("./data", exist_ok=True)
    return "sqlite+aiosqlite:///./data/cases.db"


async def init_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine
    url = _resolve_url()
    _engine = create_async_engine(url, echo=False, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return _engine


async def close_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("DB not initialized — call init_engine() first")
    return _sessionmaker
