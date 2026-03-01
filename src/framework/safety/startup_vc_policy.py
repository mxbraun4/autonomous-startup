"""Domain policy hook for startup-VC autonomy.

Gates tool calls that CrewAI agents make during framework-mode execution.
The hook is consulted by ``PolicyEngine`` on every tool invocation that
passes through the ``AgentRuntime.execute_tool_call()`` bridge.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


# Tool names that correspond to the CrewAI tools defined in
# ``src/crewai_agents/tools.py``.  Must match the ``name`` attribute on
# each ``@tool`` decorated function.
TOOL_WEB_SEARCH_STARTUPS = "web_search_startups"
TOOL_WEB_SEARCH_VCS = "web_search_vcs"

# Policy key names read from the policies dict.
POLICY_MAX_WEB_SEARCHES_PER_CYCLE = "max_web_searches_per_cycle"

# Defaults
_DEFAULT_MAX_WEB_SEARCHES = 20


def build_startup_vc_domain_policy_hook(
    policies: Dict[str, Any],
) -> Callable[[str, str, Dict[str, Any]], Optional[str]]:
    """Build a domain hook for startup-VC safety constraints.

    The returned callable follows the framework's domain-policy-hook
    contract: ``(tool_name, capability, arguments) -> Optional[str]``.
    It returns ``None`` when the call is allowed and an error message
    string when the call should be denied.

    Enforced constraints
    --------------------
    * ``web_search_startups`` and ``web_search_vcs`` are capped at
      ``max_web_searches_per_cycle`` combined invocations (default 20).
    """
    max_web_searches = int(
        policies.get(POLICY_MAX_WEB_SEARCHES_PER_CYCLE, _DEFAULT_MAX_WEB_SEARCHES)
    )

    web_search_count = 0

    def hook(
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> Optional[str]:
        nonlocal web_search_count
        name = tool_name or capability

        if name in (TOOL_WEB_SEARCH_STARTUPS, TOOL_WEB_SEARCH_VCS):
            web_search_count += 1
            if web_search_count > max_web_searches:
                return (
                    f"Web search blocked: cycle limit reached "
                    f"({max_web_searches} per cycle)"
                )

        return None

    return hook
