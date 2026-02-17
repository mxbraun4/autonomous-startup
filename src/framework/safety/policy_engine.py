"""Rule-based policy engine for tool-call gating.

Evaluation order (first deny wins):
1. Denylist — tool explicitly forbidden
2. Allowlist — tool not in explicit allow set (when set is non-empty)
3. Autonomy level — tool side-effect level exceeds current autonomy cap
4. Argument validators — callable validators on arguments
5. Domain policy hook — optional domain-specific callable
"""

from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel

from src.framework.safety.limits import ToolClassification


class PolicyResult(BaseModel):
    """Structured outcome of a policy check."""

    allowed: bool = True
    denied_reason: Optional[str] = None
    rule_name: Optional[str] = None


class PolicyEngine:
    """Configurable policy engine that gates tool execution.

    Implements the ``check(tool_name, capability, arguments) -> bool``
    interface expected by :class:`AgentRuntime`.
    """

    def __init__(
        self,
        allowlist: Optional[Set[str]] = None,
        denylist: Optional[Set[str]] = None,
        autonomy_level: int = 2,
        tool_classifications: Optional[Dict[str, ToolClassification]] = None,
        argument_validators: Optional[
            List[Callable[[str, Dict[str, Any]], Optional[str]]]
        ] = None,
        domain_policy_hook: Optional[
            Callable[[str, str, Dict[str, Any]], Optional[str]]
        ] = None,
    ) -> None:
        self._allowlist: Set[str] = set(allowlist) if allowlist else set()
        self._denylist: Set[str] = set(denylist) if denylist else set()
        self._autonomy_level = autonomy_level
        self._tool_classifications: Dict[str, ToolClassification] = (
            dict(tool_classifications) if tool_classifications else {}
        )
        self._argument_validators = list(argument_validators or [])
        self._domain_policy_hook = domain_policy_hook

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check(self, tool_name: str, capability: str, arguments: Dict[str, Any]) -> bool:
        """Return ``True`` if the tool call is allowed."""
        return self.check_detailed(tool_name, capability, arguments).allowed

    def check_detailed(
        self, tool_name: str, capability: str, arguments: Dict[str, Any]
    ) -> PolicyResult:
        """Return a :class:`PolicyResult` with denial reason if blocked."""

        # 1. Denylist
        if tool_name in self._denylist:
            return PolicyResult(
                allowed=False,
                denied_reason=f"Tool '{tool_name}' is on the denylist",
                rule_name="denylist",
            )

        # 2. Allowlist (only enforced when non-empty)
        if self._allowlist and tool_name not in self._allowlist:
            return PolicyResult(
                allowed=False,
                denied_reason=f"Tool '{tool_name}' is not on the allowlist",
                rule_name="allowlist",
            )

        # 3. Autonomy-level gating
        classification = self._tool_classifications.get(tool_name)
        if classification is not None:
            if classification.side_effect_level > self._autonomy_level:
                return PolicyResult(
                    allowed=False,
                    denied_reason=(
                        f"Tool '{tool_name}' requires side-effect level "
                        f"{classification.side_effect_level} but autonomy level "
                        f"is {self._autonomy_level}"
                    ),
                    rule_name="autonomy_level",
                )

        # 4. Argument validators
        for validator in self._argument_validators:
            reason = validator(tool_name, arguments)
            if reason is not None:
                return PolicyResult(
                    allowed=False,
                    denied_reason=reason,
                    rule_name="argument_validator",
                )

        # 5. Domain policy hook
        if self._domain_policy_hook is not None:
            reason = self._domain_policy_hook(tool_name, capability, arguments)
            if reason is not None:
                return PolicyResult(
                    allowed=False,
                    denied_reason=reason,
                    rule_name="domain_hook",
                )

        return PolicyResult(allowed=True)

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_to_denylist(self, tool_name: str) -> None:
        self._denylist.add(tool_name)

    def remove_from_denylist(self, tool_name: str) -> None:
        self._denylist.discard(tool_name)

    def add_to_allowlist(self, tool_name: str) -> None:
        self._allowlist.add(tool_name)

    def remove_from_allowlist(self, tool_name: str) -> None:
        self._allowlist.discard(tool_name)

    def set_autonomy_level(self, level: int) -> None:
        self._autonomy_level = level
