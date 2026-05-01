"""Case REST endpoints."""
from __future__ import annotations
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from sqlalchemy import select, func

from dr_holmes.api.dependencies import get_current_user, User
from dr_holmes.api.persistence import (
    get_sessionmaker, Case, AuditLog, AgentResponseRecord,
)
from dr_holmes.api.schemas.requests import (
    CaseCreateRequest, CaseSummary, CaseDetail, EvidenceInjection,
    FollowupRequest,
)
from dr_holmes.api.runner import schedule_case
from dr_holmes.api.redis_client import set_status, get_status

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", response_model=CaseSummary, status_code=status.HTTP_201_CREATED)
async def create_case(
    req: CaseCreateRequest,
    user: User = Depends(get_current_user),
    x_drholmes_live_confirm: str | None = Header(default=None),
):
    # ── Phase 6.5 budget guards ─────────────────────────────────────────────
    if not req.mock_mode:
        from dr_holmes.safety import budget as _budget
        # Guard 1: live mode env flag
        if not _budget.live_mode_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Live mode disabled. Set DR_HOLMES_ALLOW_LIVE=true on the server."
            )
        # Guard 8: explicit confirm header so live cases can't be triggered by accident
        if (x_drholmes_live_confirm or "").lower() != "yes":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Live cases require X-DrHolmes-Live-Confirm: yes header."
            )
        # Guard 5: pre-flight cost estimator
        # Realistic per-case spend with max_tokens=500 + 6 agents × 3-4 rounds:
        #   3 mini-agents × ~2K tokens × $0.50/1M  ≈ $0.003
        #   2 gpt-4o agents × ~3K tokens × $6/1M   ≈ $0.036
        #   1 grok-2  × ~3K tokens × $6/1M         ≈ $0.018
        #   Caddick × few rounds × ~2K tokens      ≈ $0.024
        # Total ≈ $0.08-0.12; pad 3× for safety   ≈ $0.30 estimate
        rough_estimate = max(0.30, _budget.per_case_budget_usd() * 0.6)
        remaining = _budget.remaining_session_budget()
        if rough_estimate > remaining:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Estimated case cost ~${rough_estimate:.2f} exceeds "
                       f"remaining session budget ${remaining:.2f}. Reset session "
                       f"or raise DR_HOLMES_MAX_BUDGET_USD."
            )

    case_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    sm = get_sessionmaker()
    async with sm() as session:
        case = Case(
            id=case_id,
            owner_id=user.owner_id,
            status="pending",
            mock_mode=req.mock_mode,
            fixture_path=req.fixture_path,
            patient_presentation=req.patient_presentation,
            include_park=req.include_park,
        )
        session.add(case)
        await session.commit()

    await set_status(case_id, "pending", user.owner_id)
    schedule_case(case_id, req.mock_mode, req.fixture_path, user.owner_id)

    return CaseSummary(
        id=case_id, owner_id=user.owner_id, status="pending",
        mock_mode=req.mock_mode, include_park=req.include_park, rounds_taken=0,
        created_at=datetime.utcnow().isoformat(),
    )


@router.get("", response_model=list[CaseSummary])
async def list_cases(
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user),
):
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = select(Case).where(Case.owner_id == user.owner_id)
        if status_filter:
            stmt = stmt.where(Case.status == status_filter)
        stmt = stmt.order_by(Case.created_at.desc()).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()
    return [
        CaseSummary(
            id=c.id, owner_id=c.owner_id, status=c.status,
            mock_mode=c.mock_mode,
            include_park=getattr(c, "include_park", False),
            rounds_taken=c.rounds_taken,
            convergence_reason=c.convergence_reason,
            followup_count=getattr(c, "followup_count", 0) or 0,
            created_at=c.created_at.isoformat() if c.created_at else "",
            concluded_at=c.concluded_at.isoformat() if c.concluded_at else None,
            finalized_at=c.finalized_at.isoformat() if getattr(c, "finalized_at", None) else None,
        )
        for c in rows
    ]


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str, user: User = Depends(get_current_user)):
    sm = get_sessionmaker()
    async with sm() as session:
        case = (await session.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    if case.owner_id != user.owner_id and user.owner_id != "dev":
        raise HTTPException(403, "Not your case")
    return CaseDetail(
        id=case.id, owner_id=case.owner_id, status=case.status,
        mock_mode=case.mock_mode,
        include_park=getattr(case, "include_park", False),
        rounds_taken=case.rounds_taken,
        convergence_reason=case.convergence_reason,
        followup_count=getattr(case, "followup_count", 0) or 0,
        created_at=case.created_at.isoformat() if case.created_at else "",
        concluded_at=case.concluded_at.isoformat() if case.concluded_at else None,
        finalized_at=case.finalized_at.isoformat() if getattr(case, "finalized_at", None) else None,
        patient_presentation=case.patient_presentation,
        final_report=case.final_report,
        finalized_report=getattr(case, "finalized_report", None),
        assessment_history=getattr(case, "assessment_history", None) or [],
        evidence_log=getattr(case, "evidence_log", None) or [],
    )


@router.delete("/{case_id}", status_code=204)
async def delete_case(case_id: str, user: User = Depends(get_current_user)):
    sm = get_sessionmaker()
    async with sm() as session:
        case = (await session.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
        if not case:
            raise HTTPException(404, "Case not found")
        if case.owner_id != user.owner_id and user.owner_id != "dev":
            raise HTTPException(403, "Not your case")
        await session.delete(case)
        await session.commit()
    return None


@router.get("/{case_id}/transcript")
async def get_transcript(case_id: str, user: User = Depends(get_current_user)):
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (await session.execute(
            select(AuditLog).where(AuditLog.case_id == case_id).order_by(AuditLog.sequence)
        )).scalars().all()
    return [
        {"sequence": r.sequence, "event_type": r.event_type,
         "payload": r.payload, "timestamp": r.timestamp.isoformat() if r.timestamp else None}
        for r in rows
    ]


@router.get("/{case_id}/differentials")
async def get_differentials(case_id: str, user: User = Depends(get_current_user)):
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (await session.execute(
            select(AuditLog).where(
                AuditLog.case_id == case_id,
                AuditLog.event_type == "bayesian_update",
            ).order_by(AuditLog.sequence.desc()).limit(1)
        )).scalars().all()
    if not rows:
        return {"differentials": []}
    return rows[0].payload


@router.get("/{case_id}/report")
async def get_report(case_id: str, user: User = Depends(get_current_user)):
    sm = get_sessionmaker()
    async with sm() as session:
        case = (await session.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status != "concluded":
        raise HTTPException(409, f"Case not concluded yet (status={case.status})")
    return case.final_report


@router.post("/{case_id}/pause", status_code=202)
async def pause_case(case_id: str, user: User = Depends(get_current_user)):
    await set_status(case_id, "paused", user.owner_id)
    return {"status": "paused"}


@router.post("/{case_id}/resume", status_code=202)
async def resume_case(case_id: str, user: User = Depends(get_current_user)):
    await set_status(case_id, "running", user.owner_id)
    return {"status": "running"}


@router.post("/{case_id}/finalize", status_code=200)
async def finalize_case(case_id: str, user: User = Depends(get_current_user)):
    """Doctor's permanent lock. Freezes the latest final_report into
    `finalized_report` and sets status='finalized' (terminal)."""
    sm = get_sessionmaker()
    async with sm() as session:
        case = (await session.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
        if not case:
            raise HTTPException(404, "Case not found")
        if case.owner_id != user.owner_id and user.owner_id != "dev":
            raise HTTPException(403, "Not your case")
        if case.status == "finalized":
            return {"status": "finalized", "note": "already finalized"}
        if case.status not in ("concluded", "errored"):
            raise HTTPException(
                409,
                f"Cannot finalize from status={case.status}. "
                "Wait for AI to produce an assessment first.",
            )
        # Freeze the latest assessment
        case.finalized_report = case.final_report
        case.status = "finalized"
        case.finalized_at = datetime.utcnow()
        await session.commit()
    await set_status(case_id, "finalized", user.owner_id)
    return {"status": "finalized"}


# Kept for backward-compat — old "conclude" button maps to finalize.
@router.post("/{case_id}/conclude", status_code=202)
async def conclude_case(case_id: str, user: User = Depends(get_current_user)):
    return await finalize_case(case_id, user)


@router.post("/{case_id}/evidence", status_code=202)
async def inject_evidence(case_id: str, evidence: EvidenceInjection,
                          user: User = Depends(get_current_user)):
    """Mid-case evidence injection (Phase 6 HITL).
    For followup-on-concluded, use /followup instead — it triggers
    the AI to re-deliberate."""
    return {"accepted": True, "evidence": evidence.model_dump(),
            "note": "For mid-case injection use the WS pipeline. "
                    "For followup on a concluded case, use POST /followup."}


@router.post("/{case_id}/followup", status_code=202)
async def followup_case(
    case_id: str,
    req: FollowupRequest,
    user: User = Depends(get_current_user),
    x_drholmes_live_confirm: str | None = Header(default=None),
):
    """Add new findings to a concluded case → re-opens it for further
    deliberation. AI runs more rounds with the new evidence in context.
    Status flips concluded → running → concluded (with updated report)."""
    sm = get_sessionmaker()
    async with sm() as session:
        case = (await session.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
        if not case:
            raise HTTPException(404, "Case not found")
        if case.owner_id != user.owner_id and user.owner_id != "dev":
            raise HTTPException(403, "Not your case")
        if case.status == "finalized":
            raise HTTPException(409, "Case is finalized — cannot add findings.")
        if case.status not in ("concluded", "errored", "paused"):
            raise HTTPException(
                409,
                f"Cannot add findings while status={case.status}. "
                "Wait for AI to produce an assessment first.",
            )

        # Phase 6.5 budget check (only for live, not mock)
        if not case.mock_mode:
            from dr_holmes.safety import budget as _budget
            if not _budget.live_mode_enabled():
                raise HTTPException(403, "Live mode disabled.")
            if (x_drholmes_live_confirm or "").lower() != "yes":
                raise HTTPException(400, "Live followup requires X-DrHolmes-Live-Confirm: yes header.")
            remaining = _budget.remaining_session_budget()
            if remaining < 0.10:
                raise HTTPException(
                    402,
                    f"Insufficient session budget remaining (${remaining:.2f}). "
                    f"Followup cycle estimate ~$0.05-0.10."
                )

        # Snapshot current assessment into history before re-opening
        history = list(case.assessment_history or [])
        if case.final_report:
            history.append(case.final_report)
        case.assessment_history = history

        # Append new evidence to persistent evidence_log
        ev_log = list(case.evidence_log or [])
        for ev in req.new_evidence:
            ev_log.append(ev.model_dump())
        case.evidence_log = ev_log
        case.status = "running"
        case.followup_count = (case.followup_count or 0) + 1
        await session.commit()

    # Schedule the followup deliberation as a background task
    from dr_holmes.api.runner import schedule_followup
    schedule_followup(
        case_id=case_id,
        new_evidence=[e.model_dump() for e in req.new_evidence],
        question=req.question,
        target_agent=req.target_agent,
        owner_id=user.owner_id,
        is_mock=case.mock_mode,
        fixture_path=case.fixture_path,
    )
    return {"status": "running", "followup_count": case.followup_count}
