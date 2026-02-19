"""Startup/VC domain adapter implementation."""

from __future__ import annotations

from typing import Any, Dict, List

from src.framework.adapters.base import BaseDomainAdapter
from src.framework.contracts import EvaluationResult, TaskSpec
from src.framework.learning.procedure_updater import ProcedureUpdateProposal


def _normalized_success(total: int, completed: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, completed / total))


class StartupVCAdapter(BaseDomainAdapter):
    """Domain adapter for startup-to-VC matching and outreach."""

    def __init__(self, max_targets_per_cycle: int = 5) -> None:
        self._max_targets_per_cycle = max(1, int(max_targets_per_cycle))

    def build_cycle_tasks(self, run_context: Any) -> List[TaskSpec]:
        cycle_id = int(getattr(run_context, "cycle_id", 0))
        run_id = getattr(run_context, "run_id", None)
        return [
            TaskSpec(
                run_id=run_id,
                cycle_id=cycle_id,
                task_id=f"startup_vc_data_cycle_{cycle_id}",
                objective="Identify startup/VC data coverage gaps and refresh top gaps",
                agent_role="data_specialist",
                required_capabilities=["data_coverage_analysis", "database_write"],
                constraints={"max_targets": self._max_targets_per_cycle},
                priority=1,
            ),
            TaskSpec(
                run_id=run_id,
                cycle_id=cycle_id,
                task_id=f"startup_vc_matching_cycle_{cycle_id}",
                objective="Generate explainable startup-to-VC match shortlist",
                agent_role="matching_specialist",
                required_capabilities=["match_scoring", "explanation_generation"],
                constraints={"shortlist_size": self._max_targets_per_cycle},
                priority=2,
            ),
            TaskSpec(
                run_id=run_id,
                cycle_id=cycle_id,
                task_id=f"startup_vc_outreach_cycle_{cycle_id}",
                objective="Draft and prepare personalized outreach messages for top matches",
                agent_role="outreach_specialist",
                required_capabilities=["message_personalization", "campaign_tracking"],
                constraints={"message_count": self._max_targets_per_cycle},
                priority=3,
            ),
        ]

    def simulate_environment(
        self,
        cycle_outputs: Any,
        run_context: Any,
    ) -> Dict[str, Any]:
        total = int(getattr(cycle_outputs, "total_tasks", 0))
        completed = int(getattr(cycle_outputs, "completed_count", 0))
        failed = int(getattr(cycle_outputs, "failed_count", 0))
        skipped = int(getattr(cycle_outputs, "skipped_count", 0))

        success_rate = _normalized_success(total, completed)
        response_rate = min(0.60, 0.12 + (0.30 * success_rate))
        meeting_rate = min(response_rate, response_rate * 0.40)
        match_quality_score = min(1.0, 0.45 + (0.50 * success_rate))
        explanation_coverage = min(1.0, 0.40 + (0.55 * success_rate))
        outreach_personalization_score = min(1.0, 0.50 + (0.45 * success_rate))

        return {
            "run_id": getattr(run_context, "run_id", None),
            "cycle_id": int(getattr(run_context, "cycle_id", 0)),
            "measurement_source": "formula_simulation",
            "total_tasks": total,
            "completed_count": completed,
            "failed_count": failed,
            "skipped_count": skipped,
            "success_rate": success_rate,
            "response_rate": response_rate,
            "meeting_rate": meeting_rate,
            "match_quality_score": match_quality_score,
            "explanation_coverage": explanation_coverage,
            "outreach_personalization_score": outreach_personalization_score,
            "policy_violations": 0,
            "loop_denials": 0,
            "unhandled_exceptions": failed,
            "delegated_task_count": max(0, total - 3),
            "determinism_variance": 0.0,
            "procedure_score": match_quality_score,
        }

    def compute_domain_metrics(self, simulation_outputs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "response_rate": float(simulation_outputs.get("response_rate", 0.0)),
            "meeting_rate": float(simulation_outputs.get("meeting_rate", 0.0)),
            "match_quality_score": float(simulation_outputs.get("match_quality_score", 0.0)),
            "explanation_coverage": float(simulation_outputs.get("explanation_coverage", 0.0)),
            "outreach_personalization_score": float(
                simulation_outputs.get("outreach_personalization_score", 0.0)
            ),
            "policy_violations": int(simulation_outputs.get("policy_violations", 0)),
            "loop_denials": int(simulation_outputs.get("loop_denials", 0)),
            "unhandled_exceptions": int(
                simulation_outputs.get("unhandled_exceptions", 0)
            ),
            "delegated_task_count": int(
                simulation_outputs.get("delegated_task_count", 0)
            ),
            "determinism_variance": float(
                simulation_outputs.get("determinism_variance", 0.0)
            ),
            "procedure_score": float(simulation_outputs.get("procedure_score", 0.0)),
        }

    def suggest_procedure_updates(
        self,
        evaluation_result: EvaluationResult,
    ) -> List[ProcedureUpdateProposal]:
        updates: List[ProcedureUpdateProposal] = []
        status = evaluation_result.overall_status
        action = evaluation_result.recommended_action

        if status == "pass":
            updates.append(
                ProcedureUpdateProposal(
                    task_type="startup_vc_matching",
                    workflow={
                        "steps": [
                            "refresh_data",
                            "score_matches",
                            "generate_explanations",
                            "rank_shortlist",
                        ]
                    },
                    score=0.80,
                    provenance="adapter:pass",
                    source_evidence={"evaluation_result_id": evaluation_result.entity_id},
                )
            )
            return updates

        if action in {"pause", "stop"}:
            updates.append(
                ProcedureUpdateProposal(
                    task_type="startup_vc_outreach_guardrails",
                    workflow={
                        "steps": [
                            "tighten_target_filters",
                            "reduce_batch_size",
                            "increase_manual_review_flags",
                        ]
                    },
                    score=0.55,
                    provenance=f"adapter:{status}/{action}",
                    source_evidence={"evaluation_result_id": evaluation_result.entity_id},
                )
            )

        if action == "rollback":
            updates.append(
                ProcedureUpdateProposal(
                    task_type="startup_vc_matching",
                    workflow={
                        "steps": [
                            "use_previous_scoring_weights",
                            "freeze_new_features",
                            "collect_additional_evidence",
                        ]
                    },
                    score=0.40,
                    provenance="adapter:rollback",
                    source_evidence={"evaluation_result_id": evaluation_result.entity_id},
                )
            )

        return updates

    def get_domain_policies(self) -> Dict[str, Any]:
        return {
            "max_children_per_parent": 6,
            "max_total_delegated_tasks": 20,
            "dedupe_delegated_objectives": True,
            "loop_window_size": 20,
            "max_identical_tool_calls": 4,
            "tool_loop_window": 8,
            "tool_loop_max_repeats": 3,
        }

