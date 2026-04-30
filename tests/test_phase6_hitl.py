"""Phase 6 — Human-in-the-loop interrupts.

All tests run in mock mode without LLM API keys, Redis, or Postgres.
The intervention queue uses an in-memory fallback and audit log writes
are best-effort (warnings only).
"""
from __future__ import annotations
import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio

# Force in-memory fallback by ensuring no Redis client init
os.environ.setdefault("DATABASE_URL", "")

from dr_holmes.api.interventions import (
    enqueue_intervention, drain_pending, mark_applied, _reset_for_tests,
    next_intervention_sequence,
)
from dr_holmes.schemas.responses import Intervention, AgentResponse, Differential
from dr_holmes.orchestration.hitl import (
    apply_interventions, detect_evidence_conflict, build_forced_conclusion_report,
)
from dr_holmes.orchestration.mock_agents import build_mock_agents, load_fixture
from dr_holmes.orchestration.builder import build_phase3_graph, RenderHooks


@pytest.fixture(autouse=True)
def reset_intervention_state():
    _reset_for_tests()
    yield
    _reset_for_tests()


# ── Unit: queue ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_and_drain():
    intv = Intervention(case_id="c1", type="pause",
                        sequence_number=await next_intervention_sequence("c1"))
    await enqueue_intervention(intv)
    pending = await drain_pending("c1")
    assert len(pending) == 1
    assert pending[0].type == "pause"
    # Drain again — empty
    assert await drain_pending("c1") == []


@pytest.mark.asyncio
async def test_idempotency_via_applied_ids():
    intv = Intervention(case_id="c2", type="resume",
                        sequence_number=await next_intervention_sequence("c2"))
    await enqueue_intervention(intv)
    pending = await drain_pending("c2")
    assert len(pending) == 1
    # Mark applied
    assert await mark_applied("c2", intv.intervention_id) is True
    # Second mark returns False
    assert await mark_applied("c2", intv.intervention_id) is False
    # Re-enqueueing the same intv: drain skips it (already applied)
    await enqueue_intervention(intv)
    assert await drain_pending("c2") == []


# ── Unit: apply_interventions pure function ─────────────────────────────────

def _intv(case_id: str, type_: str, payload: dict | None = None) -> Intervention:
    return Intervention(case_id=case_id, type=type_,  # type: ignore[arg-type]
                        payload=payload or {}, sequence_number=1)


def test_apply_pause_then_inject_pause_blocks_remaining():
    """When pause comes first, remaining interventions stay queued."""
    state = {"case_status": "running", "evidence_log": [], "scheduled_turns": []}
    interventions = [
        _intv("c", "pause"),
        _intv("c", "inject_evidence", {"name": "WBC", "value": "14"}),
    ]
    new_state, emitted = apply_interventions(state, interventions)
    assert new_state["case_status"] == "paused"
    # The inject was NOT applied — evidence_log still empty
    assert new_state["evidence_log"] == []
    # Only pause emitted
    types = [e["event_type"] for e in emitted]
    assert "case_paused" in types
    assert "evidence_injected" not in types


def test_apply_inject_evidence_schedules_caddick_acknowledgment():
    state = {"case_status": "running", "evidence_log": [], "scheduled_turns": []}
    interventions = [_intv("c", "inject_evidence", {
        "name": "anti-dsDNA", "value": "positive 1:160", "type": "lab",
    })]
    new_state, emitted = apply_interventions(state, interventions)
    assert any(e["name"] == "anti-dsDNA" for e in new_state["evidence_log"])
    sched = new_state["scheduled_turns"]
    assert len(sched) == 1
    assert sched[0]["agent"] == "Caddick"
    assert sched[0]["turn_type"] == "evidence_acknowledgment"
    assert any(e["event_type"] == "evidence_injected" for e in emitted)


def test_apply_question_agent_schedules_target():
    state = {"scheduled_turns": []}
    interventions = [_intv("c", "question_agent", {
        "target_agent": "Hauser", "question": "Are you sure about Whipple's?"
    })]
    new_state, emitted = apply_interventions(state, interventions)
    sched = new_state["scheduled_turns"]
    assert len(sched) == 1
    assert sched[0]["agent"] == "Hauser"
    assert sched[0]["turn_type"] == "question_response"
    assert sched[0]["payload"]["question"].startswith("Are you sure")


def test_apply_correct_agent_appends_evidence_and_schedules():
    state = {"evidence_log": [], "scheduled_turns": []}
    interventions = [_intv("c", "correct_agent", {
        "target_agent": "Forman", "correction": "ANCA is negative — you misread the panel.",
    })]
    new_state, emitted = apply_interventions(state, interventions)
    # Correction appended to evidence log
    assert any(e["type"] == "correction" for e in new_state["evidence_log"])
    sched = new_state["scheduled_turns"]
    assert sched[0]["agent"] == "Forman"
    assert sched[0]["turn_type"] == "correction_response"


def test_apply_conclude_now_sets_forced_conclusion():
    state = {"case_status": "running", "forced_conclusion": False}
    new_state, emitted = apply_interventions(state, [_intv("c", "conclude_now")])
    assert new_state["forced_conclusion"] is True
    assert new_state["case_status"] == "concluded"
    assert any(e["event_type"] == "forced_conclusion" for e in emitted)


def test_apply_conclude_now_drops_remaining():
    state = {"case_status": "running"}
    interventions = [
        _intv("c", "conclude_now"),
        _intv("c", "inject_evidence", {"name": "WBC", "value": "10"}),
    ]
    new_state, emitted = apply_interventions(state, interventions)
    assert new_state["forced_conclusion"] is True
    # Inject NOT applied
    assert new_state.get("evidence_log", []) == []


def test_evidence_conflict_detection():
    log_ = [{"name": "WBC", "value": "10", "timestamp": "2026-04-29T10:00:00"}]
    conflict = detect_evidence_conflict(log_, "WBC", "14")
    assert conflict is not None
    assert conflict.prev_value == "10"
    assert conflict.new_value == "14"

    no_conflict = detect_evidence_conflict(log_, "Hgb", "12")
    assert no_conflict is None

    same_value = detect_evidence_conflict(log_, "WBC", "10")
    assert same_value is None


def test_apply_inject_with_conflict_records_it():
    state = {
        "evidence_log": [{"name": "WBC", "value": "10", "timestamp": "t0"}],
        "evidence_conflicts": [],
        "scheduled_turns": [],
    }
    interventions = [_intv("c", "inject_evidence", {"name": "WBC", "value": "14"})]
    new_state, emitted = apply_interventions(state, interventions)
    assert len(new_state["evidence_conflicts"]) == 1
    assert any(e["event_type"] == "evidence_injected" and e["payload"]["conflict"]
               for e in emitted)


def test_validation_failure_emits_intervention_failed():
    state = {"evidence_log": [], "scheduled_turns": []}
    interventions = [_intv("c", "inject_evidence", {})]  # missing name
    new_state, emitted = apply_interventions(state, interventions)
    assert any(e["event_type"] == "intervention_failed" for e in emitted)
    # State unchanged on failure
    assert new_state["evidence_log"] == []


def test_pause_resume_cycle():
    state = {"case_status": "running"}
    s1, _ = apply_interventions(state, [_intv("c", "pause")])
    assert s1["case_status"] == "paused"
    s2, _ = apply_interventions(s1, [_intv("c", "resume")])
    assert s2["case_status"] == "running"


# ── Routing: scheduled_turn takes priority ──────────────────────────────────

def test_routing_consumes_scheduled_turn_first():
    from dr_holmes.orchestration.routing import select_next_speakers
    state = {
        "scheduled_turns": [{
            "agent": "Hauser", "turn_type": "question_response",
            "intervention_id": "abc", "payload": {"question": "?"},
        }],
        "agent_responses": {}, "active_challenges": [],
        "current_differentials": [], "last_speakers": [],
        "hauser_force_speak": False,
    }
    speakers, reason = select_next_speakers(state)
    assert speakers == ["Hauser"]
    assert reason == "scheduled_question_response"


# ── Forced conclusion report capture ────────────────────────────────────────

def test_forced_conclusion_captures_dissents():
    """When a specialist's top dx differs from team consensus,
    they appear in pre_conclusion_dissents."""
    state = {
        "case_id": "c", "round_number": 3,
        "current_differentials": [
            {"disease": "SLE", "probability": 0.55, "proposed_by": "Carmen, Forman"},
        ],
        "agent_responses": {
            "Hauser": [AgentResponse(
                agent_name="Hauser", turn_number=3, confidence=0.7,
                differentials=[Differential(
                    diagnosis="MCTD", probability=0.65,
                    rationale="The serology is mixed — not classic SLE.",
                )],
            ).model_dump()],
            "Forman": [AgentResponse(
                agent_name="Forman", turn_number=3, confidence=0.65,
                differentials=[Differential(diagnosis="SLE", probability=0.6)],
            ).model_dump()],
            "Wills": [AgentResponse(
                agent_name="Wills", turn_number=3, confidence=0.4,
                differentials=[Differential(
                    diagnosis="Lymphoma", probability=0.45,
                    rationale="rule out before SLE call",
                )],
            ).model_dump()],
        },
        "intervention_history": [],
    }
    report = build_forced_conclusion_report(state, "c")
    assert report.forced_by_human is True
    assert report.convergence_reason == "forced_by_human"
    assert report.consensus_dx == "SLE"
    # Hauser dissent goes into the main dissent slot
    assert report.hauser_dissent is not None
    assert "MCTD" in report.hauser_dissent.hauser_dx
    # Wills dissent in pre_conclusion_dissents
    pre_dissent_dxs = [d.hauser_dx for d in report.pre_conclusion_dissents]
    assert any("Lymphoma" in dx for dx in pre_dissent_dxs)


# ── E2E: mock fixture with human_script ─────────────────────────────────────

def test_e2e_mock_with_human_script(tmp_path):
    """Full graph run with scripted interventions injected via human_script.
    Uses the existing case_01 fixture and adds a synthetic script."""
    fixture = load_fixture(Path(__file__).parent.parent / "fixtures" / "case_01_easy_mi.json")
    # Inject a question intervention after round 1
    fixture = {**fixture, "human_script": [
        {"after_round": 1, "intervention": {
            "type": "question_agent",
            "payload": {"target_agent": "Hauser",
                        "question": "Are you ruling out aortic dissection?"},
        }},
    ]}
    registry, caddick = build_mock_agents(fixture)

    finals = []
    hooks = RenderHooks(on_final=finals.append)
    graph = build_phase3_graph(registry, caddick, hooks, enable_hitl=True)
    config = {"configurable": {"thread_id": "test_e2e_hitl"}, "recursion_limit": 80}

    state = {
        "case_id": "test_e2e_hitl",
        "patient_presentation": fixture.get("patient_presentation", {}),
    }
    iters = 0
    next_state: dict | None = state
    while iters < 30:
        iters += 1
        result = graph.invoke(next_state, config=config)
        next_state = None

        if result.get("final_report"):
            break

        # Drain in-memory pending after each interrupt
        current_round = int(result.get("round_number", 0))
        if current_round >= 1:
            # Manually queue the scripted intervention once
            for entry in fixture.get("human_script", []):
                if entry["after_round"] == 1 and not getattr(test_e2e_mock_with_human_script, "_done", False):
                    intv = Intervention(case_id="test_e2e_hitl",
                                        type=entry["intervention"]["type"],  # type: ignore[arg-type]
                                        payload=entry["intervention"]["payload"],
                                        sequence_number=1)
                    asyncio.get_event_loop().run_until_complete(enqueue_intervention(intv)) \
                        if asyncio.get_event_loop().is_running() is False else None
                    # Sync application via in-memory
                    pending = _drain_sync()
                    if pending:
                        snapshot = graph.get_state(config).values
                        new_state, _ = apply_interventions(snapshot, pending)
                        graph.update_state(config, new_state)
                    test_e2e_mock_with_human_script._done = True

    # Verify case completed and final report exists
    final_state = graph.get_state(config).values
    assert final_state.get("final_report") is not None


def _drain_sync():
    """Synchronous drain using in-memory queue (for tests)."""
    from dr_holmes.api.interventions import _mem_queues
    case_id = next(iter(_mem_queues), None)
    if not case_id:
        return []
    items = list(_mem_queues[case_id])
    _mem_queues[case_id].clear()
    out = []
    for raw in items:
        out.append(Intervention.model_validate_json(raw))
    return out
