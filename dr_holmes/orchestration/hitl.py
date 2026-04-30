"""Phase 6 — apply human interventions to a CaseState.

Pure function over (state, [interventions]) → (new_state, [emitted_events]).
No Redis, no DB. The runner handles persistence + audit + WS emission.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

from dr_holmes.schemas.responses import (
    Intervention, ScheduledTurn, EvidenceConflict, FinalReport,
)


def detect_evidence_conflict(
    evidence_log: list[dict], new_name: str, new_value: str,
) -> EvidenceConflict | None:
    """Same-name, different-value conflict (deliberately simple for v1)."""
    if not new_name:
        return None
    norm_name = new_name.strip().lower()
    for prev in evidence_log:
        prev_name = str(prev.get("name", "")).strip().lower()
        prev_val = str(prev.get("value", ""))
        if prev_name == norm_name and prev_val != str(new_value):
            return EvidenceConflict(
                name=new_name,
                prev_value=prev_val,
                new_value=str(new_value),
                prev_ts=str(prev.get("timestamp") or ""),
                new_ts=datetime.utcnow().isoformat(),
            )
    return None


def apply_interventions(
    state: dict, interventions: list[Intervention],
) -> tuple[dict, list[dict]]:
    """Apply ordered interventions to state. Returns (new_state, emitted_events).

    Each emitted event is a dict suitable for becoming a WSEvent payload.
    Application rules per architecture doc §3:
      pause           → status='paused'; remaining queue stays queued.
      resume          → status='running'.
      inject_evidence → append, conflict-check, schedule Caddick(ack).
      correct_agent   → append correction, schedule target(correction_response).
      question_agent  → schedule target(question_response).
      conclude_now    → forced_conclusion=True, status='concluded'. Always last.
    """
    s = dict(state)  # shallow clone; we treat lists immutably below

    evidence_log: list[dict] = list(s.get("evidence_log", []) or [])
    scheduled: list[dict] = list(s.get("scheduled_turns", []) or [])
    intervention_history: list[dict] = list(s.get("intervention_history", []) or [])
    conflicts: list[dict] = list(s.get("evidence_conflicts", []) or [])
    case_status = s.get("case_status", "running")
    forced_conclusion = bool(s.get("forced_conclusion", False))
    emitted: list[dict] = []
    paused_during_apply = False

    for intv in interventions:
        if paused_during_apply and intv.type != "resume":
            # Paused; keep remaining for next drain.
            break

        applied_ts = datetime.utcnow()

        try:
            if intv.type == "pause":
                case_status = "paused"
                paused_during_apply = True
                emitted.append({
                    "event_type": "case_paused",
                    "payload": {"intervention_id": intv.intervention_id},
                })

            elif intv.type == "resume":
                case_status = "running"
                paused_during_apply = False
                emitted.append({
                    "event_type": "case_resumed",
                    "payload": {"intervention_id": intv.intervention_id},
                })

            elif intv.type == "inject_evidence":
                p = intv.payload
                ev_name = str(p.get("name", "")).strip()
                ev_value = str(p.get("value", ""))
                if not ev_name:
                    raise ValueError("inject_evidence: name is required")
                conflict = detect_evidence_conflict(evidence_log, ev_name, ev_value)
                new_evidence = {
                    "type": p.get("type", "lab"),
                    "name": ev_name,
                    "value": ev_value,
                    "is_present": bool(p.get("is_present", True)),
                    "timestamp": applied_ts.isoformat(),
                    "intervention_id": intv.intervention_id,
                }
                evidence_log.append(new_evidence)
                if conflict is not None:
                    conflicts.append(conflict.model_dump())
                # Schedule Caddick to acknowledge + route
                scheduled.insert(0, ScheduledTurn(
                    agent="Caddick",
                    turn_type="evidence_acknowledgment",
                    intervention_id=intv.intervention_id,
                    payload={"evidence_name": ev_name, "evidence_value": ev_value},
                ).model_dump())
                emitted.append({
                    "event_type": "evidence_injected",
                    "payload": {
                        "intervention_id": intv.intervention_id,
                        "evidence": new_evidence,
                        "conflict": conflict.model_dump() if conflict else None,
                    },
                })

            elif intv.type == "question_agent":
                p = intv.payload
                target = str(p.get("target_agent", "")).strip()
                question = str(p.get("question", "")).strip()
                if not target or not question:
                    raise ValueError("question_agent: target_agent and question required")
                scheduled.insert(0, ScheduledTurn(
                    agent=target,
                    turn_type="question_response",
                    intervention_id=intv.intervention_id,
                    payload={"question": question},
                ).model_dump())
                emitted.append({
                    "event_type": "question_asked",
                    "payload": {
                        "intervention_id": intv.intervention_id,
                        "target": target, "question": question,
                    },
                })

            elif intv.type == "correct_agent":
                p = intv.payload
                target = str(p.get("target_agent", "")).strip()
                correction = str(p.get("correction", "")).strip()
                if not target or not correction:
                    raise ValueError("correct_agent: target_agent and correction required")
                # Append correction to evidence log so other agents see it
                conflict = detect_evidence_conflict(
                    evidence_log, f"correction:{target}", correction,
                )
                evidence_log.append({
                    "type": "correction",
                    "name": f"correction:{target}",
                    "value": correction,
                    "is_present": True,
                    "timestamp": applied_ts.isoformat(),
                    "intervention_id": intv.intervention_id,
                })
                if conflict is not None:
                    conflicts.append(conflict.model_dump())
                scheduled.insert(0, ScheduledTurn(
                    agent=target,
                    turn_type="correction_response",
                    intervention_id=intv.intervention_id,
                    payload={"correction": correction},
                ).model_dump())
                emitted.append({
                    "event_type": "correction_applied",
                    "payload": {
                        "intervention_id": intv.intervention_id,
                        "target": target,
                        "correction": correction,
                        "conflict": conflict.model_dump() if conflict else None,
                    },
                })

            elif intv.type == "conclude_now":
                forced_conclusion = True
                case_status = "concluded"
                # Drop any further interventions in queue
                emitted.append({
                    "event_type": "forced_conclusion",
                    "payload": {"intervention_id": intv.intervention_id},
                })
                intervention_history.append({
                    **intv.model_dump(mode="json"),
                    "applied": True,
                    "applied_at": applied_ts.isoformat(),
                })
                break

            else:
                raise ValueError(f"Unknown intervention type: {intv.type}")

            intervention_history.append({
                **intv.model_dump(mode="json"),
                "applied": True,
                "applied_at": applied_ts.isoformat(),
            })

        except Exception as e:
            emitted.append({
                "event_type": "intervention_failed",
                "payload": {
                    "intervention_id": intv.intervention_id,
                    "type": intv.type,
                    "reason": str(e),
                },
            })
            intervention_history.append({
                **intv.model_dump(mode="json"),
                "applied": False,
                "failure_reason": str(e),
                "applied_at": applied_ts.isoformat(),
            })

    s["evidence_log"] = evidence_log
    s["scheduled_turns"] = scheduled
    s["intervention_history"] = intervention_history
    s["evidence_conflicts"] = conflicts
    s["case_status"] = case_status
    s["forced_conclusion"] = forced_conclusion
    return s, emitted


def build_forced_conclusion_report(
    state: dict, case_id: str,
) -> FinalReport:
    """When the human forces conclude, build a FinalReport that captures
    the team consensus + any specialists who would have dissented."""
    from dr_holmes.orchestration.convergence import _dx_tokens_match, _normalize_dx
    from dr_holmes.schemas.responses import HauserDissent

    ddx = state.get("current_differentials", []) or []
    if ddx:
        top = ddx[0]
        consensus = top.disease if hasattr(top, "disease") else top.get("disease", "Unknown")
        confidence = float(top.probability if hasattr(top, "probability")
                           else top.get("probability", 0.0))
    else:
        consensus, confidence = "No conclusion", 0.0

    # Pre-conclusion dissents: any specialist whose top dx ≠ consensus
    dissents: list[HauserDissent] = []
    main_dissent: HauserDissent | None = None
    for agent, hist in (state.get("agent_responses") or {}).items():
        if not hist:
            continue
        last = hist[-1]
        diffs = (last.differentials if hasattr(last, "differentials")
                 else last.get("differentials", [])) or []
        if not diffs:
            continue
        agent_top = diffs[0]
        agent_dx = (agent_top.diagnosis if hasattr(agent_top, "diagnosis")
                    else agent_top.get("diagnosis", ""))
        agent_prob = float(agent_top.probability if hasattr(agent_top, "probability")
                           else agent_top.get("probability", 0.0))
        if not _dx_tokens_match(agent_dx, consensus):
            d = HauserDissent(
                hauser_dx=agent_dx,
                hauser_confidence=agent_prob,
                rationale=(agent_top.rationale if hasattr(agent_top, "rationale")
                           else agent_top.get("rationale", "")),
                recommended_test=None,
            )
            if agent == "Hauser":
                main_dissent = d
            else:
                dissents.append(d)

    # Recommended workup: union of agents' proposed tests
    tests: dict[str, dict] = {}
    for hist in (state.get("agent_responses") or {}).values():
        if not hist: continue
        last = hist[-1]
        tps = (last.proposed_tests if hasattr(last, "proposed_tests")
               else last.get("proposed_tests", [])) or []
        for tp in tps:
            tname = tp.test_name if hasattr(tp, "test_name") else tp.get("test_name", "")
            if tname and tname not in tests:
                tests[tname] = tp if hasattr(tp, "model_dump") else tp

    from dr_holmes.schemas.responses import TestProposal
    workup = []
    for t in tests.values():
        workup.append(t if hasattr(t, "model_dump") else TestProposal(**t))

    return FinalReport(
        case_id=case_id,
        consensus_dx=consensus,
        confidence=confidence,
        rounds_taken=state.get("round_number", 0),
        hauser_dissent=main_dissent,
        recommended_workup=workup,
        deliberation_summary="(forced conclusion by attending physician)",
        convergence_reason="forced_by_human",
        forced_by_human=True,
        pre_conclusion_dissents=dissents,
        interventions_summary=state.get("intervention_history", []) or [],
    )
