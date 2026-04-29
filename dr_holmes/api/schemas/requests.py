"""REST request/response Pydantic schemas."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class CaseCreateRequest(BaseModel):
    patient_presentation: dict
    mock_mode: bool = False
    fixture_path: str | None = None
    max_rounds: int = 6


class CaseSummary(BaseModel):
    id: str
    owner_id: str
    status: str
    mock_mode: bool
    rounds_taken: int
    convergence_reason: str | None = None
    created_at: str
    concluded_at: str | None = None


class CaseDetail(CaseSummary):
    patient_presentation: dict
    final_report: dict | None = None


class EvidenceInjection(BaseModel):
    type: Literal["symptom", "lab", "imaging", "history", "physical_exam", "test_result"]
    name: str
    value: str
    is_present: bool = True


class AgentProfile(BaseModel):
    name: str
    specialty: str
    bias: str
    model_provider: str  # "openai", "xai", "anthropic"
    model_id: str
    description: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    components: dict[str, str]
    server_version: str
