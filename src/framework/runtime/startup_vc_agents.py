"""CrewAI-backed agent wrappers for the startup-VC domain.

Each agent callable follows the framework contract:
    (task_spec, tools, context) -> Dict[str, Any]

The actual work happens inside a single-task CrewAI crew kickoff so that
the framework's RunController, evaluation gates, checkpointing, adaptive
policy, and diagnostics remain fully in the loop.

Tool calls inside CrewAI agents are bridged back to
``AgentRuntime.execute_tool_call()`` so that the framework can observe,
gate, and audit every invocation.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Dict, List, Optional

from src.crewai_agents.runtime_env import (
    configure_runtime_environment,
    patch_crewai_storage_paths,
)

configure_runtime_environment()
from crewai import Crew, Task, Process, LLM  # noqa: E402

patch_crewai_storage_paths()

from src.crewai_agents.agents import (  # noqa: E402
    create_data_strategist,
    create_product_strategist,
    create_website_builder,
    get_llm,
)
from src.framework.runtime.capability_registry import CapabilityRegistry  # noqa: E402
from src.framework.runtime.task_router import TaskRouter  # noqa: E402
from src.framework.types import ToolCallStatus  # noqa: E402
from src.utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Role names (must match the agent_role values returned by StartupVCAdapter)
# ---------------------------------------------------------------------------
ROLE_DATA_SPECIALIST = "data_specialist"
ROLE_MATCHING_SPECIALIST = "matching_specialist"
ROLE_WEBSITE_BUILDER = "website_builder"

# ---------------------------------------------------------------------------
# Capability labels
# ---------------------------------------------------------------------------
CAP_DATA_COVERAGE_ANALYSIS = "data_coverage_analysis"
CAP_DATABASE_WRITE = "database_write"
CAP_MATCH_SCORING = "match_scoring"
CAP_EXPLANATION_GENERATION = "explanation_generation"
CAP_WORKSPACE_READ = "workspace_read"
CAP_WORKSPACE_WRITE = "workspace_write"
CAP_WORKSPACE_LIST = "workspace_list"


# ---------------------------------------------------------------------------
# Tool-call bridge: route CrewAI tool invocations through the framework
# ---------------------------------------------------------------------------

def _bridge_crewai_tools(
    crewai_agent: Any,
    runtime: Any,
    agent_id: str,
    task_id: str,
    collected_call_ids: List[str],
) -> None:
    """Monkey-patch every tool on *crewai_agent* so invocations route through
    ``runtime.execute_tool_call()`` before hitting the real tool function.

    This gives the framework visibility (events, policy, loop detection) over
    every tool call that CrewAI agents make internally.
    """
    if runtime is None:
        return
    for tool in getattr(crewai_agent, "tools", None) or []:
        original_run = getattr(tool, "_run", None)
        if original_run is None:
            continue

        tool_name = getattr(tool, "name", str(tool))

        @functools.wraps(original_run)
        def _wrapped_run(
            *args: Any,
            _orig=original_run,
            _tname=tool_name,
            **kwargs: Any,
        ) -> Any:
            tc = runtime.execute_tool_call(
                tool_name=_tname,
                capability=_tname,
                arguments=kwargs,
                agent_id=agent_id,
                task_id=task_id,
            )
            if tc.call_status == ToolCallStatus.SUCCESS:
                # The framework already ran the passthrough callable — now
                # run the *real* CrewAI tool function for actual work.
                collected_call_ids.append(tc.entity_id)
                return _orig(*args, **kwargs)
            if tc.call_status == ToolCallStatus.DENIED:
                reason = getattr(tc, "denied_reason", "denied by policy")
                collected_call_ids.append(tc.entity_id)
                return f"[Tool denied: {reason}]"
            # Budget exceeded or error
            collected_call_ids.append(tc.entity_id)
            error = getattr(tc, "error_message", tc.call_status.value)
            return f"[Tool error: {error}]"

        tool._run = _wrapped_run


# ---------------------------------------------------------------------------
# Agent factories
# ---------------------------------------------------------------------------

def _crew_kickoff_result(crew_output: Any) -> str:
    """Extract text from a CrewAI crew output."""
    if crew_output is None:
        return ""
    if hasattr(crew_output, "raw"):
        return str(crew_output.raw)
    return str(crew_output)


def _extract_crew_reasoning(crew_output: Any) -> str:
    """Extract per-task reasoning trace from a CrewAI crew output.

    Checks for ``tasks_output`` (list of ``TaskOutput``) and concatenates
    each task's description + raw output into a readable reasoning trace.
    Falls back to ``str(crew_output)`` when structured output is unavailable.
    """
    if crew_output is None:
        return ""
    tasks_output = getattr(crew_output, "tasks_output", None)
    if tasks_output:
        parts: List[str] = []
        for i, task_out in enumerate(tasks_output):
            desc = getattr(task_out, "description", "") or ""
            raw = getattr(task_out, "raw", "") or str(task_out)
            parts.append(f"[Task {i}] {desc}\n{raw}")
        return "\n---\n".join(parts)
    return str(crew_output)


def make_data_specialist_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs a CrewAI data crew."""

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Analyse startup/VC data coverage gaps"
        constraints = dict(getattr(task_spec, "constraints", {}) or {})
        max_targets = constraints.get("max_targets", 5)
        task_id = getattr(task_spec, "task_id", "unknown")

        crewai_agent = create_data_strategist(llm or get_llm("data"))
        call_ids: List[str] = []
        _bridge_crewai_tools(crewai_agent, runtime, ROLE_DATA_SPECIALIST, task_id, call_ids)

        crewai_task = Task(
            description=(
                f"{objective}\n\n"
                f"Max targets this cycle: {max_targets}\n"
                f"Additional input: {input_data}"
            ),
            agent=crewai_agent,
            expected_output="Data coverage report with gaps identified, data collected, quality scores.",
        )
        crew = Crew(
            agents=[crewai_agent],
            tasks=[crewai_task],
            process=Process.sequential,
            verbose=False,
            memory=False,
        )
        try:
            result = crew.kickoff()
            output_text = _crew_kickoff_result(result)
            reasoning = _extract_crew_reasoning(result)
        except Exception as exc:
            logger.warning("data_specialist crew failed: %s", exc)
            output_text = f"Data specialist crew error: {exc}"
            reasoning = ""

        return {
            "output_text": output_text,
            "reasoning": reasoning,
            "tool_calls": call_ids,
            "tokens_used": 0,
        }

    return agent


def make_matching_specialist_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs a CrewAI matching crew."""

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Generate startup-to-VC match shortlist"
        constraints = dict(getattr(task_spec, "constraints", {}) or {})
        shortlist_size = constraints.get("shortlist_size", 5)
        task_id = getattr(task_spec, "task_id", "unknown")

        crewai_agent = create_product_strategist(llm or get_llm("product"))
        call_ids: List[str] = []
        _bridge_crewai_tools(crewai_agent, runtime, ROLE_MATCHING_SPECIALIST, task_id, call_ids)

        crewai_task = Task(
            description=(
                f"{objective}\n\n"
                f"Shortlist size: {shortlist_size}\n"
                f"Additional input: {input_data}"
            ),
            agent=crewai_agent,
            expected_output="Match shortlist with scores and explanations for each match.",
        )
        crew = Crew(
            agents=[crewai_agent],
            tasks=[crewai_task],
            process=Process.sequential,
            verbose=False,
            memory=False,
        )
        try:
            result = crew.kickoff()
            output_text = _crew_kickoff_result(result)
            reasoning = _extract_crew_reasoning(result)
        except Exception as exc:
            logger.warning("matching_specialist crew failed: %s", exc)
            output_text = f"Matching specialist crew error: {exc}"
            reasoning = ""

        return {
            "output_text": output_text,
            "reasoning": reasoning,
            "tool_calls": call_ids,
            "tokens_used": 0,
        }

    return agent


def make_website_builder_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs a CrewAI website builder crew."""

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Improve the marketplace website"
        task_id = getattr(task_spec, "task_id", "unknown")

        crewai_agent = create_website_builder(llm or get_llm("developer"))
        call_ids: List[str] = []
        _bridge_crewai_tools(crewai_agent, runtime, ROLE_WEBSITE_BUILDER, task_id, call_ids)

        crewai_task = Task(
            description=(
                f"{objective}\n\n"
                f"Previous feedback and HTTP check results: {input_data}"
            ),
            agent=crewai_agent,
            expected_output="Summary of website improvements made with files modified.",
        )
        crew = Crew(
            agents=[crewai_agent],
            tasks=[crewai_task],
            process=Process.sequential,
            verbose=False,
            memory=False,
        )
        try:
            result = crew.kickoff()
            output_text = _crew_kickoff_result(result)
            reasoning = _extract_crew_reasoning(result)
        except Exception as exc:
            logger.warning("website_builder crew failed: %s", exc)
            output_text = f"Website builder crew error: {exc}"
            reasoning = ""

        return {
            "output_text": output_text,
            "reasoning": reasoning,
            "tool_calls": call_ids,
            "tokens_used": 0,
        }

    return agent


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def _passthrough_callable(**kwargs: Any) -> Dict[str, Any]:
    """Passthrough capability — actual work is done inside the CrewAI agents."""
    return {"status": "delegated_to_crewai_agent", "input": kwargs}


def register_startup_vc_capabilities(registry: CapabilityRegistry) -> None:
    """Register the 4 capability labels used by StartupVCAdapter tasks.

    These are passthrough entries: the real tool invocations happen inside
    the CrewAI agents that have their own tool sets.
    """
    for cap_name in (
        CAP_DATA_COVERAGE_ANALYSIS,
        CAP_DATABASE_WRITE,
        CAP_MATCH_SCORING,
        CAP_EXPLANATION_GENERATION,
    ):
        registry.register(
            capability=cap_name,
            tool_name=cap_name,
            tool_callable=_passthrough_callable,
            priority=0,
        )


def register_workspace_capabilities(registry: CapabilityRegistry) -> None:
    """Register the 3 workspace capability labels for the website builder."""
    for cap_name in (
        CAP_WORKSPACE_READ,
        CAP_WORKSPACE_WRITE,
        CAP_WORKSPACE_LIST,
    ):
        registry.register(
            capability=cap_name,
            tool_name=cap_name,
            tool_callable=_passthrough_callable,
            priority=0,
        )


def register_startup_vc_agents(
    router: TaskRouter,
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
    enable_workspace: bool = False,
) -> None:
    """Register the startup-VC agents with the task router.

    When *enable_workspace* is True, also registers the website builder agent.
    """

    router.register_agent(
        agent_id=ROLE_DATA_SPECIALIST,
        agent_role=ROLE_DATA_SPECIALIST,
        capabilities=[CAP_DATA_COVERAGE_ANALYSIS, CAP_DATABASE_WRITE],
        agent_instance=make_data_specialist_agent(runtime, llm=llm),
    )
    router.register_agent(
        agent_id=ROLE_MATCHING_SPECIALIST,
        agent_role=ROLE_MATCHING_SPECIALIST,
        capabilities=[CAP_MATCH_SCORING, CAP_EXPLANATION_GENERATION],
        agent_instance=make_matching_specialist_agent(runtime, llm=llm),
    )
    if enable_workspace:
        router.register_agent(
            agent_id=ROLE_WEBSITE_BUILDER,
            agent_role=ROLE_WEBSITE_BUILDER,
            capabilities=[CAP_WORKSPACE_READ, CAP_WORKSPACE_WRITE, CAP_WORKSPACE_LIST],
            agent_instance=make_website_builder_agent(runtime, llm=llm),
        )
