"""Tests for Layer G learning updaters."""

from src.framework.contracts import EvaluationResult, GateDecision, Procedure, ProcedureVersion
from src.framework.learning import (
    ProcedureUpdater,
)


def _evaluation_with_gates(gates: list[GateDecision]) -> EvaluationResult:
    return EvaluationResult(
        run_id="run_1",
        cycle_id=1,
        gates=gates,
        overall_status="warn",
        recommended_action="pause",
        summary="test",
    )


class _SyncStore:
    def __init__(self):
        self.saved_calls = []

    def proc_save(self, task_type, workflow, score=0.0, created_by="", provenance=""):
        self.saved_calls.append(
            {
                "task_type": task_type,
                "workflow": workflow,
                "score": score,
                "created_by": created_by,
                "provenance": provenance,
            }
        )
        return Procedure(
            task_type=task_type,
            current_version=1,
            versions=[
                ProcedureVersion(
                    version=1,
                    workflow=workflow,
                    score=score,
                    created_by=created_by,
                    provenance=provenance,
                    is_active=True,
                )
            ],
        )


def test_procedure_updater_propose_and_apply():
    store = _SyncStore()
    updater = ProcedureUpdater(store)

    evaluation = _evaluation_with_gates(
        [
            GateDecision(
                gate_name="learning",
                gate_status="warn",
                recommended_action="continue",
            )
        ]
    )
    proposal = updater.propose_update(
        task_type="outreach_campaign",
        workflow={"steps": ["segment", "personalize", "send"]},
        score=0.72,
        evaluation_result=evaluation,
        source_evidence={"delta": 0.01},
    )

    assert proposal.provenance.startswith("evaluation:")
    assert proposal.source_evidence["evaluation_status"] == "warn"
    assert proposal.source_evidence["delta"] == 0.01

    result = updater.apply_update(proposal)
    assert result.task_type == "outreach_campaign"
    assert len(store.saved_calls) == 1
    assert store.saved_calls[0]["created_by"] == "procedure_updater"
