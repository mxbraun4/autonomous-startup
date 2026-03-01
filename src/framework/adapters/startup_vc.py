"""Startup/VC domain adapter implementation."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.framework.adapters.base import BaseDomainAdapter
from src.framework.contracts import EvaluationResult, TaskSpec
from src.framework.learning.procedure_updater import ProcedureUpdateProposal
from src.simulation.customer_environment import (
    build_customer_environment_input,
    run_customer_environment,
)
from src.simulation.customer_event_instrumentation import validate_product_events
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


def _stable_cycle_seed(base_seed: int, run_id: str, cycle_id: int) -> int:
    raw = f"{int(base_seed)}|{run_id}|{int(cycle_id)}".encode("utf-8")
    digest = sha256(raw).hexdigest()
    return int(digest[:8], 16)


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
        use_customer_simulation: bool = True,
        customer_seed_path: Optional[str] = None,
        include_visitors: bool = False,
        product_events_path: Optional[str] = None,
        product_surface_only: bool = False,
        simulation_seed: int = 42,
        match_calibration_path: Optional[str] = None,
        match_calibration_min_samples: int = 20,
        workspace_root: Optional[str] = None,
        workspace_server_port: int = 0,
    ) -> None:
        self._max_targets_per_cycle = max(1, int(max_targets_per_cycle))
        self._use_customer_simulation = bool(use_customer_simulation)
        self._customer_seed_path = (
            str(customer_seed_path).strip() if customer_seed_path else None
        )
        self._include_visitors = bool(include_visitors)
        self._product_events_path = (
            str(product_events_path).strip() if product_events_path else None
        )
        self._product_surface_only = bool(product_surface_only)
        self._simulation_seed = int(simulation_seed)
        self._match_calibration_path = (
            str(match_calibration_path).strip()
            if match_calibration_path
            else None
        )
        self._match_calibration_min_samples = max(
            1, int(match_calibration_min_samples)
        )
        self._product_events_loaded = False
        self._cached_product_events: Optional[List[Dict[str, Any]]] = None

        # Workspace mode
        self._workspace_root: Optional[str] = (
            str(workspace_root).strip() if workspace_root else None
        )
        self._workspace_server_port = int(workspace_server_port)
        self._workspace_server: Any = None
        self._workspace_versioning: Any = None
        self._http_check_results: Optional[Dict[str, Any]] = None
        self._previous_simulation_results: Optional[Dict[str, Any]] = None

        if self._workspace_root:
            from src.workspace.server import WorkspaceServer
            from src.workspace.versioning import WorkspaceVersioning

            self._workspace_server = WorkspaceServer(
                self._workspace_root,
                port=self._workspace_server_port,
            )
            self._workspace_versioning = WorkspaceVersioning(self._workspace_root)

    def build_cycle_tasks(self, run_context: Any) -> List[TaskSpec]:
        cycle_id = int(getattr(run_context, "cycle_id", 0))
        run_id = getattr(run_context, "run_id", None)
        tasks: List[TaskSpec] = []

        if self._workspace_root:
            # Coordinator-driven flow: emit ONE coordinator task.
            # The coordinator analyses feedback and delegates to whichever
            # agents it decides are needed via delegated_tasks.
            input_data: Dict[str, Any] = {"cycle_id": cycle_id}
            if self._http_check_results:
                input_data["previous_http_checks"] = self._http_check_results
            if self._previous_simulation_results:
                customer_metrics = self._previous_simulation_results.get("customer_metrics")
                if customer_metrics:
                    input_data["customer_metrics"] = customer_metrics
                input_data["previous_results"] = {
                    k: v
                    for k, v in self._previous_simulation_results.items()
                    if k not in ("customer_metrics", "customer_diagnostics")
                }
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
            # Non-workspace flow: emit the 2 hardcoded specialist tasks.
            tasks.extend([
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
            ])
        return tasks
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
        ]

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
                self._http_check_results = checker.run_all_checks()
                base_metrics["http_checks"] = self._http_check_results
            except Exception as exc:
                logger.warning("Workspace HTTP checks failed: %s", exc)
                self._http_check_results = None

        if not self._use_customer_simulation:
            result = self._formula_simulation(base_metrics)
            self._previous_simulation_results = result
            return result

        try:
            environment_output = run_customer_environment(
                build_customer_environment_input(
                    run_id=f"{base_metrics['run_id']}_customer",
                    iteration=max(1, base_metrics["cycle_id"]),
                    seed=_stable_cycle_seed(
                        self._simulation_seed,
                        str(base_metrics["run_id"]),
                        base_metrics["cycle_id"],
                    ),
                    params=self._customer_params(
                        success_rate=base_metrics["success_rate"]
                    ),
                    seed_path=self._customer_seed_path,
                    include_visitors=self._include_visitors,
                    product_events=self._load_product_events(),
                    product_surface_only=self._product_surface_only,
                    match_calibration_path=self._match_calibration_path,
                    match_calibration_min_samples=self._match_calibration_min_samples,
                )
            )

            customer_metrics = dict(environment_output.get("metrics") or {})
            diagnostics = dict(environment_output.get("diagnostics") or {})
            validation_errors = diagnostics.get("input_validation_errors") or []
            if not isinstance(validation_errors, list):
                validation_errors = [str(validation_errors)]

            mapped = self._map_customer_metrics(customer_metrics)
            response_rate = mapped["response_rate"]
            meeting_rate = min(response_rate, mapped["meeting_rate"])
            procedure_score = max(
                0.0,
                min(
                    1.0,
                    (
                        (0.35 * mapped["match_quality_score"])
                        + (0.20 * mapped["explanation_coverage"])
                        + (0.20 * mapped["outreach_personalization_score"])
                        + (0.15 * response_rate)
                        + (0.10 * meeting_rate)
                    ),
                ),
            )

            result = {
                **base_metrics,
                "measurement_source": "customer_simulation",
                "response_rate": response_rate,
                "meeting_rate": meeting_rate,
                "match_quality_score": mapped["match_quality_score"],
                "explanation_coverage": mapped["explanation_coverage"],
                "outreach_personalization_score": mapped[
                    "outreach_personalization_score"
                ],
                "policy_violations": int(len(validation_errors)),
                "loop_denials": 0,
                "unhandled_exceptions": base_metrics["failed_count"],
                "delegated_task_count": max(0, base_metrics["total_tasks"] - 2),
                "determinism_variance": 0.0 if not validation_errors else 1.0,
                "procedure_score": procedure_score,
                "customer_metrics": customer_metrics,
                "customer_diagnostics": {
                    "dropoff_reasons": dict(diagnostics.get("dropoff_reasons") or {}),
                    "input_validation_errors": [str(item) for item in validation_errors],
                    "events_count": len(environment_output.get("events") or []),
                },
            }
            self._previous_simulation_results = result
            return result
        except Exception as exc:
            fallback = self._formula_simulation(base_metrics)
            fallback["measurement_source"] = "customer_simulation_fallback_formula"
            fallback["customer_simulation_error"] = str(exc)
            self._previous_simulation_results = fallback
            return fallback

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

    @staticmethod
    def _formula_simulation(base_metrics: Dict[str, Any]) -> Dict[str, Any]:
        success_rate = _clamp01(base_metrics.get("success_rate", 0.0))
        response_rate = min(0.60, 0.12 + (0.30 * success_rate))
        meeting_rate = min(response_rate, response_rate * 0.40)
        match_quality_score = min(1.0, 0.45 + (0.50 * success_rate))
        explanation_coverage = min(1.0, 0.40 + (0.55 * success_rate))
        outreach_personalization_score = min(1.0, 0.50 + (0.45 * success_rate))
        return {
            **base_metrics,
            "measurement_source": "formula_simulation",
            "response_rate": response_rate,
            "meeting_rate": meeting_rate,
            "match_quality_score": match_quality_score,
            "explanation_coverage": explanation_coverage,
            "outreach_personalization_score": outreach_personalization_score,
            "policy_violations": 0,
            "loop_denials": 0,
            "unhandled_exceptions": _safe_int(base_metrics.get("failed_count"), 0),
            "delegated_task_count": max(0, _safe_int(base_metrics.get("total_tasks"), 0) - 2),
            "determinism_variance": 0.0,
            "procedure_score": match_quality_score,
        }

    def _customer_params(self, success_rate: float) -> Dict[str, Any]:
        score = _clamp01(success_rate)
        params = {
            "founder_base_interest": min(1.0, 0.12 + (0.20 * score)),
            "vc_base_interest": min(1.0, 0.10 + (0.18 * score)),
            "meeting_rate_from_mutual_interest": min(1.0, 0.25 + (0.30 * score)),
            "derived_match_score_boost": min(1.0, 0.05 * score),
            "derived_explanation_quality_boost": min(1.0, 0.05 * score),
            "derived_personalization_score_boost": min(1.0, 0.05 * score),
            "derived_timing_score_boost": min(1.0, 0.04 * score),
        }
        # Boost customer params based on HTTP check results
        if self._http_check_results:
            signup_score = _safe_float(
                self._http_check_results.get("http_signup_score", 0.0)
            )
            nav_score = _safe_float(
                self._http_check_results.get("http_navigation_score", 0.0)
            )
            landing_score = _safe_float(
                self._http_check_results.get("http_landing_score", 0.0)
            )
            # CTA clarity boost from signup form quality
            params["derived_personalization_score_boost"] = min(
                1.0,
                params["derived_personalization_score_boost"] + signup_score * 0.15,
            )
            # Reduce signup friction from good navigation
            params["founder_base_interest"] = min(
                1.0,
                params["founder_base_interest"] + nav_score * 0.10,
            )
            # Trust boost from working landing page
            params["vc_base_interest"] = min(
                1.0,
                params["vc_base_interest"] + landing_score * 0.10,
            )
        return params

    def _load_product_events(self) -> Optional[List[Dict[str, Any]]]:
        if self._product_events_loaded:
            return self._cached_product_events

        self._product_events_loaded = True
        self._cached_product_events = None
        if not self._product_events_path:
            return None

        path = Path(self._product_events_path)
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, list):
            return None
        if not all(isinstance(item, dict) for item in payload):
            return None

        events = [dict(item) for item in payload]
        validation_errors = validate_product_events(events)
        if validation_errors:
            return None

        self._cached_product_events = events
        return self._cached_product_events

    @staticmethod
    def _map_customer_metrics(customer_metrics: Dict[str, Any]) -> Dict[str, float]:
        founder_interested = _clamp01(customer_metrics.get("founder_interested_rate", 0.0))
        vc_interested = _clamp01(customer_metrics.get("vc_interested_rate", 0.0))
        response_rate = _clamp01((founder_interested + vc_interested) / 2.0)
        mutual_interest_rate = _clamp01(customer_metrics.get("mutual_interest_rate", 0.0))
        meeting_conversion_rate = _clamp01(
            customer_metrics.get("meeting_conversion_rate", 0.0)
        )
        meeting_rate = _clamp01(mutual_interest_rate * meeting_conversion_rate)
        return {
            "response_rate": response_rate,
            "meeting_rate": meeting_rate,
            "match_quality_score": _clamp01(
                customer_metrics.get("average_match_relevance", 0.0)
            ),
            "explanation_coverage": _clamp01(
                customer_metrics.get("explanation_coverage", 0.0)
            ),
            "outreach_personalization_score": _clamp01(
                customer_metrics.get("personalization_quality_score", 0.0)
            ),
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
            "measurement_source": str(
                simulation_outputs.get("measurement_source", "unknown")
            ),
            "founder_visit_to_signup": float(
                simulation_outputs.get("customer_metrics", {}).get(
                    "founder_visit_to_signup",
                    0.0,
                )
            ),
            "vc_visit_to_signup": float(
                simulation_outputs.get("customer_metrics", {}).get(
                    "vc_visit_to_signup",
                    0.0,
                )
            ),
            "founder_interested_rate": float(
                simulation_outputs.get("customer_metrics", {}).get(
                    "founder_interested_rate",
                    0.0,
                )
            ),
            "vc_interested_rate": float(
                simulation_outputs.get("customer_metrics", {}).get(
                    "vc_interested_rate",
                    0.0,
                )
            ),
            "mutual_interest_rate": float(
                simulation_outputs.get("customer_metrics", {}).get(
                    "mutual_interest_rate",
                    0.0,
                )
            ),
            "meeting_conversion_rate": float(
                simulation_outputs.get("customer_metrics", {}).get(
                    "meeting_conversion_rate",
                    0.0,
                )
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

    def snapshot_workspace(self, cycle_id: int) -> Optional[Dict[str, Any]]:
        """Take a versioned snapshot of the workspace at the start of a cycle."""
        if self._workspace_versioning is None:
            return None
        try:
            return self._workspace_versioning.snapshot(cycle_id)
        except Exception as exc:
            logger.warning("Workspace snapshot failed for cycle %s: %s", cycle_id, exc)
            return None

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
            "customer_simulation_enabled": self._use_customer_simulation,
            "customer_include_visitors": self._include_visitors,
            "customer_product_surface_only": self._product_surface_only,
            "customer_match_calibration_min_samples": self._match_calibration_min_samples,
        }

