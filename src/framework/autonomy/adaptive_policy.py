"""Adaptive policy controller for cycle-end autonomous policy mutation."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from src.framework.contracts import EvaluationResult, GateDecision, RunConfig


class PolicyAdjustment(BaseModel):
    """Single applied policy mutation for observability/audit trails."""

    key: str
    before: Any = None
    after: Any = None
    reason: str = ""
    source_gate: str = ""


class AdaptivePolicyController:
    """Adjust runtime policy constraints from evaluation gate outcomes."""

    def __init__(
        self,
        *,
        run_config: RunConfig,
        policy_engine: Any = None,
        event_emitter: Any = None,
        reliability_pass_streak: int = 3,
        step_adjustment_ratio: float = 0.10,
        learning_improvement_threshold: float = 0.05,
        bounds: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._run_config = run_config
        self._policy_engine = policy_engine
        self._event_emitter = event_emitter
        self._reliability_pass_streak_required = max(1, int(reliability_pass_streak))
        self._step_adjustment_ratio = max(0.0, float(step_adjustment_ratio))
        self._learning_improvement_threshold = float(learning_improvement_threshold)
        self._bounds = dict(bounds or {})
        self._reliability_pass_streak_count = 0

    def apply(self, evaluation_result: EvaluationResult) -> List[PolicyAdjustment]:
        """Apply bounded policy mutations and emit audit events."""
        gates = {gate.gate_name: gate for gate in evaluation_result.gates}
        adjustments: List[PolicyAdjustment] = []

        reliability_gate = gates.get("reliability")
        if reliability_gate is not None and reliability_gate.gate_status == "pass":
            self._reliability_pass_streak_count += 1
        else:
            self._reliability_pass_streak_count = 0

        if self._reliability_pass_streak_count >= self._reliability_pass_streak_required:
            before = int(getattr(self._run_config, "autonomy_level", 0))
            after = self._clamp_int(
                "autonomy_level",
                before + 1,
                default_min=0,
                default_max=5,
            )
            if after != before:
                self._run_config.autonomy_level = after
                self._set_autonomy_level(after)
                adjustments.append(
                    PolicyAdjustment(
                        key="autonomy_level",
                        before=before,
                        after=after,
                        reason=(
                            "Raised autonomy level after reliability pass streak "
                            f"({self._reliability_pass_streak_count})"
                        ),
                        source_gate="reliability",
                    )
                )
            self._reliability_pass_streak_count = 0

        safety_gate = gates.get("safety")
        if safety_gate is not None and safety_gate.gate_status == "fail":
            before_level = int(getattr(self._run_config, "autonomy_level", 0))
            after_level = self._clamp_int(
                "autonomy_level",
                before_level - 1,
                default_min=0,
                default_max=5,
            )
            if after_level != before_level:
                self._run_config.autonomy_level = after_level
                self._set_autonomy_level(after_level)
                adjustments.append(
                    PolicyAdjustment(
                        key="autonomy_level",
                        before=before_level,
                        after=after_level,
                        reason="Lowered autonomy level after safety gate failure",
                        source_gate="safety",
                    )
                )

            deny_before = sorted(self._denylist())
            new_tools = self._extract_offending_tools(safety_gate)
            for tool_name in new_tools:
                self._add_to_denylist(tool_name)
            deny_after = sorted(self._denylist())
            if deny_after != deny_before:
                adjustments.append(
                    PolicyAdjustment(
                        key="denylist",
                        before=deny_before,
                        after=deny_after,
                        reason="Added safety-offending tool(s) to denylist",
                        source_gate="safety",
                    )
                )

        efficiency_gate = gates.get("efficiency")
        if efficiency_gate is not None and efficiency_gate.gate_status == "fail":
            adjustments.extend(
                self._adjust_max_steps(
                    ratio=-self._step_adjustment_ratio,
                    reason="Reduced max_steps_per_cycle after efficiency gate failure",
                    source_gate="efficiency",
                )
            )

        learning_gate = gates.get("learning")
        if (
            learning_gate is not None
            and learning_gate.gate_status == "pass"
            and self._is_strong_learning_improvement(learning_gate)
        ):
            adjustments.extend(
                self._adjust_max_steps(
                    ratio=self._step_adjustment_ratio,
                    reason="Expanded max_steps_per_cycle after strong learning improvement",
                    source_gate="learning",
                )
            )

        if adjustments:
            self._emit(
                "policy.auto_adjusted",
                {
                    "run_id": evaluation_result.run_id,
                    "cycle_id": evaluation_result.cycle_id,
                    "adjustments": [adj.model_dump(mode="json") for adj in adjustments],
                },
            )

        return adjustments

    def force_tighten(
        self,
        *,
        run_id: Optional[str],
        cycle_id: Optional[int],
        reason: str,
    ) -> List[PolicyAdjustment]:
        """Force immediate tightening, typically from diagnostics signals."""
        adjustments = self._adjust_max_steps(
            ratio=-self._step_adjustment_ratio,
            reason=reason,
            source_gate="diagnostics",
        )
        if adjustments:
            self._emit(
                "policy.auto_adjusted",
                {
                    "run_id": run_id,
                    "cycle_id": cycle_id,
                    "adjustments": [adj.model_dump(mode="json") for adj in adjustments],
                },
            )
        return adjustments

    def _adjust_max_steps(
        self,
        *,
        ratio: float,
        reason: str,
        source_gate: str,
    ) -> List[PolicyAdjustment]:
        before = int(getattr(self._run_config, "max_steps_per_cycle", 1))
        delta = max(1, int(math.ceil(before * abs(ratio))))
        if ratio < 0:
            candidate = before - delta
        else:
            candidate = before + delta
        after = self._clamp_int(
            "max_steps_per_cycle",
            candidate,
            default_min=1,
            default_max=10_000,
        )
        if after == before:
            return []
        self._run_config.max_steps_per_cycle = after
        return [
            PolicyAdjustment(
                key="max_steps_per_cycle",
                before=before,
                after=after,
                reason=reason,
                source_gate=source_gate,
            )
        ]

    def _is_strong_learning_improvement(self, gate: GateDecision) -> bool:
        evidence = gate.evidence or {}
        value = evidence.get("procedure_score_delta")
        try:
            delta = float(value)
        except (TypeError, ValueError):
            return False
        return delta >= self._learning_improvement_threshold

    def _extract_offending_tools(self, gate: GateDecision) -> List[str]:
        evidence = gate.evidence or {}
        candidates: List[str] = []
        for key in (
            "offending_tools",
            "policy_violation_tools",
            "denied_tools",
            "tools",
        ):
            value = evidence.get(key)
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, Iterable):
                for entry in value:
                    if isinstance(entry, str):
                        candidates.append(entry)
        for key in ("tool_name", "denied_tool"):
            value = evidence.get(key)
            if isinstance(value, str):
                candidates.append(value)
        cleaned = sorted({name.strip() for name in candidates if name and name.strip()})
        return cleaned

    def _clamp_int(
        self,
        key: str,
        value: int,
        *,
        default_min: int,
        default_max: int,
    ) -> int:
        bounds = self._bounds.get(key) or {}
        lower = _safe_int(bounds.get("min"), default_min)
        upper = _safe_int(bounds.get("max"), default_max)
        if lower > upper:
            lower, upper = upper, lower
        return max(lower, min(upper, int(value)))

    def _denylist(self) -> set[str]:
        policies = dict(getattr(self._run_config, "policies", {}) or {})
        denylist = set(policies.get("denylist") or [])
        return {name for name in denylist if isinstance(name, str) and name}

    def _add_to_denylist(self, tool_name: str) -> None:
        if not tool_name:
            return
        policies = dict(getattr(self._run_config, "policies", {}) or {})
        deny = set(policies.get("denylist") or [])
        deny.add(tool_name)
        policies["denylist"] = sorted(deny)
        self._run_config.policies = policies

        engine = self._policy_engine
        if engine is None:
            return
        if hasattr(engine, "add_to_denylist"):
            try:
                engine.add_to_denylist(tool_name)
                return
            except Exception:
                pass
        inner = getattr(engine, "_policy", None)
        if inner is not None and hasattr(inner, "add_to_denylist"):
            try:
                inner.add_to_denylist(tool_name)
            except Exception:
                pass

    def _set_autonomy_level(self, level: int) -> None:
        engine = self._policy_engine
        if engine is None:
            return
        if hasattr(engine, "set_autonomy_level"):
            try:
                engine.set_autonomy_level(level)
                return
            except Exception:
                pass
        inner = getattr(engine, "_policy", None)
        if inner is not None and hasattr(inner, "set_autonomy_level"):
            try:
                inner.set_autonomy_level(level)
            except Exception:
                pass

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        try:
            self._event_emitter.emit(event_type, payload)
        except Exception:
            pass


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)
