"""Startup/VC domain adapter implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.framework.adapters.base import BaseDomainAdapter
from src.framework.contracts import EvaluationResult, TaskSpec
from src.framework.learning.procedure_updater import ProcedureUpdateProposal
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _normalized_success(total: int, completed: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, completed / total))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result


def _clamp01(value: Any) -> float:
    return max(0.0, min(1.0, _safe_float(value, default=0.0)))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


class StartupVCAdapter(BaseDomainAdapter):
    """Domain adapter for startup-to-VC matching and outreach."""

    def __init__(
        self,
        max_targets_per_cycle: int = 5,
        *,
        workspace_root: Optional[str] = None,
        workspace_server_port: int = 0,
        # Legacy kwargs accepted but ignored for backwards compatibility
        **_kwargs: Any,
    ) -> None:
        self._max_targets_per_cycle = max(1, int(max_targets_per_cycle))

        # Workspace mode
        self._workspace_root: Optional[str] = (
            str(workspace_root).strip() if workspace_root else None
        )
        self._workspace_server_port = int(workspace_server_port)
        self._workspace_server: Any = None
        self._http_check_results: Optional[Dict[str, Any]] = None

        if self._workspace_root:
            from src.workspace_tools.server import WorkspaceServer

            self._workspace_server = WorkspaceServer(
                self._workspace_root,
                port=self._workspace_server_port,
            )

    def build_cycle_tasks(self, run_context: Any) -> List[TaskSpec]:
        cycle_id = int(getattr(run_context, "cycle_id", 0))
        run_id = getattr(run_context, "run_id", None)
        tasks: List[TaskSpec] = []

        if self._workspace_root:
            input_data: Dict[str, Any] = {"cycle_id": cycle_id}
            if self._http_check_results:
                input_data["previous_http_checks"] = self._http_check_results
            tasks.append(
                TaskSpec(
                    run_id=run_id,
                    cycle_id=cycle_id,
                    task_id=f"startup_vc_coordinator_cycle_{cycle_id}",
                    objective="Analyze feedback, formulate vision, delegate to agents",
                    agent_role="coordinator",
                    required_capabilities=["coordination"],
                    constraints={},
                    priority=0,
                    input_data=input_data,
                ),
            )
        else:
            tasks.append(
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
            )
        return tasks

    def simulate_environment(
        self,
        cycle_outputs: Any,
        run_context: Any,
    ) -> Dict[str, Any]:
        base_metrics = self._extract_base_metrics(cycle_outputs, run_context)

        # Run HTTP checks if workspace is active
        if self._workspace_root and self._workspace_server is not None:
            try:
                base_url = self._workspace_server.start()  # idempotent
                from src.simulation.http_checks import WorkspaceHTTPChecker

                checker = WorkspaceHTTPChecker(base_url)
                self._http_check_results = checker.run_all_checks(
                    workspace_root=str(self._workspace_root)
                )
                base_metrics["http_checks"] = self._http_check_results
            except Exception as exc:
                logger.warning("Workspace HTTP checks failed: %s", exc)
                self._http_check_results = None

        success_rate = _clamp01(base_metrics.get("success_rate", 0.0))
        return {
            **base_metrics,
            "measurement_source": "http_checks",
            "procedure_score": success_rate,
            "policy_violations": 0,
            "loop_denials": 0,
            "unhandled_exceptions": _safe_int(base_metrics.get("failed_count"), 0),
            "delegated_task_count": max(0, _safe_int(base_metrics.get("total_tasks"), 0) - 2),
            "determinism_variance": 0.0,
        }

    @staticmethod
    def _extract_base_metrics(
        cycle_outputs: Any,
        run_context: Any,
    ) -> Dict[str, Any]:
        total = int(getattr(cycle_outputs, "total_tasks", 0))
        completed = int(getattr(cycle_outputs, "completed_count", 0))
        failed = int(getattr(cycle_outputs, "failed_count", 0))
        skipped = int(getattr(cycle_outputs, "skipped_count", 0))
        success_rate = _normalized_success(total, completed)
        return {
            "run_id": str(getattr(run_context, "run_id", "") or ""),
            "cycle_id": int(getattr(run_context, "cycle_id", 0)),
            "total_tasks": total,
            "completed_count": completed,
            "failed_count": failed,
            "skipped_count": skipped,
            "success_rate": success_rate,
        }

    def compute_domain_metrics(self, simulation_outputs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "procedure_score": float(simulation_outputs.get("procedure_score", 0.0)),
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
            "measurement_source": str(
                simulation_outputs.get("measurement_source", "unknown")
            ),
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

        return updates

    def stop_workspace_server(self) -> None:
        """Stop the workspace HTTP server."""
        if self._workspace_server is not None:
            try:
                self._workspace_server.stop()
            except Exception as exc:
                logger.warning("Workspace server stop failed: %s", exc)

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
