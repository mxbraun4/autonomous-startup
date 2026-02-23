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
    create_developer_agent,
    create_master_coordinator,
    create_product_strategist,
    create_reviewer_agent,
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
ROLE_COORDINATOR = "coordinator"
ROLE_PRODUCT_STRATEGIST = "product_strategist"
ROLE_DATA_SPECIALIST = "data_specialist"
ROLE_MATCHING_SPECIALIST = "matching_specialist"
ROLE_WORKSPACE_DEVELOPER = "workspace_developer"

# ---------------------------------------------------------------------------
# Capability labels
# ---------------------------------------------------------------------------
CAP_COORDINATION = "coordination"
CAP_PRODUCT_STRATEGY = "product_strategy"
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


# ---------------------------------------------------------------------------
# Coordinator helpers
# ---------------------------------------------------------------------------

_AVAILABLE_AGENTS = [
    "product_strategist",
    "workspace_developer",
    "data_specialist",
    "matching_specialist",
]


def _format_feedback_for_coordinator(input_data: Dict[str, Any]) -> str:
    """Format feedback metrics into a readable prompt section for the coordinator."""
    parts: List[str] = []

    http_checks = input_data.get("previous_http_checks")
    if http_checks and isinstance(http_checks, dict):
        parts.append("HTTP check results:")
        for key, value in http_checks.items():
            parts.append(f"  {key}: {value}")

    customer_metrics = input_data.get("customer_metrics")
    if customer_metrics and isinstance(customer_metrics, dict):
        parts.append("Customer simulation metrics:")
        for key, value in customer_metrics.items():
            parts.append(f"  {key}: {value}")

    previous_results = input_data.get("previous_results")
    if previous_results and isinstance(previous_results, dict):
        parts.append("Previous cycle results:")
        for key, value in previous_results.items():
            parts.append(f"  {key}: {value}")

    return "\n".join(parts) if parts else "No feedback available yet (first cycle)."


def _parse_delegated_tasks(output_text: str) -> Optional[List[Dict[str, Any]]]:
    """Extract delegated_tasks from coordinator LLM output.

    Supports JSON inside ```json code fences, raw JSON objects, or bare JSON
    arrays. Returns None if parsing fails.
    """
    import json
    import re

    if not output_text or not isinstance(output_text, str):
        return None

    # Try extracting from ```json ... ``` code fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", output_text, re.DOTALL)
    text_to_parse = fence_match.group(1) if fence_match else output_text

    # Try parsing as JSON object with delegated_tasks key
    try:
        parsed = json.loads(text_to_parse)
        if isinstance(parsed, dict) and "delegated_tasks" in parsed:
            tasks = parsed["delegated_tasks"]
            if isinstance(tasks, list) and all(isinstance(t, dict) for t in tasks):
                return tasks
        if isinstance(parsed, list) and all(isinstance(t, dict) for t in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Try finding a JSON object anywhere in the text
    obj_match = re.search(r"\{[^{}]*\"delegated_tasks\"\s*:\s*\[.*?\]\s*\}", output_text, re.DOTALL)
    if obj_match:
        try:
            parsed = json.loads(obj_match.group(0))
            tasks = parsed.get("delegated_tasks", [])
            if isinstance(tasks, list) and all(isinstance(t, dict) for t in tasks):
                return tasks
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _default_delegation(input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fallback delegation: delegate to all 4 agents with sensible defaults."""
    return [
        {
            "agent_role": "product_strategist",
            "objective": "Inspect the website and define product improvement requirements",
            "priority": 1,
        },
        {
            "agent_role": "workspace_developer",
            "objective": "Improve the marketplace website based on product strategy and feedback",
            "priority": 2,
        },
        {
            "agent_role": "data_specialist",
            "objective": "Identify startup/VC data coverage gaps and refresh top gaps",
            "priority": 3,
        },
        {
            "agent_role": "matching_specialist",
            "objective": "Generate explainable startup-to-VC match shortlist",
            "priority": 4,
        },
    ]


def make_coordinator_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs the coordinator.

    The coordinator analyses feedback, formulates a vision, and returns
    ``delegated_tasks`` so the framework's DelegationHandler injects them
    into the TaskGraph for execution by specialist agents.

    In mock mode the LLM output won't parse as valid JSON, so the agent
    falls back to ``_default_delegation()`` which delegates to all 4 agents.
    """
    from src.workspace.file_tools import (
        read_workspace_file,
        list_workspace_files,
    )

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        task_id = getattr(task_spec, "task_id", "unknown")
        feedback_text = _format_feedback_for_coordinator(input_data)

        crewai_agent = create_master_coordinator(
            llm or get_llm("coordinator"),
            extra_tools=[read_workspace_file, list_workspace_files],
        )
        call_ids: List[str] = []
        _bridge_crewai_tools(crewai_agent, runtime, ROLE_COORDINATOR, task_id, call_ids)

        available = ", ".join(_AVAILABLE_AGENTS)
        crewai_task = Task(
            description=(
                "You are the autonomous coordinator for this cycle.\n\n"
                f"Available agents: {available}\n\n"
                f"Feedback from previous cycle:\n{feedback_text}\n\n"
                "Analyse the current state. Formulate a vision for this cycle. "
                "Then return a JSON object with a 'delegated_tasks' key containing "
                "a list of tasks to delegate. Each task must have 'agent_role' and "
                "'objective' keys. Example:\n"
                '```json\n'
                '{"delegated_tasks": [\n'
                '  {"agent_role": "workspace_developer", "objective": "Improve signup page CTA"},\n'
                '  {"agent_role": "data_specialist", "objective": "Fill data gaps in fintech sector"}\n'
                ']}\n'
                '```'
            ),
            agent=crewai_agent,
            expected_output="JSON with delegated_tasks array.",
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
            logger.warning("coordinator crew failed: %s", exc)
            output_text = f"Coordinator crew error: {exc}"
            reasoning = ""

        # Parse delegated tasks from LLM output, fall back to defaults
        delegated = _parse_delegated_tasks(output_text)
        if delegated is None:
            logger.info("Coordinator output did not parse — using default delegation")
            delegated = _default_delegation(input_data)

        return {
            "output_text": output_text,
            "reasoning": reasoning,
            "tool_calls": call_ids,
            "tokens_used": 0,
            "delegated_tasks": delegated,
        }

    return agent


def make_product_strategist_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs the product strategist.

    Inspects the site, produces improvement requirements, and shares insights.
    """
    from src.workspace.file_tools import (
        read_workspace_file,
        list_workspace_files,
    )

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Inspect the website and define product improvement requirements"
        task_id = getattr(task_spec, "task_id", "unknown")

        crewai_agent = create_product_strategist(
            llm or get_llm("product"),
            extra_tools=[read_workspace_file, list_workspace_files],
        )
        call_ids: List[str] = []
        _bridge_crewai_tools(crewai_agent, runtime, ROLE_PRODUCT_STRATEGIST, task_id, call_ids)

        crewai_task = Task(
            description=(
                f"{objective}\n\n"
                f"Additional input: {input_data}\n\n"
                "List workspace files to understand the current site structure. "
                "Read key pages. Analyse customer feedback and HTTP check results. "
                "Produce specific improvement requirements and share insights with the team."
            ),
            agent=crewai_agent,
            expected_output="Product improvement requirements with prioritised action items.",
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
            logger.warning("product_strategist crew failed: %s", exc)
            output_text = f"Product strategist crew error: {exc}"
            reasoning = ""

        return {
            "output_text": output_text,
            "reasoning": reasoning,
            "tool_calls": call_ids,
            "tokens_used": 0,
        }

    return agent


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


def make_workspace_dev_reviewer_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs a two-agent developer + reviewer crew.

    The crew is sequential:
      1. Developer Agent (with workspace read/write/list tools) builds/improves files.
      2. Reviewer Agent (with workspace read/list tools — NO write) inspects and
         reports PASS or FAIL.

    If the reviewer reports FAIL, a remediation crew runs:
      A. Developer fixes issues based on reviewer feedback.
      B. Reviewer re-inspects and reports final PASS/FAIL.
    """
    from src.workspace.file_tools import (
        read_workspace_file,
        write_workspace_file,
        list_workspace_files,
    )

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Improve the marketplace website"
        task_id = getattr(task_spec, "task_id", "unknown")
        resolved_llm = llm or get_llm("developer")

        # --- Build agents with workspace tools ---
        dev_agent = create_developer_agent(
            resolved_llm,
            extra_tools=[read_workspace_file, write_workspace_file, list_workspace_files],
        )
        reviewer_agent = create_reviewer_agent(
            llm or get_llm("reviewer"),
            extra_tools=[read_workspace_file, list_workspace_files],
        )

        call_ids: List[str] = []
        _bridge_crewai_tools(dev_agent, runtime, ROLE_WORKSPACE_DEVELOPER, task_id, call_ids)
        _bridge_crewai_tools(reviewer_agent, runtime, ROLE_WORKSPACE_DEVELOPER, task_id, call_ids)

        # --- Primary crew: develop then review ---
        dev_task = Task(
            description=(
                f"{objective}\n\n"
                f"Previous feedback and HTTP check results: {input_data}\n\n"
                "List workspace files to understand the current site structure, "
                "read existing files, analyse the feedback, then write improved files. "
                "Focus on CTA clarity, signup flow, navigation, and trust signals."
            ),
            agent=dev_agent,
            expected_output="Summary of website improvements made with files modified.",
        )
        review_task = Task(
            description=(
                "Inspect the workspace files that were just modified. "
                "Check HTML structure, link validity, form completeness, and overall quality. "
                "Report PASS if the site meets quality standards, or FAIL with specific issues."
            ),
            agent=reviewer_agent,
            expected_output="QA verdict: PASS or FAIL with details.",
        )
        crew = Crew(
            agents=[dev_agent, reviewer_agent],
            tasks=[dev_task, review_task],
            process=Process.sequential,
            verbose=False,
            memory=False,
        )
        try:
            result = crew.kickoff()
            output_text = _crew_kickoff_result(result)
            reasoning = _extract_crew_reasoning(result)
        except Exception as exc:
            logger.warning("workspace_developer crew failed: %s", exc)
            output_text = f"Workspace developer crew error: {exc}"
            reasoning = ""
            return {
                "output_text": output_text,
                "reasoning": reasoning,
                "tool_calls": call_ids,
                "tokens_used": 0,
            }

        # --- Remediation crew if reviewer reported FAIL ---
        if "FAIL" in output_text.upper():
            logger.info("Reviewer reported FAIL — running remediation crew")
            fix_task = Task(
                description=(
                    f"The reviewer found issues:\n{output_text}\n\n"
                    "Fix the problems identified above. Re-read the affected files, "
                    "apply corrections, and write the fixed files."
                ),
                agent=dev_agent,
                expected_output="Summary of fixes applied.",
            )
            re_review_task = Task(
                description=(
                    "Re-inspect the workspace files after the developer's fixes. "
                    "Report final PASS or FAIL with details."
                ),
                agent=reviewer_agent,
                expected_output="Final QA verdict: PASS or FAIL with details.",
            )
            remediation_crew = Crew(
                agents=[dev_agent, reviewer_agent],
                tasks=[fix_task, re_review_task],
                process=Process.sequential,
                verbose=False,
                memory=False,
            )
            try:
                remediation_result = remediation_crew.kickoff()
                remediation_text = _crew_kickoff_result(remediation_result)
                remediation_reasoning = _extract_crew_reasoning(remediation_result)
                output_text = f"{output_text}\n\n--- Remediation ---\n{remediation_text}"
                reasoning = f"{reasoning}\n\n--- Remediation ---\n{remediation_reasoning}"
            except Exception as exc:
                logger.warning("workspace_developer remediation crew failed: %s", exc)
                output_text = f"{output_text}\n\nRemediation error: {exc}"

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
    """Register capability labels used by StartupVCAdapter tasks.

    These are passthrough entries: the real tool invocations happen inside
    the CrewAI agents that have their own tool sets.
    """
    for cap_name in (
        CAP_COORDINATION,
        CAP_PRODUCT_STRATEGY,
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

    When *enable_workspace* is True, registers all 5 agents: coordinator,
    product_strategist, workspace_developer, data_specialist, and
    matching_specialist. When False, only data_specialist and
    matching_specialist are registered (unchanged).
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
            agent_id=ROLE_COORDINATOR,
            agent_role=ROLE_COORDINATOR,
            capabilities=[CAP_COORDINATION],
            agent_instance=make_coordinator_agent(runtime, llm=llm),
        )
        router.register_agent(
            agent_id=ROLE_PRODUCT_STRATEGIST,
            agent_role=ROLE_PRODUCT_STRATEGIST,
            capabilities=[CAP_PRODUCT_STRATEGY],
            agent_instance=make_product_strategist_agent(runtime, llm=llm),
        )
        router.register_agent(
            agent_id=ROLE_WORKSPACE_DEVELOPER,
            agent_role=ROLE_WORKSPACE_DEVELOPER,
            capabilities=[CAP_WORKSPACE_READ, CAP_WORKSPACE_WRITE, CAP_WORKSPACE_LIST],
            agent_instance=make_workspace_dev_reviewer_agent(runtime, llm=llm),
        )
