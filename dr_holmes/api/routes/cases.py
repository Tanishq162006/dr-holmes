"""Case REST endpoints."""
from __future__ import annotations
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func

from dr_holmes.api.dependencies import get_current_user, User
from dr_holmes.api.persistence import (
    get_sessionmaker, Case, AuditLog, AgentResponseRecord,
)
from dr_holmes.api.schemas.requests import (
    CaseCreateRequest, CaseSummary, CaseDetail, EvidenceInjection,
)
from dr_holmes.api.runner import schedule_case
from dr_holmes.api.redis_client import set_status, get_status

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", response_model=CaseSummary, status_code=status.HTTP_201_CREATED)
async def create_case(req: CaseCreateRequest, user: User = Depends(get_current_user)):
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
        )
        session.add(case)
        await session.commit()

    await set_status(case_id, "pending", user.owner_id)
    schedule_case(case_id, req.mock_mode, req.fixture_path, user.owner_id)

    return CaseSummary(
        id=case_id, owner_id=user.owner_id, status="pending",
        mock_mode=req.mock_mode, rounds_taken=0,
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
            mock_mode=c.mock_mode, rounds_taken=c.rounds_taken,
            convergence_reason=c.convergence_reason,
            created_at=c.created_at.isoformat() if c.created_at else "",
            concluded_at=c.concluded_at.isoformat() if c.concluded_at else None,
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
        mock_mode=case.mock_mode, rounds_taken=case.rounds_taken,
        convergence_reason=case.convergence_reason,
        created_at=case.created_at.isoformat() if case.created_at else "",
        concluded_at=case.concluded_at.isoformat() if case.concluded_at else None,
        patient_presentation=case.patient_presentation,
        final_report=case.final_report,
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


@router.post("/{case_id}/conclude", status_code=202)
async def conclude_case(case_id: str, user: User = Depends(get_current_user)):
    # Phase 6 implements true conclusion — for now mark as such
    await set_status(case_id, "concluded", user.owner_id)
    return {"status": "concluded"}


@router.post("/{case_id}/evidence", status_code=202)
async def inject_evidence(case_id: str, evidence: EvidenceInjection,
                          user: User = Depends(get_current_user)):
    # Phase 6 wires this into the running graph; for now just log
    return {"accepted": True, "evidence": evidence.model_dump(),
            "note": "Live evidence injection wires up in Phase 6"}
