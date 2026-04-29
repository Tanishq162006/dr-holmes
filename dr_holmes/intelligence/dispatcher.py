"""
ToolDispatcher — routes agent tool calls to MedicalIntelligence methods.

OpenAI tool-call format (works for both Grok and GPT-4o).
"""
from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel

from dr_holmes.models.core import Demographics, Evidence, Differential
from dr_holmes.intelligence.medical import MedicalIntelligence


# ── Input models (one per tool) ────────────────────────────────────────────

class GetDifferentialsInput(BaseModel):
    symptoms: list[str]
    age: int = 0
    sex: str = "other"
    bias: str = "neutral"
    top_n: int = 10


class GetDiscriminatingTestsInput(BaseModel):
    disease_names: list[str]
    max_tests: int = 5


class UpdateProbabilitiesInput(BaseModel):
    disease_names: list[str]
    evidence_type: str
    evidence_name: str
    evidence_value: str
    is_present: bool = True


class GetTypicalPresentationInput(BaseModel):
    disease: str


class GetDrugInteractionsInput(BaseModel):
    medications: list[str]


class GetRedFlagsInput(BaseModel):
    symptoms: list[str]


class SearchCaseReportsInput(BaseModel):
    query: str
    top_k: int = 5


class GetDiseaseRelationshipsInput(BaseModel):
    disease: str


class ExplainResultInput(BaseModel):
    test: str
    value: str
    age: int = 0
    sex: str = "other"


# ── Registry ───────────────────────────────────────────────────────────────

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_differentials_for_symptoms",
        "description": (
            "Returns a ranked differential diagnosis list given symptoms. "
            "Use the 'bias' parameter to weight toward your specialty: "
            "'rare' (Hauser), 'common' (Forman), 'autoimmune', 'malignancy', "
            "'infectious', 'procedural', or 'neutral'."
        ),
        "input_model": GetDifferentialsInput,
    },
    {
        "name": "get_discriminating_tests",
        "description": (
            "Given a list of diseases in the differential, returns the tests "
            "with highest information gain — the ones that best discriminate "
            "between the competing diagnoses."
        ),
        "input_model": GetDiscriminatingTestsInput,
    },
    {
        "name": "update_probabilities",
        "description": (
            "Bayesian update: takes current diseases + a new finding (lab, "
            "symptom, test result) and returns updated posterior probabilities. "
            "Call this every time new evidence arrives."
        ),
        "input_model": UpdateProbabilitiesInput,
    },
    {
        "name": "get_typical_presentation",
        "description": "Classic features, demographics, time course, and mimics for a disease.",
        "input_model": GetTypicalPresentationInput,
    },
    {
        "name": "get_drug_interactions",
        "description": "Check drug-drug interactions and adverse effects for a patient's medication list.",
        "input_model": GetDrugInteractionsInput,
    },
    {
        "name": "get_red_flags",
        "description": (
            "Checks for don't-miss, immediately dangerous diagnoses "
            "(PE, MI, sepsis, AAA, meningitis, stroke, etc.) given symptoms."
        ),
        "input_model": GetRedFlagsInput,
    },
    {
        "name": "search_case_reports",
        "description": (
            "Vector search over medical literature for similar cases. "
            "Use for zebra hunting and unusual presentations."
        ),
        "input_model": SearchCaseReportsInput,
    },
    {
        "name": "get_disease_relationships",
        "description": (
            "Knowledge graph query: returns related conditions, complications, "
            "mimics, symptoms, and treatments for a disease."
        ),
        "input_model": GetDiseaseRelationshipsInput,
    },
    {
        "name": "explain_result",
        "description": (
            "Interpret a lab or test result in context: reference range, "
            "sensitivity/specificity, common false positives/negatives."
        ),
        "input_model": ExplainResultInput,
    },
]


class ToolDispatcher:
    def __init__(self, mi: MedicalIntelligence, active_differentials: list[Differential] | None = None):
        self.mi = mi
        self._active_dx: list[Differential] = active_differentials or []

    def update_differentials(self, dx: list[Differential]):
        self._active_dx = dx

    def tool_schemas(self) -> list[dict]:
        schemas = []
        for tool in _TOOLS:
            model: type[BaseModel] = tool["input_model"]
            schema = model.model_json_schema()
            schema.pop("title", None)
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": schema,
                },
            })
        return schemas

    def dispatch(self, tool_name: str, args: dict) -> str:
        try:
            result = self._route(tool_name, args)
            if isinstance(result, list):
                return json.dumps([r.model_dump() if hasattr(r, "model_dump") else r for r in result])
            if hasattr(result, "model_dump"):
                return json.dumps(result.model_dump())
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _route(self, tool_name: str, args: dict):
        mi = self.mi

        if tool_name == "get_differentials_for_symptoms":
            inp = GetDifferentialsInput(**args)
            dem = Demographics(age=inp.age, sex=inp.sex)
            result = mi.get_differentials_for_symptoms(inp.symptoms, dem, inp.bias, inp.top_n)
            self._active_dx = result
            return result

        if tool_name == "get_discriminating_tests":
            inp = GetDiscriminatingTestsInput(**args)
            dx = [d for d in self._active_dx if d.disease in inp.disease_names] or self._active_dx
            return mi.get_discriminating_tests(dx, inp.max_tests)

        if tool_name == "update_probabilities":
            inp = UpdateProbabilitiesInput(**args)
            prior = [d for d in self._active_dx if d.disease in inp.disease_names] or self._active_dx
            ev = Evidence(
                type=inp.evidence_type,
                name=inp.evidence_name,
                value=inp.evidence_value,
                is_present=inp.is_present,
            )
            result = mi.update_probabilities(prior, ev)
            self._active_dx = result
            return result

        if tool_name == "get_typical_presentation":
            inp = GetTypicalPresentationInput(**args)
            return mi.get_typical_presentation(inp.disease)

        if tool_name == "get_drug_interactions":
            inp = GetDrugInteractionsInput(**args)
            return mi.get_drug_interactions(inp.medications)

        if tool_name == "get_red_flags":
            inp = GetRedFlagsInput(**args)
            return mi.get_red_flags(inp.symptoms)

        if tool_name == "search_case_reports":
            inp = SearchCaseReportsInput(**args)
            return mi.search_case_reports(inp.query, inp.top_k)

        if tool_name == "get_disease_relationships":
            inp = GetDiseaseRelationshipsInput(**args)
            return mi.get_disease_relationships(inp.disease)

        if tool_name == "explain_result":
            inp = ExplainResultInput(**args)
            dem = Demographics(age=inp.age, sex=inp.sex)
            return mi.explain_result(inp.test, inp.value, dem)

        raise ValueError(f"Unknown tool: {tool_name}")
