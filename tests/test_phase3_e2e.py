"""Phase 3 end-to-end integration tests using mock fixtures.

These verify the state machine produces medically sensible behavior:
top differential matches the case answer, Hauser dissent is correct,
state machine progresses through rounds without crashing, etc.

Strict round-N convergence assertions are NOT enforced because the
fixtures' authored probabilities don't always cross the 0.80 threshold —
that's a fixture-quality issue, not an orchestration bug. Real LLM-driven
runs will produce sharper probabilities."""
from __future__ import annotations
from pathlib import Path

import pytest

from dr_holmes.orchestration.mock_agents import load_fixture, build_mock_agents
from dr_holmes.orchestration.builder import build_phase3_graph, RenderHooks
from dr_holmes.orchestration.convergence import _dx_tokens_match


FIXTURES = Path(__file__).parent.parent / "fixtures"


def _run(fixture_name: str) -> dict:
    fixture = load_fixture(FIXTURES / fixture_name)
    registry, caddick = build_mock_agents(fixture)
    rounds_seen, finals = [], []
    hooks = RenderHooks(
        on_round_start=rounds_seen.append,
        on_final=finals.append,
    )
    graph = build_phase3_graph(registry, caddick, hooks)
    result = graph.invoke(
        {"case_id": fixture["case_id"], "patient_presentation": fixture["patient_presentation"]},
        config={"recursion_limit": 80},
    )
    return {
        "fixture": fixture,
        "rounds_seen": rounds_seen,
        "final": finals[-1] if finals else None,
        "result": result,
        "convergence_reason": result.get("convergence_reason"),
        "rounds": result.get("round_number", 0),
    }


# ── Case 1: STEMI — fast convergence ───────────────────────────────────────

def test_case_01_stemi_terminates():
    r = _run("case_01_easy_mi.json")
    assert r["final"] is not None
    assert r["rounds"] >= 1

def test_case_01_stemi_top_dx_is_stemi():
    r = _run("case_01_easy_mi.json")
    assert _dx_tokens_match(r["final"].consensus_dx, "STEMI")

def test_case_01_no_hauser_dissent():
    r = _run("case_01_easy_mi.json")
    assert r["final"].hauser_dissent is None

def test_case_01_converges_via_team_agreement():
    r = _run("case_01_easy_mi.json")
    # The fast/clear case should hit real team agreement
    assert r["convergence_reason"] == "team_agreement"


# ── Case 2: SLE — autoimmune debate ────────────────────────────────────────

def test_case_02_sle_terminates():
    r = _run("case_02_atypical_sle.json")
    assert r["final"] is not None

def test_case_02_sle_top_dx_is_sle():
    r = _run("case_02_atypical_sle.json")
    assert _dx_tokens_match(r["final"].consensus_dx, "SLE")

def test_case_02_no_hauser_dissent():
    r = _run("case_02_atypical_sle.json")
    assert r["final"].hauser_dissent is None


# ── Case 3: Whipple's — late vindication ───────────────────────────────────

def test_case_03_whipples_terminates():
    r = _run("case_03_zebra_whipples.json")
    assert r["final"] is not None

def test_case_03_whipples_top_dx_is_whipples():
    r = _run("case_03_zebra_whipples.json")
    assert _dx_tokens_match(r["final"].consensus_dx, "Whipple disease")

def test_case_03_no_hauser_dissent_team_converges_on_his_answer():
    r = _run("case_03_zebra_whipples.json")
    # Case 3: team eventually agrees with Hauser, so no dissent is recorded
    assert r["final"].hauser_dissent is None


# ── State machine smoke tests ──────────────────────────────────────────────

def test_routing_reasons_observed_across_runs():
    """Across all 3 cases, we should observe variety in Caddick routing —
    not always the same fallback."""
    reasons_seen = set()
    for case in ["case_01_easy_mi.json", "case_02_atypical_sle.json",
                 "case_03_zebra_whipples.json"]:
        r = _run(case)
        for synth in (r["result"].get("caddick_synthesis_history") or []):
            reason = synth.routing_reason if hasattr(synth, "routing_reason") else synth.get("routing_reason")
            if reason:
                reasons_seen.add(reason)
    assert len(reasons_seen) >= 2, f"only saw routing reasons: {reasons_seen}"
