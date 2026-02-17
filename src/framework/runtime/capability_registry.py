"""Tool registration and resolution by capability label."""

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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a tool under a capability label."""
        tool = RegisteredTool(
            tool_name=tool_name,
            capability=capability,
            priority=priority,
            tool_callable=tool_callable,
            metadata=metadata or {},
        )
        self._tools.setdefault(capability, []).append(tool)

    def resolve(self, capability: str) -> List[RegisteredTool]:
        """Return all tools for *capability*, sorted by priority (ascending)."""
        tools = self._tools.get(capability, [])
        return sorted(tools, key=lambda t: t.priority)

    def resolve_best(self, capability: str) -> Optional[RegisteredTool]:
        """Return the highest-priority tool for *capability*, or ``None``."""
        resolved = self.resolve(capability)
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
