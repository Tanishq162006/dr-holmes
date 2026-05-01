"""REST request/response Pydantic schemas."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class CaseCreateRequest(BaseModel):
    patient_presentation: dict
    mock_mode: bool = False
    fixture_path: str | None = None
    max_rounds: int = 6
    # Per-case toggle for Dr. Park (primary care, anti-zebra). Default False
    # because the n=20 ablation showed baseline beats with-Park on Top-1
    # (35% vs 30%) and ECE (0.17 vs 0.26). Park anchors on common dx and
    # actively pushes back on Hauser's zebra-hunting, which can reduce
    # rare-disease sensitivity. Opt in per case when you want the
    # primary-care anchor (e.g. clearly common presentations).
    # See docs/EVAL_SUMMARY.md.
    include_park: bool = False


class CaseSummary(BaseModel):
    id: str
    owner_id: str
    status: str
    mock_mode: bool
    include_park: bool = False
    rounds_taken: int
    convergence_reason: str | None = None
    followup_count: int = 0
    created_at: str
    concluded_at: str | None = None
    finalized_at: str | None = None


class CaseDetail(CaseSummary):
    patient_presentation: dict
    final_report: dict | None = None
    finalized_report: dict | None = None
    assessment_history: list[dict] = []
    evidence_log: list[dict] = []


class EvidenceInjection(BaseModel):
    type: Literal["symptom", "lab", "imaging", "history", "physical_exam", "test_result", "treatment_response"]
    name: str
    value: str
    is_present: bool = True


class FollowupRequest(BaseModel):
    """Add findings (and optional question) to a concluded case to re-open it."""
    new_evidence: list[EvidenceInjection] = []
    question: str | None = None
    target_agent: str | None = None   # for `question` if set


class AgentProfile(BaseModel):
    name: str
    specialty: str
    bias: str
    model_provider: str  # "openai" | "xai"
    model_id: str
    description: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    components: dict[str, str]
    server_version: str
