"""DDXPlus sampling — stratified, difficulty-binned, reproducible.

DDXPlus columns:
  AGE  SEX  PATHOLOGY  DIFFERENTIAL_DIAGNOSIS  EVIDENCES  INITIAL_EVIDENCE
"""
from __future__ import annotations
import ast
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Literal, Optional, Iterable

from pydantic import BaseModel


_EVIDENCES_JSON = Path("./data/release_evidences.json")


class DDXPlusCase(BaseModel):
    case_id: str
    age: int
    sex: str
    pathology: str
    differential_diagnosis: list[str]    # ranked, from DDXPlus
    evidences: list[str]                  # raw E_XX codes
    evidence_labels: list[str]            # human-readable
    initial_evidence: str

    # Difficulty heuristics
    n_evidences: int
    differential_size: int

    # Computed at sample time
    age_bracket: str = ""

    def patient_presentation(self) -> dict:
        """Convert DDXPlus row → format expected by Phase 3/4."""
        return {
            "presenting_complaint": self.evidence_labels[0] if self.evidence_labels else "unspecified",
            "history": "; ".join(self.evidence_labels[1:]) if len(self.evidence_labels) > 1 else "",
            "vitals": {},
            "labs": {},
            "imaging": {},
            "medications": [],
            "additional_findings": [],
        }


def _short_label(question: str) -> str:
    q = (question or "").lower().strip().rstrip("?")
    for prefix in ("do you have ", "are you ", "have you ", "does your ",
                   "do you feel ", "is your ", "did you ", "is the "):
        if q.startswith(prefix):
            q = q[len(prefix):]; break
    return q[:80]


def _age_bracket(age: int) -> str:
    if age < 18:   return "<18"
    if age < 35:   return "18-34"
    if age < 55:   return "35-54"
    if age < 75:   return "55-74"
    return "75+"


def _parse_differential(raw) -> list[str]:
    """DDXPlus DIFFERENTIAL_DIAGNOSIS column may be a string-encoded list of [name, prob] pairs."""
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        try:
            items = ast.literal_eval(raw)
        except Exception:
            return []
    else:
        return []
    out = []
    for item in items:
        if isinstance(item, (list, tuple)) and item:
            out.append(str(item[0]))
        elif isinstance(item, str):
            out.append(item)
    return out


def _parse_evidences(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            return [str(x) for x in ast.literal_eval(raw)]
        except Exception:
            return []
    return []


class DDXPlusSampler:
    def __init__(
        self,
        split: Literal["test", "validate"] = "test",
        evidences_json_path: str | Path = _EVIDENCES_JSON,
    ):
        self.split = split
        self._evidence_labels: dict[str, str] = {}
        if Path(evidences_json_path).exists():
            data = json.loads(Path(evidences_json_path).read_text())
            for code, meta in data.items():
                self._evidence_labels[code] = _short_label(meta.get("question_en") or code)
        self._cases: list[DDXPlusCase] = []

    def load(self, max_cases: int | None = None) -> int:
        """Lazy-load DDXPlus from HuggingFace, parse, cache. Returns total count."""
        from datasets import load_dataset
        ds = load_dataset("aai530-group6/ddxplus", split=self.split)
        n = len(ds) if max_cases is None else min(len(ds), max_cases)
        self._cases = []
        for i, row in enumerate(ds):
            if i >= n:
                break
            ev_codes = _parse_evidences(row.get("EVIDENCES", "[]"))
            labels = []
            seen = set()
            for code in ev_codes:
                base = code.split("_@_")[0] if "_@_" in code else code
                if base in seen:
                    continue
                seen.add(base)
                labels.append(self._evidence_labels.get(base, base))
            differential = _parse_differential(row.get("DIFFERENTIAL_DIAGNOSIS"))
            case = DDXPlusCase(
                case_id=f"ddx_{self.split}_{i:07d}",
                age=int(row.get("AGE", 0) or 0),
                sex=str(row.get("SEX", "")),
                pathology=str(row.get("PATHOLOGY", "")),
                differential_diagnosis=differential,
                evidences=ev_codes,
                evidence_labels=labels,
                initial_evidence=str(row.get("INITIAL_EVIDENCE", "")),
                n_evidences=len(set(c.split("_@_")[0] for c in ev_codes)),
                differential_size=len(differential),
                age_bracket=_age_bracket(int(row.get("AGE", 0) or 0)),
            )
            self._cases.append(case)
        return len(self._cases)

    @property
    def cases(self) -> list[DDXPlusCase]:
        return self._cases

    # ── Sampling strategies ────────────────────────────────────────

    def stratified_sample(
        self,
        n: int,
        seed: int = 42,
        mode: Literal["proportional", "uniform_per_disease"] = "proportional",
    ) -> list[DDXPlusCase]:
        rng = random.Random(seed)
        if not self._cases:
            return []

        if mode == "proportional":
            # Match base rates: simple weighted random sample
            pop = list(self._cases)
            rng.shuffle(pop)
            return pop[:n]

        # uniform_per_disease: equal samples across pathologies
        by_dx: dict[str, list[DDXPlusCase]] = defaultdict(list)
        for c in self._cases:
            by_dx[c.pathology].append(c)
        per_dx = max(1, n // len(by_dx))
        out: list[DDXPlusCase] = []
        for dx, cases in by_dx.items():
            sampled = rng.sample(cases, min(per_dx, len(cases)))
            out.extend(sampled)
        rng.shuffle(out)
        return out[:n]

    def difficulty_sample(
        self,
        n: int,
        difficulty: Literal["easy", "medium", "hard"],
        seed: int = 42,
    ) -> list[DDXPlusCase]:
        rng = random.Random(seed)
        def bucket(c: DDXPlusCase) -> str:
            if c.n_evidences <= 6 and c.differential_size <= 3:    return "easy"
            if c.n_evidences > 15 or c.differential_size > 7:      return "hard"
            return "medium"
        pool = [c for c in self._cases if bucket(c) == difficulty]
        rng.shuffle(pool)
        return pool[:n]

    def fixed_seed_subset(self, n: int, seed: int = 42) -> list[DDXPlusCase]:
        rng = random.Random(seed)
        pool = list(self._cases)
        rng.shuffle(pool)
        return pool[:n]

    def stats(self) -> dict:
        if not self._cases:
            return {"n": 0}
        n_per_dx = defaultdict(int)
        n_per_age = defaultdict(int)
        for c in self._cases:
            n_per_dx[c.pathology] += 1
            n_per_age[c.age_bracket] += 1
        return {
            "n_total": len(self._cases),
            "n_diseases": len(n_per_dx),
            "per_disease": dict(n_per_dx),
            "per_age_bracket": dict(n_per_age),
        }
