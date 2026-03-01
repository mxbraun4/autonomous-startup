"""Layer F — Safety & Governance.

Public API
----------
ActionGuard          Composite guard (the ``policy_engine`` for AgentRuntime)
BudgetLimits         Declarative budget caps
BudgetManager        Read-only budget query layer
PolicyEngine         Rule-based tool-call gating
PolicyResult         Structured check outcome
ToolClassification   Per-tool risk metadata
create_action_guard  Factory that builds an ActionGuard from RunConfig
"""

from src.framework.safety.action_guard import ActionGuard, create_action_guard
from src.framework.safety.budget_manager import BudgetManager
from src.framework.safety.limits import BudgetLimits, ToolClassification
from src.framework.safety.policy_engine import PolicyEngine, PolicyResult
from src.framework.safety.startup_vc_policy import build_startup_vc_domain_policy_hook
from src.framework.safety.web_policy import build_web_domain_policy_hook

__all__ = [
    "ActionGuard",
    "BudgetLimits",
    "BudgetManager",
    "PolicyEngine",
    "PolicyResult",
    "ToolClassification",
    "build_startup_vc_domain_policy_hook",
    "build_web_domain_policy_hook",
    "create_action_guard",
]
