"""Scorecard construction from cycle metrics."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from src.framework.contracts import CycleMetrics


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Scorecard(BaseModel):
    """Normalized metrics used for gate evaluation."""

    task_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    completion_rate: float = 0.0
    failure_rate: float = 0.0
    tokens_used: int = 0
    duration_seconds: float = 0.0

    unhandled_exceptions: int = 0
    policy_violations: int = 0
    loop_denials: int = 0
    delegated_task_count: int = 0
    determinism_variance: Optional[float] = None
    procedure_score_delta: Optional[float] = None


def build_scorecard(
    current_metrics: CycleMetrics,
    previous_metrics: Optional[CycleMetrics] = None,
) -> Scorecard:
    """Build a scorecard from one cycle and optional prior cycle."""
    task_count = max(0, _to_int(current_metrics.task_count))
    success_count = max(0, _to_int(current_metrics.success_count))
    failure_count = max(0, _to_int(current_metrics.failure_count))

    completion_rate = (success_count / task_count) if task_count > 0 else 0.0
    failure_rate = (failure_count / task_count) if task_count > 0 else 0.0

    domain = current_metrics.domain_metrics or {}
    prev_domain = previous_metrics.domain_metrics if previous_metrics else {}

    current_proc = _to_float(domain.get("procedure_score"))
    previous_proc = _to_float(prev_domain.get("procedure_score")) if prev_domain else None
    procedure_score_delta: Optional[float] = None
    if current_proc is not None and previous_proc is not None:
        procedure_score_delta = current_proc - previous_proc

    return Scorecard(
        task_count=task_count,
        success_count=success_count,
        failure_count=failure_count,
        completion_rate=completion_rate,
        failure_rate=failure_rate,
        tokens_used=max(0, _to_int(current_metrics.tokens_used)),
        duration_seconds=max(0.0, float(current_metrics.duration_seconds)),
        unhandled_exceptions=max(0, _to_int(domain.get("unhandled_exceptions", 0))),
        policy_violations=max(0, _to_int(domain.get("policy_violations", 0))),
        loop_denials=max(0, _to_int(domain.get("loop_denials", 0))),
        delegated_task_count=max(0, _to_int(domain.get("delegated_task_count", 0))),
        determinism_variance=_to_float(domain.get("determinism_variance")),
        procedure_score_delta=procedure_score_delta,
    )

