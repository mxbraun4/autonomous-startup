"""Tool registration and resolution by capability label.

Adds basic health-aware resolution for failover:
- tools can enter cooldown after failures
- resolver skips cooling-down tools by default
- runtime can record success/failure outcomes per tool
"""

import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class RegisteredTool(BaseModel):
    """A tool registered under a capability label."""

    model_config = {"arbitrary_types_allowed": True}

    tool_name: str
    capability: str
    priority: int = 0
    tool_callable: Any = None  # the actual callable
    metadata: Dict[str, Any] = Field(default_factory=dict)
    cooldown_seconds: float = 0.0
    cooldown_until_epoch: float = 0.0
    consecutive_failures: int = 0


class CapabilityRegistry:
    """Registry that maps capability labels to concrete tool implementations.

    Tools are registered under capability labels (e.g. ``"web_search"``).
    Multiple tools may share a capability; resolution returns them sorted
    by priority (lower = preferred).
    """

    def __init__(self) -> None:
        self._tools: Dict[str, List[RegisteredTool]] = {}

    def register(
        self,
        capability: str,
        tool_name: str,
        tool_callable: Callable[..., Any],
        priority: int = 0,
        cooldown_seconds: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a tool under a capability label."""
        md = metadata or {}
        effective_cooldown = float(md.get("cooldown_seconds", cooldown_seconds))
        tool = RegisteredTool(
            tool_name=tool_name,
            capability=capability,
            priority=priority,
            tool_callable=tool_callable,
            metadata=md,
            cooldown_seconds=max(0.0, effective_cooldown),
        )
        self._tools.setdefault(capability, []).append(tool)

    def resolve(
        self,
        capability: str,
        include_unavailable: bool = False,
        now: Optional[float] = None,
    ) -> List[RegisteredTool]:
        """Return tools for *capability*, sorted by priority (ascending).

        By default, tools currently in cooldown are filtered out.
        """
        tools = self._tools.get(capability, [])
        if include_unavailable:
            return sorted(tools, key=lambda t: t.priority)

        current = time.monotonic() if now is None else now
        available = [t for t in tools if self._is_available(t, current)]
        return sorted(available, key=lambda t: t.priority)

    def resolve_best(
        self,
        capability: str,
        include_unavailable: bool = False,
    ) -> Optional[RegisteredTool]:
        """Return the highest-priority tool for *capability*, or ``None``."""
        resolved = self.resolve(capability, include_unavailable=include_unavailable)
        return resolved[0] if resolved else None

    def list_capabilities(self) -> List[str]:
        """Return all registered capability labels."""
        return list(self._tools.keys())

    def list_tools(self, capability: Optional[str] = None) -> List[RegisteredTool]:
        """Return all registered tools, optionally filtered by capability."""
        if capability is not None:
            return list(self._tools.get(capability, []))
        result: List[RegisteredTool] = []
        for tools in self._tools.values():
            result.extend(tools)
        return result

    def mark_tool_success(self, capability: str, tool_name: str) -> None:
        """Reset failure counters for a successful tool call."""
        tool = self._find_tool(capability, tool_name)
        if tool is None:
            return
        tool.consecutive_failures = 0
        tool.cooldown_until_epoch = 0.0

    def mark_tool_failure(self, capability: str, tool_name: str) -> None:
        """Record a failed tool call and enter cooldown when configured."""
        tool = self._find_tool(capability, tool_name)
        if tool is None:
            return

        tool.consecutive_failures += 1
        if tool.cooldown_seconds > 0.0:
            tool.cooldown_until_epoch = time.monotonic() + tool.cooldown_seconds

    def is_tool_available(self, capability: str, tool_name: str) -> bool:
        """Return ``True`` if the tool is not currently cooling down."""
        tool = self._find_tool(capability, tool_name)
        if tool is None:
            return False
        return self._is_available(tool, time.monotonic())

    def resolution_trace(self, capability: str) -> List[Dict[str, Any]]:
        """Return availability diagnostics for all tools on a capability."""
        now = time.monotonic()
        trace: List[Dict[str, Any]] = []
        for tool in sorted(self._tools.get(capability, []), key=lambda t: t.priority):
            trace.append(
                {
                    "tool_name": tool.tool_name,
                    "priority": tool.priority,
                    "available": self._is_available(tool, now),
                    "consecutive_failures": tool.consecutive_failures,
                    "cooldown_remaining_seconds": max(
                        0.0, tool.cooldown_until_epoch - now
                    ),
                }
            )
        return trace

    def _find_tool(self, capability: str, tool_name: str) -> Optional[RegisteredTool]:
        for tool in self._tools.get(capability, []):
            if tool.tool_name == tool_name:
                return tool
        return None

    @staticmethod
    def _is_available(tool: RegisteredTool, now: float) -> bool:
        return tool.cooldown_until_epoch <= now
