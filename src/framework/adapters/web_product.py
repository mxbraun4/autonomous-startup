"""Domain adapter for autonomous localhost web-product iteration."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from src.framework.adapters.base import BaseDomainAdapter
from src.framework.contracts import EvaluationResult, TaskSpec
from src.framework.learning.procedure_updater import ProcedureUpdateProposal
from src.framework.web_constants import (
    CAP_BROWSER_NAVIGATE,
    CAP_CODE_EDIT,
    CAP_RESTART_SERVICE,
    CAP_RUN_TESTS,
    DEFAULT_LOCALHOST_HOSTS,
    DEFAULT_MAX_EDITS_PER_CYCLE,
    POLICY_ALLOWED_EDIT_PATH_PATTERNS,
    POLICY_ALLOWED_EDIT_SEARCH_PATTERNS,
    POLICY_ALLOWED_LOCALHOST_HOSTS,
    POLICY_ALLOWED_LOCALHOST_PORTS,
    POLICY_ALLOWLIST,
    POLICY_DEDUPE_DELEGATED_OBJECTIVES,
    POLICY_LOOP_WINDOW_SIZE,
    POLICY_MAX_CHILDREN_PER_PARENT,
    POLICY_MAX_EDITS_PER_CYCLE,
    POLICY_MAX_IDENTICAL_TOOL_CALLS,
    POLICY_MAX_TOTAL_DELEGATED_TASKS,
    POLICY_REQUIRE_TESTS_BEFORE_RESTART,
    POLICY_TOOL_LOOP_MAX_REPEATS,
    POLICY_TOOL_LOOP_WINDOW,
    POLICY_WORKSPACE_ROOT,
    ROLE_WEB_EXPLORER,
    ROLE_WEB_IMPROVER,
    ROLE_WEB_VALIDATOR,
    WEB_CAPABILITIES,
)


def _rate(total: int, value: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, value / total))


def _task_status_name(status: Any) -> str:
    if status is None:
        return ""
    return getattr(status, "value", str(status)).lower()


def _normalize_edit_path_pattern(path_value: str, workspace_root: str) -> str:
    candidate = Path(str(path_value))
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(Path(workspace_root).resolve())
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


class WebProductAdapter(BaseDomainAdapter):
    """Adapter that scopes autonomy cycles to local web-product work."""

    def __init__(
        self,
        *,
        target_url: str,
        workspace_root: str,
        test_command: str = "pytest -q",
        restart_command: str = "",
        max_edits_per_cycle: int = DEFAULT_MAX_EDITS_PER_CYCLE,
        default_edit_instruction: Optional[Dict[str, Any]] = None,
        allowed_localhost_hosts: Optional[List[str]] = None,
        allowed_localhost_ports: Optional[List[int]] = None,
        allowed_edit_path_patterns: Optional[List[str]] = None,
        allowed_edit_search_patterns: Optional[List[str]] = None,
    ) -> None:
        self._target_url = target_url
        self._workspace_root = workspace_root
        self._test_command = test_command
        self._restart_command = restart_command
        self._max_edits_per_cycle = max(1, int(max_edits_per_cycle))
        self._default_edit_instruction = dict(default_edit_instruction or {})
        self._allowed_localhost_hosts = list(
            allowed_localhost_hosts or list(DEFAULT_LOCALHOST_HOSTS)
        )
        self._allowed_localhost_ports = list(allowed_localhost_ports or [])
        self._allowed_edit_path_patterns = list(allowed_edit_path_patterns or [])
        self._allowed_edit_search_patterns = list(allowed_edit_search_patterns or [])

        # If edit instructions are preconfigured, derive strict defaults unless provided.
        if not self._allowed_edit_path_patterns:
            default_path = self._default_edit_instruction.get("path")
            if default_path:
                self._allowed_edit_path_patterns = [
                    _normalize_edit_path_pattern(default_path, self._workspace_root)
                ]

        if not self._allowed_edit_search_patterns:
            default_search = self._default_edit_instruction.get("search")
            if default_search:
                escaped = re.escape(str(default_search))
                self._allowed_edit_search_patterns = [f"^{escaped}$"]

    def build_cycle_tasks(self, run_context: Any) -> List[TaskSpec]:
        cycle_id = int(getattr(run_context, "cycle_id", 0))
        run_id = getattr(run_context, "run_id", None)

        edit_input = dict(self._default_edit_instruction)
        if not edit_input:
            # By default, the improver does not write unless edit instructions are provided.
            edit_input = {"dry_run": True}

        restart_enabled = bool(self._restart_command)

        return [
            TaskSpec(
                run_id=run_id,
                cycle_id=cycle_id,
                task_id=f"web_explore_cycle_{cycle_id}",
                objective="Explore localhost product flow and capture page signals",
                agent_role=ROLE_WEB_EXPLORER,
                required_capabilities=[CAP_BROWSER_NAVIGATE],
                input_data={
                    "url": self._target_url,
                },
                priority=1,
            ),
            TaskSpec(
                run_id=run_id,
                cycle_id=cycle_id,
                task_id=f"web_improve_cycle_{cycle_id}",
                objective="Apply bounded code improvements in workspace",
                agent_role=ROLE_WEB_IMPROVER,
                required_capabilities=[CAP_CODE_EDIT],
                input_data=edit_input,
                constraints={POLICY_MAX_EDITS_PER_CYCLE: self._max_edits_per_cycle},
                priority=2,
            ),
            TaskSpec(
                run_id=run_id,
                cycle_id=cycle_id,
                task_id=f"web_validate_cycle_{cycle_id}",
                objective="Run tests and restart service only when tests pass",
                agent_role=ROLE_WEB_VALIDATOR,
                required_capabilities=[CAP_RUN_TESTS, CAP_RESTART_SERVICE],
                input_data={
                    "test_command": self._test_command,
                    "restart": restart_enabled,
                    "restart_command": self._restart_command,
                },
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
        success_rate = _rate(total, completed)

        task_results = getattr(cycle_outputs, "task_results", {}) or {}
        tests_passed = False
        restart_success = False
        edits_applied = 0
        policy_violations = 0

        for result in task_results.values():
            output = getattr(result, "output", {}) or {}
            if output.get("tests_passed") is True:
                tests_passed = True
            if output.get("restart_status") in {"success", "skipped"}:
                restart_success = True
            try:
                edits_applied += int(output.get("edits_applied", 0))
            except (TypeError, ValueError):
                pass

            status_name = _task_status_name(getattr(result, "task_status", None))
            error_category = _task_status_name(getattr(result, "error_category", None))
            if status_name == "failed" and error_category == "policy_violation":
                policy_violations += 1

        procedure_score = min(
            1.0,
            0.40 + (0.35 * success_rate) + (0.15 if tests_passed else 0.0) + (0.10 if restart_success else 0.0),
        )

        return {
            "run_id": getattr(run_context, "run_id", None),
            "cycle_id": int(getattr(run_context, "cycle_id", 0)),
            "total_tasks": total,
            "completed_count": completed,
            "failed_count": failed,
            "skipped_count": skipped,
            "success_rate": success_rate,
            "tests_passed": tests_passed,
            "restart_success": restart_success,
            "edits_applied": edits_applied,
            "policy_violations": policy_violations,
            "loop_denials": 0,
            "unhandled_exceptions": failed,
            "determinism_variance": 0.0,
            "procedure_score": procedure_score,
        }

    def compute_domain_metrics(self, simulation_outputs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tests_passed": bool(simulation_outputs.get("tests_passed", False)),
            "restart_success": bool(simulation_outputs.get("restart_success", False)),
            "edits_applied": int(simulation_outputs.get("edits_applied", 0)),
            "policy_violations": int(simulation_outputs.get("policy_violations", 0)),
            "loop_denials": int(simulation_outputs.get("loop_denials", 0)),
            "unhandled_exceptions": int(simulation_outputs.get("unhandled_exceptions", 0)),
            "determinism_variance": float(simulation_outputs.get("determinism_variance", 0.0)),
            "procedure_score": float(simulation_outputs.get("procedure_score", 0.0)),
        }

    def suggest_procedure_updates(
        self,
        evaluation_result: EvaluationResult,
    ) -> List[ProcedureUpdateProposal]:
        status = evaluation_result.overall_status
        action = evaluation_result.recommended_action

        if status == "pass":
            return [
                ProcedureUpdateProposal(
                    task_type="web_validation",
                    workflow={
                        "steps": ["navigate", "apply_patch", "run_tests", "restart_if_safe"]
                    },
                    score=0.80,
                    provenance="web_adapter:pass",
                    source_evidence={"evaluation_result_id": evaluation_result.entity_id},
                )
            ]

        if action in {"pause", "stop"}:
            return [
                ProcedureUpdateProposal(
                    task_type="web_recovery",
                    workflow={
                        "steps": [
                            "reduce_edit_scope",
                            "run_targeted_tests",
                            "require_manual_review_for_restart",
                        ]
                    },
                    score=0.55,
                    provenance=f"web_adapter:{status}/{action}",
                    source_evidence={"evaluation_result_id": evaluation_result.entity_id},
                )
            ]

        return []

    def get_domain_policies(self) -> Dict[str, Any]:
        policies: Dict[str, Any] = {
            POLICY_ALLOWLIST: list(WEB_CAPABILITIES),
            POLICY_MAX_CHILDREN_PER_PARENT: 3,
            POLICY_MAX_TOTAL_DELEGATED_TASKS: 8,
            POLICY_DEDUPE_DELEGATED_OBJECTIVES: True,
            POLICY_LOOP_WINDOW_SIZE: 20,
            POLICY_MAX_IDENTICAL_TOOL_CALLS: 4,
            POLICY_TOOL_LOOP_WINDOW: 8,
            POLICY_TOOL_LOOP_MAX_REPEATS: 3,
            POLICY_WORKSPACE_ROOT: self._workspace_root,
            POLICY_ALLOWED_LOCALHOST_HOSTS: list(self._allowed_localhost_hosts),
            POLICY_MAX_EDITS_PER_CYCLE: self._max_edits_per_cycle,
            POLICY_REQUIRE_TESTS_BEFORE_RESTART: True,
        }
        if self._allowed_localhost_ports:
            policies[POLICY_ALLOWED_LOCALHOST_PORTS] = list(
                self._allowed_localhost_ports
            )
        if self._allowed_edit_path_patterns:
            policies[POLICY_ALLOWED_EDIT_PATH_PATTERNS] = list(
                self._allowed_edit_path_patterns
            )
        if self._allowed_edit_search_patterns:
            policies[POLICY_ALLOWED_EDIT_SEARCH_PATTERNS] = list(
                self._allowed_edit_search_patterns
            )
        return policies
