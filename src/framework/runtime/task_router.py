"""Task-to-agent routing based on role and capability overlap."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.framework.contracts import TaskSpec
from src.framework.errors import TaskRoutingError
from src.framework.runtime.capability_registry import CapabilityRegistry, RegisteredTool


class RegisteredAgent(BaseModel):
    """An agent registered with the router."""

    model_config = {"arbitrary_types_allowed": True}

    agent_id: str
    agent_role: str
    capabilities: List[str] = Field(default_factory=list)
    agent_instance: Any = None


class RoutingDecision(BaseModel):
    """Result of routing a TaskSpec to an agent."""

    agent_id: str
    agent_role: str
    resolved_tools: List[RegisteredTool] = Field(default_factory=list)
    unresolved_capabilities: List[str] = Field(default_factory=list)
    can_execute: bool = True


class TaskRouter:
    """Route a :class:`TaskSpec` to the best-matching registered agent.

    Matching strategy:
    1. Match by ``agent_role`` first (exact match).
    2. If multiple agents match the role, pick the one with the greatest
       capability overlap with the task's ``required_capabilities``.
    3. If no role match, find the agent with the best capability overlap.
    4. If no agents are registered, raise :class:`TaskRoutingError`.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        self._agents: Dict[str, RegisteredAgent] = {}

    def register_agent(
        self,
        agent_id: str,
        agent_role: str,
        capabilities: List[str],
        agent_instance: Any = None,
    ) -> None:
        """Register an agent that can handle tasks."""
        self._agents[agent_id] = RegisteredAgent(
            agent_id=agent_id,
            agent_role=agent_role,
            capabilities=capabilities,
            agent_instance=agent_instance,
        )

    def route(self, task_spec: TaskSpec) -> RoutingDecision:
        """Resolve a :class:`TaskSpec` to an agent and its tools.

        Raises :class:`TaskRoutingError` if no agents are registered.
        """
        if not self._agents:
            raise TaskRoutingError("No agents registered")

        # 1. Match by role
        role_matches = [
            a for a in self._agents.values() if a.agent_role == task_spec.agent_role
        ]

        if role_matches:
            # Pick the one with the best capability overlap
            chosen = self._best_capability_match(role_matches, task_spec.required_capabilities)
        else:
            # 2. Fallback: best capability overlap across all agents
            chosen = self._best_capability_match(
                list(self._agents.values()), task_spec.required_capabilities
            )

        # Resolve tools for required capabilities
        resolved_tools: List[RegisteredTool] = []
        unresolved: List[str] = []
        for cap in task_spec.required_capabilities:
            tool = self._registry.resolve_best(cap)
            if tool is not None:
                resolved_tools.append(tool)
            else:
                unresolved.append(cap)

        can_execute = len(unresolved) == 0

        return RoutingDecision(
            agent_id=chosen.agent_id,
            agent_role=chosen.agent_role,
            resolved_tools=resolved_tools,
            unresolved_capabilities=unresolved,
            can_execute=can_execute,
        )

    def list_agents(self) -> List[RegisteredAgent]:
        """Return all registered agents."""
        return list(self._agents.values())

    @staticmethod
    def _best_capability_match(
        agents: List[RegisteredAgent], required: List[str]
    ) -> RegisteredAgent:
        """Pick the agent with the greatest overlap with *required*."""
        required_set = set(required)

        def overlap(agent: RegisteredAgent) -> int:
            return len(set(agent.capabilities) & required_set)

        return max(agents, key=overlap)
