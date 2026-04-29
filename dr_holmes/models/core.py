from __future__ import annotations
from typing import Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime


class PatientCase(BaseModel):
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    presenting_complaint: str
    history: str = ""
    vitals: dict[str, Any] = Field(default_factory=dict)
    labs: dict[str, Any] = Field(default_factory=dict)
    imaging: dict[str, Any] = Field(default_factory=dict)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    additional_findings: list[str] = Field(default_factory=list)


class Demographics(BaseModel):
    age: int = 0
    sex: Literal["M", "F", "other"] = "other"
    weight_kg: float | None = None


class Evidence(BaseModel):
    type: Literal["symptom", "lab", "imaging", "history", "physical_exam", "test_result"]
    name: str
    value: str
    is_present: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)


class Differential(BaseModel):
    disease: str
    icd10: str | None = None
    probability: float = Field(ge=0.0, le=1.0, default=0.0)
    log_prob: float = 0.0
    supporting_evidence: list[str] = Field(default_factory=list)
    against_evidence: list[str] = Field(default_factory=list)
    proposed_by: str = ""
    update_rationale: str = ""


class Test(BaseModel):
    name: str
    loinc_code: str | None = None
    sensitivity: float = 0.0
    specificity: float = 0.0
    information_gain: float = 0.0
    rationale: str = ""


class RedFlag(BaseModel):
    diagnosis: str
    urgency: Literal["immediate", "urgent", "monitor"]
    key_features: list[str] = Field(default_factory=list)
    action: str = ""


class Interaction(BaseModel):
    drug_a: str
    drug_b: str
    severity: Literal["mild", "moderate", "severe", "contraindicated"]
    mechanism: str = ""
    clinical_effect: str = ""


class CaseReport(BaseModel):
    title: str
    snippet: str
    disease: str = ""
    source: str = ""
    similarity_score: float = 0.0


class Presentation(BaseModel):
    disease: str
    classic_features: list[str] = Field(default_factory=list)
    demographics_summary: str = ""
    time_course: str = ""
    key_tests: list[str] = Field(default_factory=list)
    mimics: list[str] = Field(default_factory=list)


class ResultInterpretation(BaseModel):
    test: str
    value: str
    interpretation: str = ""
    sensitivity: float | None = None
    specificity: float | None = None
    lr_positive: float | None = None
    lr_negative: float | None = None
    common_false_positives: list[str] = Field(default_factory=list)
    common_false_negatives: list[str] = Field(default_factory=list)
    reference_range: str = ""


class Subgraph(BaseModel):
    disease: str
    related_diseases: list[str] = Field(default_factory=list)
    complications: list[str] = Field(default_factory=list)
    mimics: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    treatments: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool_name: str
    inputs: dict[str, Any]
    output: str = ""
    agent_id: str = ""


class AgentMessage(BaseModel):
    agent_id: str
    agent_name: str
    role: Literal["agent", "human", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    thinking: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class DiagnosticState(BaseModel):
    case: PatientCase
    messages: list[AgentMessage] = Field(default_factory=list)
    differentials: list[Differential] = Field(default_factory=list)
    current_speaker: str = ""
    round_number: int = 0
    human_injection: str = ""
    concluded: bool = False
