"""Agent runtime - execution substrate for all autonomy layers."""

from src.framework.runtime.capability_registry import CapabilityRegistry, RegisteredTool
from src.framework.runtime.execution_context import ExecutionContext
from src.framework.runtime.task_router import RegisteredAgent, RoutingDecision, TaskRouter
from src.framework.runtime.agent_runtime import AgentRuntime
from src.framework.runtime.localhost_tools import LocalhostAutonomyToolset
from src.framework.runtime.web_edit_templates import (
    get_edit_templates,
    list_edit_templates,
    resolve_edit_template,
)
from src.framework.runtime.web_agents import (
    make_web_explorer_agent,
    make_web_improver_agent,
    make_web_validator_agent,
    register_web_agents,
    register_web_capabilities,
)

__all__ = [
    "AgentRuntime",
    "CapabilityRegistry",
    "ExecutionContext",
    "LocalhostAutonomyToolset",
    "RegisteredAgent",
    "RegisteredTool",
    "RoutingDecision",
    "TaskRouter",
    "get_edit_templates",
    "list_edit_templates",
    "make_web_explorer_agent",
    "make_web_improver_agent",
    "make_web_validator_agent",
    "register_web_agents",
    "register_web_capabilities",
    "resolve_edit_template",
]

