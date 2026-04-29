from __future__ import annotations
import math
from sqlalchemy.orm import Session
from dr_holmes.db.schema import DiseasePrior, SymptomLikelihood, TestCharacteristic
from dr_holmes.models.core import Differential, Evidence, Test

_EPSILON = 1e-9
_LR_CAP  = 50.0   # cap likelihood ratio to avoid Naive-Bayes overconfidence


def _lr(p_given_disease: float, p_given_other: float, is_present: bool) -> float:
    if is_present:
        raw = p_given_disease / max(p_given_other, _EPSILON)
    else:
        raw = (1 - p_given_disease) / max(1 - p_given_other, _EPSILON)
    return min(max(raw, 1.0 / _LR_CAP), _LR_CAP)


class BayesEngine:
    def __init__(self, session: Session):
        self.session = session

    def get_priors(self, disease_names: list[str] | None = None) -> list[Differential]:
        q = self.session.query(DiseasePrior)
        if disease_names:
            q = q.filter(DiseasePrior.disease_name.in_(disease_names))
        rows = q.all()
        if not rows:
            return []
        total = sum(r.prior_prob for r in rows) or 1.0
        result = []
        for r in rows:
            p = r.prior_prob / total
            result.append(Differential(
                disease=r.disease_name,
                icd10=r.icd10,
                probability=p,
                log_prob=math.log(max(p, _EPSILON)),
                proposed_by="bayes_prior",
            ))
        return sorted(result, key=lambda d: d.probability, reverse=True)

    def _resolve_symptom(self, disease: str, name: str) -> SymptomLikelihood | None:
        """Try exact match first, then substring (case-insensitive) on the
        full English question text. Agents may pass 'fever' but the DB has
        'a fever (either felt or measured with a thermometer)'."""
        row = (
            self.session.query(SymptomLikelihood)
            .filter_by(disease_name=disease, symptom_name=name)
            .first()
        )
        if row:
            return row
        # substring fallback — prefer shortest match (most general phrasing)
        like = f"%{name.lower()}%"
        rows = (
            self.session.query(SymptomLikelihood)
            .filter(SymptomLikelihood.disease_name == disease)
            .filter(SymptomLikelihood.symptom_name.ilike(like))
            .all()
        )
        if not rows:
            return None
        return min(rows, key=lambda r: len(r.symptom_name))

    def update(
        self,
        prior_dx: list[Differential],
        evidence: Evidence,
    ) -> list[Differential]:
        updated = []
        for dx in prior_dx:
            row = self._resolve_symptom(dx.disease, evidence.name)
            if row:
                lr = _lr(
                    row.p_symptom_given_disease,
                    row.p_symptom_given_other,
                    evidence.is_present,
                )
                new_log = dx.log_prob + math.log(max(lr, _EPSILON))
                rationale = (
                    f"{'[+]' if evidence.is_present else '[-]'} {evidence.name}={evidence.value} "
                    f"→ LR={lr:.2f}"
                )
            else:
                new_log = dx.log_prob
                rationale = dx.update_rationale

            updated.append(dx.model_copy(update={
                "log_prob": new_log,
                "update_rationale": rationale,
            }))

        # normalize
        max_log = max(d.log_prob for d in updated)
        exp_vals = [math.exp(d.log_prob - max_log) for d in updated]
        total = sum(exp_vals) or 1.0
        result = []
        for dx, ev in zip(updated, exp_vals):
            result.append(dx.model_copy(update={"probability": ev / total}))
        return sorted(result, key=lambda d: d.probability, reverse=True)

    def information_gain(self, test_name: str, current_dx: list[Differential]) -> float:
        """Expected entropy reduction (bits) from running this test."""
        def _entropy(probs: list[float]) -> float:
            return -sum(p * math.log2(max(p, _EPSILON)) for p in probs)

        probs = [d.probability for d in current_dx]
        h_prior = _entropy(probs)

        # Compute posterior under test+ and test-
        sens_specs = {}
        for dx in current_dx:
            row = (
                self.session.query(TestCharacteristic)
                .filter_by(test_name=test_name, disease_name=dx.disease)
                .first()
            )
            sens_specs[dx.disease] = (
                (row.sensitivity, row.specificity) if row else (0.5, 0.5)
            )

        # P(T+) = Σ P(T+|D) × P(D)
        p_pos = sum(
            sens_specs[d.disease][0] * d.probability for d in current_dx
        )
        p_neg = 1 - p_pos

        def _posterior(is_pos: bool) -> list[float]:
            raw = []
            for dx in current_dx:
                s, sp = sens_specs[dx.disease]
                lr = (s / max(1 - sp, _EPSILON)) if is_pos else ((1 - s) / max(sp, _EPSILON))
                raw.append(math.exp(dx.log_prob + math.log(max(lr, _EPSILON))))
            total = sum(raw) or 1.0
            return [v / total for v in raw]

        h_pos = _entropy(_posterior(True))
        h_neg = _entropy(_posterior(False))
        ig = h_prior - (p_pos * h_pos + p_neg * h_neg)
        return max(ig, 0.0)

    def top_discriminating_tests(
        self,
        current_dx: list[Differential],
        max_tests: int = 5,
    ) -> list[Test]:
        disease_names = [d.disease for d in current_dx]
        rows = (
            self.session.query(TestCharacteristic.test_name)
            .filter(TestCharacteristic.disease_name.in_(disease_names))
            .distinct()
            .all()
        )
        test_names = [r.test_name for r in rows]

        scored: list[tuple[float, str, float, float]] = []
        for tn in test_names:
            ig = self.information_gain(tn, current_dx)
            row = (
                self.session.query(TestCharacteristic)
                .filter_by(test_name=tn)
                .first()
            )
            scored.append((ig, tn, row.sensitivity if row else 0.5, row.specificity if row else 0.5))

        scored.sort(reverse=True)
        result = []
        for ig, tn, sens, spec in scored[:max_tests]:
            result.append(Test(
                name=tn,
                sensitivity=sens,
                specificity=spec,
                information_gain=round(ig, 4),
                rationale=f"IG={ig:.3f} bits vs current Ddx",
            ))
        return result
