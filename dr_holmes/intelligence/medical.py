"""
MedicalIntelligence — shared tool API used by all agents.

Backends:
  - Neo4j       → graph traversal (relationships, presentations, drug interactions)
  - BayesEngine → probability updates, information gain
  - ChromaDB    → vector search for case reports
  - Redis       → session working memory (read only here; written by graph nodes)
"""
from __future__ import annotations
import json
import math
from typing import Literal

from sqlalchemy.orm import Session

from dr_holmes.models.core import (
    Demographics, Evidence, Differential, Test, RedFlag,
    Interaction, CaseReport, Presentation, ResultInterpretation, Subgraph,
)
from dr_holmes.db.bayes import BayesEngine

# ── Red flag database (static, curated) ────────────────────────────────────
_RED_FLAGS: list[dict] = [
    {"diagnosis": "Pulmonary Embolism",  "urgency": "immediate",
     "keywords": ["dyspnea", "chest pain", "tachycardia", "hemoptysis", "hypoxia"],
     "action": "CT-PA now, anticoagulate if high probability"},
    {"diagnosis": "Meningitis",          "urgency": "immediate",
     "keywords": ["headache", "fever", "neck stiffness", "photophobia", "altered mental status"],
     "action": "LP within 1h, empiric antibiotics immediately"},
    {"diagnosis": "Aortic Dissection",   "urgency": "immediate",
     "keywords": ["chest pain", "back pain", "tearing", "hypertension", "pulse differential"],
     "action": "CT angiography stat, no anticoagulation"},
    {"diagnosis": "STEMI",               "urgency": "immediate",
     "keywords": ["chest pain", "diaphoresis", "radiation", "nausea", "ST elevation"],
     "action": "Cath lab activation, aspirin + heparin"},
    {"diagnosis": "Sepsis",              "urgency": "immediate",
     "keywords": ["fever", "tachycardia", "hypotension", "altered mental status", "infection"],
     "action": "Cultures, broad-spectrum antibiotics within 1h, 30mL/kg fluid"},
    {"diagnosis": "Ruptured AAA",        "urgency": "immediate",
     "keywords": ["back pain", "hypotension", "pulsatile mass", "abdominal pain"],
     "action": "Vascular surgery stat, type & cross"},
    {"diagnosis": "Stroke",              "urgency": "immediate",
     "keywords": ["facial droop", "arm weakness", "speech", "sudden headache", "vision loss"],
     "action": "CT head now, tPA if within window"},
    {"diagnosis": "Epiglottitis",        "urgency": "immediate",
     "keywords": ["stridor", "drooling", "dysphagia", "sore throat", "tripod position"],
     "action": "Airway first, lateral neck X-ray, ENT"},
]

# ── Minimal test reference ranges (fallback when no DB row) ────────────────
_TEST_REFS: dict[str, dict] = {
    "WBC":         {"range": "4.5-11.0 × 10³/μL", "high_means": "infection, inflammation, leukemia"},
    "Hemoglobin":  {"range": "M: 13.5-17.5 g/dL, F: 12.0-15.5 g/dL", "high_means": "polycythemia", "low_means": "anemia"},
    "Platelets":   {"range": "150-400 × 10³/μL"},
    "Creatinine":  {"range": "0.6-1.2 mg/dL", "high_means": "AKI, CKD"},
    "Troponin":    {"range": "<0.04 ng/mL", "high_means": "myocardial injury (ACS, myocarditis, PE)"},
    "D-dimer":     {"range": "<0.5 mg/L FEU", "high_means": "PE, DVT, DIC — low specificity"},
    "CRP":         {"range": "<1.0 mg/dL", "high_means": "inflammation, infection"},
    "ESR":         {"range": "M <15 mm/h, F <20 mm/h", "high_means": "inflammation, autoimmune, malignancy"},
    "ANA":         {"range": "negative", "high_means": "SLE, Sjogren, mixed CT disease"},
    "TSH":         {"range": "0.4-4.0 mIU/L"},
    "Lactate":     {"range": "<2.0 mmol/L", "high_means": "sepsis, ischemia, liver failure"},
    "Procalcitonin":{"range": "<0.1 ng/mL", "high_means": "bacterial sepsis"},
}


class MedicalIntelligence:
    def __init__(
        self,
        bayes_session: Session,
        neo4j_driver=None,
        chroma_collection=None,
        redis_client=None,
    ):
        self.bayes = BayesEngine(bayes_session)
        self._neo4j = neo4j_driver
        self._chroma = chroma_collection
        self._redis = redis_client

    # ── 1. get_differentials_for_symptoms ─────────────────────────────────
    def get_differentials_for_symptoms(
        self,
        symptoms: list[str],
        demographics: Demographics,
        bias: Literal["common", "rare", "autoimmune", "malignancy",
                      "infectious", "procedural", "neutral"] = "neutral",
        top_n: int = 10,
    ) -> list[Differential]:
        all_dx = self.bayes.get_priors()
        if not all_dx:
            return []

        # Update with each symptom as present evidence
        current = all_dx
        for sym in symptoms:
            ev = Evidence(type="symptom", name=sym, value="present", is_present=True)
            current = self.bayes.update(current, ev)

        # Apply bias reweighting
        current = _apply_bias(current, bias)

        return current[:top_n]

    # ── 2. get_discriminating_tests ───────────────────────────────────────
    def get_discriminating_tests(
        self,
        differentials: list[Differential],
        max_tests: int = 5,
    ) -> list[Test]:
        return self.bayes.top_discriminating_tests(differentials, max_tests)

    # ── 3. update_probabilities ───────────────────────────────────────────
    def update_probabilities(
        self,
        prior_dx: list[Differential],
        new_evidence: Evidence,
    ) -> list[Differential]:
        return self.bayes.update(prior_dx, new_evidence)

    # ── 4. get_typical_presentation ───────────────────────────────────────
    def get_typical_presentation(self, disease: str) -> Presentation:
        if self._neo4j:
            with self._neo4j.session() as s:
                result = s.run(
                    """
                    MATCH (d:Disease)
                    WHERE toLower(d.name) CONTAINS toLower($name)
                    OPTIONAL MATCH (d)-[:PRESENTS_WITH]->(sym:Symptom)
                    OPTIONAL MATCH (d)-[:RESEMBLES]->(mimic:Disease)
                    RETURN d.name AS disease,
                           collect(DISTINCT sym.name)[..10] AS symptoms,
                           collect(DISTINCT mimic.name)[..5] AS mimics
                    LIMIT 1
                    """,
                    name=disease,
                )
                row = result.single()
                if row:
                    return Presentation(
                        disease=row["disease"],
                        classic_features=row["symptoms"] or [],
                        mimics=row["mimics"] or [],
                    )
        return Presentation(disease=disease)

    # ── 5. get_drug_interactions ──────────────────────────────────────────
    def get_drug_interactions(self, medications: list[str]) -> list[Interaction]:
        if not self._neo4j or not medications:
            return []
        interactions = []
        with self._neo4j.session() as s:
            for i, drug_a in enumerate(medications):
                for drug_b in medications[i + 1:]:
                    result = s.run(
                        """
                        MATCH (a:Compound)-[r:INTERACTS_WITH]->(b:Compound)
                        WHERE toLower(a.name) CONTAINS toLower($a)
                          AND toLower(b.name) CONTAINS toLower($b)
                        RETURN a.name, b.name, r.severity, r.mechanism
                        LIMIT 1
                        """,
                        a=drug_a, b=drug_b,
                    )
                    row = result.single()
                    if row:
                        interactions.append(Interaction(
                            drug_a=row["a.name"],
                            drug_b=row["b.name"],
                            severity=row["r.severity"] or "moderate",
                            mechanism=row["r.mechanism"] or "",
                            clinical_effect="",
                        ))
        return interactions

    # ── 6. get_red_flags ──────────────────────────────────────────────────
    def get_red_flags(self, symptoms: list[str]) -> list[RedFlag]:
        lower_symptoms = [s.lower() for s in symptoms]
        flags = []
        for rf in _RED_FLAGS:
            matches = [kw for kw in rf["keywords"] if any(kw in s for s in lower_symptoms)]
            if matches:
                flags.append(RedFlag(
                    diagnosis=rf["diagnosis"],
                    urgency=rf["urgency"],
                    key_features=matches,
                    action=rf["action"],
                ))
        return flags

    # ── 7. search_case_reports ────────────────────────────────────────────
    def search_case_reports(self, query: str, top_k: int = 5) -> list[CaseReport]:
        if not self._chroma:
            return []
        results = self._chroma.query(query_texts=[query], n_results=top_k)
        docs = results.get("documents", [[]])[0]
        scores = results.get("distances", [[]])[0]
        reports = []
        for doc, score in zip(docs, scores):
            lines = doc.split("\n")
            title = lines[0][:80] if lines else query
            snippet = doc[:200]
            reports.append(CaseReport(
                title=title,
                snippet=snippet,
                source="medqa",
                similarity_score=round(1 - score, 3),
            ))
        return reports

    # ── 8. get_disease_relationships ──────────────────────────────────────
    def get_disease_relationships(self, disease: str) -> Subgraph:
        if not self._neo4j:
            return Subgraph(disease=disease)
        with self._neo4j.session() as s:
            result = s.run(
                """
                MATCH (d:Disease)
                WHERE toLower(d.name) CONTAINS toLower($name)
                OPTIONAL MATCH (d)-[:PRESENTS_WITH]->(sym:Symptom)
                OPTIONAL MATCH (d)-[:RESEMBLES]->(rel:Disease)
                OPTIONAL MATCH (d)-[:CAUSES]->(comp:Disease)
                OPTIONAL MATCH (d)-[:LOCALIZES_TO]->(anat:Anatomy)
                OPTIONAL MATCH (drug:Compound)-[:TREATS]->(d)
                RETURN d.name AS disease,
                       collect(DISTINCT sym.name)[..15]  AS symptoms,
                       collect(DISTINCT rel.name)[..8]   AS related,
                       collect(DISTINCT comp.name)[..8]  AS complications,
                       collect(DISTINCT anat.name)[..5]  AS anatomy,
                       collect(DISTINCT drug.name)[..8]  AS treatments
                LIMIT 1
                """,
                name=disease,
            )
            row = result.single()
            if row:
                return Subgraph(
                    disease=row["disease"],
                    symptoms=row["symptoms"] or [],
                    related_diseases=row["related"] or [],
                    complications=row["complications"] or [],
                    treatments=row["treatments"] or [],
                )
        return Subgraph(disease=disease)

    # ── 9. explain_result ─────────────────────────────────────────────────
    def explain_result(
        self,
        test: str,
        value: str,
        demographics: Demographics,
    ) -> ResultInterpretation:
        ref = _TEST_REFS.get(test, {})
        interp = ref.get("high_means", "") or ref.get("low_means", "") or "See reference range."
        return ResultInterpretation(
            test=test,
            value=value,
            interpretation=interp,
            reference_range=ref.get("range", "unknown"),
        )


# ── Bias reweighting helper ────────────────────────────────────────────────

_BIAS_KEYWORDS: dict[str, list[str]] = {
    "rare":        ["rare", "uncommon", "atypical", "unusual"],
    "autoimmune":  ["lupus", "sjogren", "vasculitis", "autoimmune", "sarcoid", "myositis", "ra"],
    "malignancy":  ["cancer", "lymphoma", "leukemia", "carcinoma", "malignant", "tumor", "neoplasm"],
    "infectious":  ["bacterial", "viral", "fungal", "sepsis", "pneumonia", "meningitis", "abscess"],
    "procedural":  ["surgical", "rupture", "obstruction", "torsion", "perforation", "ischemia"],
    "common":      [],  # no keyword boost; just damp rare ones
}

_BOOST = 2.0
_DAMP  = 0.5


def _apply_bias(dx: list[Differential], bias: str) -> list[Differential]:
    if bias == "neutral":
        return dx
    keywords = _BIAS_KEYWORDS.get(bias, [])
    result = []
    for d in dx:
        name_lower = d.disease.lower()
        if bias == "common":
            # damp anything with rare/uncommon in the name
            factor = _DAMP if any(kw in name_lower for kw in ["rare", "uncommon"]) else 1.0
        else:
            factor = _BOOST if any(kw in name_lower for kw in keywords) else 1.0
        new_log = d.log_prob + math.log(factor)
        result.append(d.model_copy(update={"log_prob": new_log}))

    # re-normalize
    import math as _math
    max_log = max(d.log_prob for d in result)
    exps = [_math.exp(d.log_prob - max_log) for d in result]
    total = sum(exps) or 1.0
    return sorted(
        [d.model_copy(update={"probability": e / total}) for d, e in zip(result, exps)],
        key=lambda d: d.probability, reverse=True,
    )
