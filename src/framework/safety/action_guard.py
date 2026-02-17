"""Unified safety guard that composes policy rules and budget checks.

``ActionGuard`` is the object passed as ``policy_engine`` to
:class:`AgentRuntime`. It implements the same
``check(tool_name, capability, arguments) -> bool`` interface.
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional, Set

from src.framework.safety.budget_manager import BudgetManager
from src.framework.safety.limits import BudgetLimits, ToolClassification
from src.framework.safety.policy_engine import PolicyEngine, PolicyResult


class _DenialRecord:
    """Internal log entry for a denied tool call."""

    __slots__ = ("tool_name", "reason", "rule_name", "timestamp")

    def __init__(self, tool_name: str, reason: str, rule_name: str, timestamp: float):
        self.tool_name = tool_name
        self.reason = reason
        self.rule_name = rule_name
        self.timestamp = timestamp


class ActionGuard:
    """Composite guard that checks kill switch, budget, loop, and policy rules.

    Check order:
    1. Kill switch - if killed, deny immediately.
    2. Budget - if budget exhausted, deny.
    3. Loop detection - deny repeated identical tool-call signatures.
    4. Policy rules - delegate to :class:`PolicyEngine`.
    5. On success, reset consecutive-denial counter.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        budget_manager: Optional[BudgetManager] = None,
        max_consecutive_denials: int = 5,
        loop_window_size: int = 20,
        max_identical_calls: int = 5,
    ) -> None:
        self._policy = policy_engine
        self._budget = budget_manager
        self._max_consecutive_denials = max_consecutive_denials
        self._loop_window_size = max(0, int(loop_window_size))
        self._max_identical_calls = max(0, int(max_identical_calls))

        self._killed = False
        self._kill_reason: Optional[str] = None
        self._consecutive_denials = 0
        self._denial_log: List[_DenialRecord] = []
        self._recent_call_signatures: List[str] = []

    # ------------------------------------------------------------------
    # Public interface (matches AgentRuntime expectation)
    # ------------------------------------------------------------------

    def check(self, tool_name: str, capability: str, arguments: Dict[str, Any]) -> bool:
        """Return ``True`` if the tool call is allowed."""
        return self.check_detailed(tool_name, capability, arguments).allowed

    def check_detailed(
        self, tool_name: str, capability: str, arguments: Dict[str, Any]
    ) -> PolicyResult:
        """Full policy check with structured result."""

        # 1. Kill switch
        if self._killed:
            return self._record_denial(
                tool_name,
                PolicyResult(
                    allowed=False,
                    denied_reason=f"Kill switch active: {self._kill_reason}",
                    rule_name="kill_switch",
                ),
            )

        # 2. Budget
        if self._budget is not None and not self._budget.check_budget():
            return self._record_denial(
                tool_name,
                PolicyResult(
                    allowed=False,
                    denied_reason="Budget exhausted",
                    rule_name="budget",
                ),
            )

        # 3. Loop detection
        if self._is_tool_loop(tool_name, capability, arguments):
            return self._record_denial(
                tool_name,
                PolicyResult(
                    allowed=False,
                    denied_reason="Tool-call loop detected",
                    rule_name="loop_detection",
                ),
            )

        # 4. Policy rules
        result = self._policy.check_detailed(tool_name, capability, arguments)
        if not result.allowed:
            pr = self._record_denial(tool_name, result)
            # Auto-kill after N consecutive policy denials
            if self._consecutive_denials >= self._max_consecutive_denials:
                self.kill(
                    f"Auto-killed after {self._consecutive_denials} consecutive policy denials"
                )
            return pr

        # Success - reset consecutive denial counter
        self._consecutive_denials = 0
        return result

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def kill(self, reason: str = "Manual kill") -> None:
        """Permanently disable all tool calls."""
        self._killed = True
        self._kill_reason = reason

    @property
    def is_killed(self) -> bool:
        return self._killed

    @property
    def kill_reason(self) -> Optional[str]:
        return self._kill_reason

    # ------------------------------------------------------------------
    # Denial log
    # ------------------------------------------------------------------

    @property
    def denial_log(self) -> List[_DenialRecord]:
        """List of all denial records (read-only snapshot)."""
        return list(self._denial_log)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _record_denial(self, tool_name: str, result: PolicyResult) -> PolicyResult:
        self._consecutive_denials += 1
        self._denial_log.append(
            _DenialRecord(
                tool_name=tool_name,
                reason=result.denied_reason or "",
                rule_name=result.rule_name or "",
                timestamp=time.time(),
            )
        )
        return result

    def _is_tool_loop(
        self,
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Detect repeated identical tool calls in a sliding window."""
        if self._loop_window_size <= 0 or self._max_identical_calls <= 0:
            return False

        signature = self._signature(tool_name, capability, arguments)
        recent = self._recent_call_signatures[-self._loop_window_size:]
        match_count = sum(1 for item in recent if item == signature)

        self._recent_call_signatures.append(signature)
        keep = max(50, self._loop_window_size * 3)
        if len(self._recent_call_signatures) > keep:
            self._recent_call_signatures = self._recent_call_signatures[-keep:]

        return match_count >= self._max_identical_calls

    @staticmethod
    def _signature(
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> str:
        try:
            arg_sig = json.dumps(arguments, sort_keys=True, default=str)
        except Exception:
            arg_sig = str(arguments)
        return f"{tool_name}|{capability}|{arg_sig}"


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


def create_action_guard(
    run_config: Any,
    execution_context: Any,
    tool_classifications: Optional[Dict[str, ToolClassification]] = None,
    domain_policy_hook: Optional[
        Callable[[str, str, Dict[str, Any]], Optional[str]]
    ] = None,
) -> ActionGuard:
    """Build an :class:`ActionGuard` from a :class:`RunConfig`.

    Reads ``run_config.policies`` dict for:
    - ``allowlist`` (list of tool names)
    - ``denylist`` (list of tool names)
    - ``max_consecutive_denials`` (int, default 5)
    - ``loop_window_size`` (int, default 20)
    - ``max_identical_tool_calls`` (int, default 5)
    """
    policies: Dict[str, Any] = getattr(run_config, "policies", {}) or {}

    allowlist: Optional[Set[str]] = None
    if "allowlist" in policies:
        allowlist = set(policies["allowlist"])

    denylist: Optional[Set[str]] = None
    if "denylist" in policies:
        denylist = set(policies["denylist"])

    max_denials = policies.get("max_consecutive_denials", 5)
    loop_window_size = policies.get("loop_window_size", 20)
    max_identical_calls = policies.get("max_identical_tool_calls", 5)

    policy_engine = PolicyEngine(
        allowlist=allowlist,
        denylist=denylist,
        autonomy_level=getattr(run_config, "autonomy_level", 2),
        tool_classifications=tool_classifications,
        domain_policy_hook=domain_policy_hook,
    )

    budget_limits = BudgetLimits(
        max_tokens=getattr(run_config, "budget_tokens", None),
        max_seconds=getattr(run_config, "budget_seconds", None),
    )

    budget_manager = BudgetManager(
        execution_context=execution_context,
        limits=budget_limits,
    )

    return ActionGuard(
        policy_engine=policy_engine,
        budget_manager=budget_manager,
        max_consecutive_denials=max_denials,
        loop_window_size=loop_window_size,
        max_identical_calls=max_identical_calls,
    )
