"""
Load DDXPlus into SQLite Bayesian tables.

Inputs:
  - aai530-group6/ddxplus on HuggingFace (1M+ patient simulations)
  - release_evidences.json  (E_XX → human-readable symptom)
  - release_conditions.json (49 pathologies metadata)

Outputs (SQLite):
  - disease_priors        : P(D)
  - symptom_likelihoods   : P(S|D), P(S|¬D)

Format quirk: EVIDENCES column is a STRING containing a Python-repr list,
so we use ast.literal_eval (not json.loads). Compound evidences look like
"E_55_@_V_167" — the prefix E_55 is the symptom; V_167 is the categorical value.
"""
import os
import sys
import json
import ast
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from datasets import load_dataset

load_dotenv()

DB_PATH = os.getenv("SQLITE_PATH", "./data/bayes.db")
EVIDENCES_JSON = "./data/release_evidences.json"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dr_holmes.db.schema import get_engine, get_session, DiseasePrior, SymptomLikelihood


def _short_label(question: str) -> str:
    """Convert 'Do you have a fever?' → 'fever' style short label."""
    q = question.lower().strip().rstrip("?")
    # strip common prefixes
    prefixes = [
        "do you have ", "are you ", "have you ", "does your ", "do you feel ",
        "is your ", "did you ", "have you experienced ", "do you ", "is the ",
    ]
    for p in prefixes:
        if q.startswith(p):
            q = q[len(p):]
            break
    # truncate
    if len(q) > 60:
        q = q[:57] + "..."
    return q


def main():
    if not Path(EVIDENCES_JSON).exists():
        print(f"Missing {EVIDENCES_JSON}.")
        print("Download with:")
        print("  curl -sL https://huggingface.co/datasets/aai530-group6/ddxplus/"
              "resolve/main/release_evidences.json -o ./data/release_evidences.json")
        sys.exit(1)

    ev_map_raw = json.load(open(EVIDENCES_JSON))
    # Build E_XX → short symptom label
    ev_label: dict[str, str] = {}
    for code, meta in ev_map_raw.items():
        ev_label[code] = _short_label(meta.get("question_en") or code)

    print(f"Loaded {len(ev_label)} evidence labels.")
    print("Loading DDXPlus train split (~1M rows)...")
    ds = load_dataset("aai530-group6/ddxplus", split="train")
    print(f"Got {len(ds)} rows.")

    disease_count: dict[str, int] = defaultdict(int)
    symptom_disease_count: dict[tuple[str, str], int] = defaultdict(int)
    symptom_total: dict[str, int] = defaultdict(int)
    total = 0
    parse_failures = 0

    for i, row in enumerate(ds):
        if i % 100000 == 0 and i > 0:
            print(f"  processed {i:,}/{len(ds):,}")

        pathology = row.get("PATHOLOGY", "")
        if not pathology:
            continue

        evidences_raw = row.get("EVIDENCES", "[]")
        if isinstance(evidences_raw, str):
            try:
                evidences = ast.literal_eval(evidences_raw)
            except Exception:
                parse_failures += 1
                continue
        else:
            evidences = list(evidences_raw)

        disease_count[pathology] += 1
        total += 1

        seen_symptoms_this_row: set[str] = set()
        for ev in evidences:
            ev_str = str(ev)
            # split on "_@_" — left side is the E_XX code
            code = ev_str.split("_@_")[0] if "_@_" in ev_str else ev_str
            symptom = ev_label.get(code, code)
            # avoid double-counting same symptom from multi-value compound evidences
            if symptom in seen_symptoms_this_row:
                continue
            seen_symptoms_this_row.add(symptom)
            symptom_disease_count[(symptom, pathology)] += 1
            symptom_total[symptom] += 1

    if parse_failures:
        print(f"  warning: {parse_failures} EVIDENCES rows failed to parse")

    print(f"\nTotals: {total:,} cases | {len(disease_count)} diseases "
          f"| {len(symptom_total)} unique symptoms | {len(symptom_disease_count)} (S,D) pairs")

    # ── Write to SQLite ────────────────────────────────────────────────────
    engine = get_engine(DB_PATH)
    session = get_session(engine)

    session.query(DiseasePrior).filter_by(source="ddxplus").delete()
    for disease, count in disease_count.items():
        session.add(DiseasePrior(
            disease_name=disease,
            prior_prob=count / total,
            source="ddxplus",
        ))
    session.commit()
    print(f"Wrote {len(disease_count)} disease priors.")

    session.query(SymptomLikelihood).filter_by(source="ddxplus").delete()
    rows_to_add = []
    for (symptom, disease), sd_count in symptom_disease_count.items():
        d_count = disease_count[disease]
        p_sd = sd_count / d_count if d_count > 0 else 0.0

        s_total = symptom_total[symptom]
        not_d_total = total - d_count
        s_not_d = max(s_total - sd_count, 0)
        p_s_not_d = s_not_d / not_d_total if not_d_total > 0 else 0.0

        rows_to_add.append(SymptomLikelihood(
            disease_name=disease,
            symptom_name=symptom,
            p_symptom_given_disease=p_sd,
            p_symptom_given_other=p_s_not_d,
            source="ddxplus",
        ))

    # batch insert
    BATCH = 1000
    for start in range(0, len(rows_to_add), BATCH):
        session.bulk_save_objects(rows_to_add[start:start + BATCH])
        session.commit()
    print(f"Wrote {len(rows_to_add)} symptom likelihood rows.")
    session.close()
    print("Done.")


if __name__ == "__main__":
    main()
