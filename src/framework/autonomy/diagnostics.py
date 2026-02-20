"""Autonomous diagnostics agent that reacts to observability signals."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from src.framework.contracts import RunConfig


class DiagnosticsAction(BaseModel):
    """Single diagnostics action with reason and effect."""

    action: str
    reason: str
    details: Dict[str, Any] = Field(default_factory=dict)


class DiagnosticsAgent:
    """Scan recent events and execute bounded self-diagnosis actions."""

    def __init__(
        self,
        *,
        event_source: Any,
        run_config: RunConfig,
        adaptive_policy_controller: Any = None,
        policy_engine: Any = None,
        event_emitter: Any = None,
        window_size: int = 100,
        policy_violation_threshold: int = 3,
        tool_denied_threshold: int = 3,
        gate_drop_window: int = 3,
    ) -> None:
        self._event_source = event_source
        self._run_config = run_config
        self._adaptive_policy_controller = adaptive_policy_controller
        self._policy_engine = policy_engine
        self._event_emitter = event_emitter
        self._window_size = max(1, int(window_size))
        self._policy_violation_threshold = max(1, int(policy_violation_threshold))
        self._tool_denied_threshold = max(1, int(tool_denied_threshold))
        self._gate_drop_window = max(2, int(gate_drop_window))
        self._last_seen_events = 0

    def scan_and_act(
        self,
        *,
        run_id: Optional[str],
        cycle_id: Optional[int],
    ) -> List[DiagnosticsAction]:
        """Scan event window and apply diagnostics actions."""
        events = self._load_events(run_id=run_id)
        if not events:
            return []
        if len(events) <= self._last_seen_events:
            return []
        self._last_seen_events = len(events)

        window = events[-self._window_size :]
        actions: List[DiagnosticsAction] = []
        actions.extend(self._handle_tool_denials(window, run_id=run_id, cycle_id=cycle_id))
        actions.extend(self._handle_policy_violations(window, run_id=run_id, cycle_id=cycle_id))
        actions.extend(self._handle_budget_warnings(window, run_id=run_id, cycle_id=cycle_id))
        actions.extend(self._handle_gate_regression(window, run_id=run_id, cycle_id=cycle_id))

        for action in actions:
            self._emit(
                "diagnostics.action_taken",
                {
                    "run_id": run_id,
                    "cycle_id": cycle_id,
                    **action.model_dump(mode="json"),
                },
            )
        return actions

    def _handle_tool_denials(
        self,
        events: Sequence[Any],
        *,
        run_id: Optional[str],
        cycle_id: Optional[int],
    ) -> List[DiagnosticsAction]:
        counts: Dict[str, int] = {}
        for event in events:
            if getattr(event, "event_type", "") != "tool_denied":
                continue
            payload = getattr(event, "payload", {}) or {}
            tool_name = str(payload.get("tool_name") or "").strip()
            if not tool_name:
                continue
            counts[tool_name] = counts.get(tool_name, 0) + 1

        actions: List[DiagnosticsAction] = []
        for tool_name, count in sorted(counts.items()):
            if count < self._tool_denied_threshold:
                continue
            if tool_name in self._denylist():
                continue
            self._add_to_denylist(tool_name)
            actions.append(
                DiagnosticsAction(
                    action="tool_disabled",
                    reason=(
                        f"Observed {count} tool_denied events for '{tool_name}' "
                        f"in last {self._window_size} events"
                    ),
                    details={
                        "tool_name": tool_name,
                        "denied_count": count,
                        "fallback_mode": "policy_denylist",
                        "run_id": run_id,
                        "cycle_id": cycle_id,
                    },
                )
            )
        return actions

    def _handle_policy_violations(
        self,
        events: Sequence[Any],
        *,
        run_id: Optional[str],
        cycle_id: Optional[int],
    ) -> List[DiagnosticsAction]:
        count = sum(
            1
            for event in events
            if getattr(event, "event_type", "") == "policy_violation"
        )
        if count < self._policy_violation_threshold:
            return []

        details: Dict[str, Any] = {"policy_violations": count}
        if self._adaptive_policy_controller is not None and hasattr(
            self._adaptive_policy_controller,
            "force_tighten",
        ):
            adjustments = self._adaptive_policy_controller.force_tighten(
                run_id=run_id,
                cycle_id=cycle_id,
                reason="Tightened by diagnostics after policy_violation burst",
            )
            serialized: List[Dict[str, Any]] = []
            for adjustment in adjustments:
                if hasattr(adjustment, "model_dump"):
                    serialized.append(adjustment.model_dump(mode="json"))
                elif isinstance(adjustment, dict):
                    serialized.append(dict(adjustment))
                else:
                    serialized.append({"value": str(adjustment)})
            details["adjustments"] = serialized
        else:
            # Fallback tightening when no adaptive controller is present.
            before = int(getattr(self._run_config, "max_steps_per_cycle", 1))
            after = max(1, int(before * 0.9))
            self._run_config.max_steps_per_cycle = after
            details["adjustments"] = [
                {
                    "key": "max_steps_per_cycle",
                    "before": before,
                    "after": after,
                }
            ]

        return [
            DiagnosticsAction(
                action="policy_tightened",
                reason=(
                    f"Observed {count} policy_violation events in "
                    f"last {self._window_size} events"
                ),
                details=details,
            )
        ]

    def _handle_budget_warnings(
        self,
        events: Sequence[Any],
        *,
        run_id: Optional[str],
        cycle_id: Optional[int],
    ) -> List[DiagnosticsAction]:
        count = sum(
            1
            for event in events
            if getattr(event, "event_type", "") == "budget.warning"
        )
        if count <= 0:
            return []

        policies = dict(getattr(self._run_config, "policies", {}) or {})
        current_limit = policies.get("exploratory_task_limit")
        if current_limit is None:
            policies["exploratory_task_limit"] = 1
        else:
            try:
                policies["exploratory_task_limit"] = max(1, int(current_limit))
            except (TypeError, ValueError):
                policies["exploratory_task_limit"] = 1
        policies["llm_tier_override"] = "cheap"
        self._run_config.policies = policies

        return [
            DiagnosticsAction(
                action="scope_reduced",
                reason=(
                    f"Observed {count} budget.warning events; "
                    "reduced next-cycle scope and set cheap model tier"
                ),
                details={
                    "exploratory_task_limit": policies["exploratory_task_limit"],
                    "llm_tier_override": policies["llm_tier_override"],
                    "run_id": run_id,
                    "cycle_id": cycle_id,
                },
            )
        ]

    def _handle_gate_regression(
        self,
        events: Sequence[Any],
        *,
        run_id: Optional[str],
        cycle_id: Optional[int],
    ) -> List[DiagnosticsAction]:
        completion_rates: List[float] = []
        seen_cycles: set[int] = set()
        for event in reversed(events):
            if getattr(event, "event_type", "") != "gate_decision":
                continue
            payload = getattr(event, "payload", {}) or {}
            cycle = payload.get("cycle_id")
            try:
                cycle_id_int = int(cycle)
            except (TypeError, ValueError):
                continue
            if cycle_id_int in seen_cycles:
                continue
            seen_cycles.add(cycle_id_int)

            scorecard = (payload.get("metadata") or {}).get("scorecard") or {}
            value = scorecard.get("completion_rate")
            try:
                completion_rates.append(float(value))
            except (TypeError, ValueError):
                continue
            if len(completion_rates) >= self._gate_drop_window:
                break

        if len(completion_rates) < self._gate_drop_window:
            return []

        # completion_rates collected newest -> oldest, reverse for trend check.
        ordered = list(reversed(completion_rates))
        if not _strictly_decreasing(ordered):
            return []

        policies = dict(getattr(self._run_config, "policies", {}) or {})
        if bool(policies.get("strategy_shift_requested")):
            return []
        policies["strategy_shift_requested"] = True
        self._run_config.policies = policies

        return [
            DiagnosticsAction(
                action="strategy_shift",
                reason=(
                    f"Detected monotonic gate score decline across "
                    f"{self._gate_drop_window} cycles"
                ),
                details={
                    "completion_rate_sequence": ordered,
                    "strategy_shift_requested": True,
                    "run_id": run_id,
                    "cycle_id": cycle_id,
                },
            )
        ]

    def _load_events(self, *, run_id: Optional[str]) -> List[Any]:
        source = self._event_source
        if source is None:
            return []

        if hasattr(source, "get_events"):
            try:
                if run_id is None:
                    return list(source.get_events())
                return list(source.get_events(run_id=run_id))
            except Exception:
                return []

        if callable(source):
            try:
                return list(source(run_id=run_id))
            except Exception:
                return []
        return []

    def _denylist(self) -> set[str]:
        policies = dict(getattr(self._run_config, "policies", {}) or {})
        deny = set(policies.get("denylist") or [])
        return {name for name in deny if isinstance(name, str) and name}

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

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        try:
            self._event_emitter.emit(event_type, payload)
        except Exception:
            pass


def _strictly_decreasing(values: Sequence[float]) -> bool:
    if len(values) < 2:
        return False
    for idx in range(1, len(values)):
        if values[idx] >= values[idx - 1]:
            return False
    return True
