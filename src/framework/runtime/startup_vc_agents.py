"""CrewAI-backed agent wrappers for the startup-VC domain.

Each agent callable follows the framework contract:
    (task_spec, tools, context) -> Dict[str, Any]

The actual work happens inside a single-task CrewAI crew kickoff so that
the framework's RunController, evaluation gates, checkpointing, adaptive
policy, and diagnostics remain fully in the loop.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.crewai_agents.runtime_env import (
    configure_runtime_environment,
    patch_crewai_storage_paths,
)

configure_runtime_environment()
from crewai import Crew, Task, Process, LLM  # noqa: E402

patch_crewai_storage_paths()

from src.crewai_agents.agents import (  # noqa: E402
    create_data_strategist,
    create_outreach_strategist,
    create_product_strategist,
    get_llm,
)
from src.framework.runtime.capability_registry import CapabilityRegistry  # noqa: E402
from src.framework.runtime.task_router import TaskRouter  # noqa: E402
from src.utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Role names (must match the agent_role values returned by StartupVCAdapter)
# ---------------------------------------------------------------------------
ROLE_DATA_SPECIALIST = "data_specialist"
ROLE_MATCHING_SPECIALIST = "matching_specialist"
ROLE_OUTREACH_SPECIALIST = "outreach_specialist"

# ---------------------------------------------------------------------------
# Capability labels
# ---------------------------------------------------------------------------
CAP_DATA_COVERAGE_ANALYSIS = "data_coverage_analysis"
CAP_DATABASE_WRITE = "database_write"
CAP_MATCH_SCORING = "match_scoring"
CAP_EXPLANATION_GENERATION = "explanation_generation"
CAP_MESSAGE_PERSONALIZATION = "message_personalization"
CAP_CAMPAIGN_TRACKING = "campaign_tracking"


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


def make_data_specialist_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs a CrewAI data crew."""

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        del tools, context
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Analyse startup/VC data coverage gaps"
        constraints = dict(getattr(task_spec, "constraints", {}) or {})
        max_targets = constraints.get("max_targets", 5)

        crewai_agent = create_data_strategist(llm or get_llm("data"))
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
        except Exception as exc:
            logger.warning("data_specialist crew failed: %s", exc)
            output_text = f"Data specialist crew error: {exc}"

        return {
            "output_text": output_text,
            "tool_calls": [],
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
        del tools, context
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Generate startup-to-VC match shortlist"
        constraints = dict(getattr(task_spec, "constraints", {}) or {})
        shortlist_size = constraints.get("shortlist_size", 5)

        crewai_agent = create_product_strategist(llm or get_llm("product"))
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
        except Exception as exc:
            logger.warning("matching_specialist crew failed: %s", exc)
            output_text = f"Matching specialist crew error: {exc}"

        return {
            "output_text": output_text,
            "tool_calls": [],
            "tokens_used": 0,
        }

    return agent


def make_outreach_specialist_agent(
    runtime: Any,
    *,
    llm: Optional[LLM] = None,
) -> Callable[..., Dict[str, Any]]:
    """Return a framework-compatible callable that runs a CrewAI outreach crew."""

    def agent(task_spec: Any, tools: Any, context: Any) -> Dict[str, Any]:
        del tools, context
        input_data = dict(getattr(task_spec, "input_data", {}) or {})
        objective = getattr(task_spec, "objective", "") or "Draft personalized outreach messages"
        constraints = dict(getattr(task_spec, "constraints", {}) or {})
        message_count = constraints.get("message_count", 5)

        crewai_agent = create_outreach_strategist(llm or get_llm("outreach"))
        crewai_task = Task(
            description=(
                f"{objective}\n\n"
                f"Message count target: {message_count}\n"
                f"Additional input: {input_data}"
            ),
            agent=crewai_agent,
            expected_output="Outreach campaign report with personalized messages, quality metrics, and tracking.",
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
        except Exception as exc:
            logger.warning("outreach_specialist crew failed: %s", exc)
            output_text = f"Outreach specialist crew error: {exc}"

        return {
            "output_text": output_text,
            "tool_calls": [],
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
    """Register the 6 capability labels used by StartupVCAdapter tasks.

    These are passthrough entries: the real tool invocations happen inside
    the CrewAI agents that have their own tool sets.
    """
    for cap_name in (
        CAP_DATA_COVERAGE_ANALYSIS,
        CAP_DATABASE_WRITE,
        CAP_MATCH_SCORING,
        CAP_EXPLANATION_GENERATION,
        CAP_MESSAGE_PERSONALIZATION,
        CAP_CAMPAIGN_TRACKING,
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
) -> None:
    """Register the 3 startup-VC agents with the task router."""

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
    router.register_agent(
        agent_id=ROLE_OUTREACH_SPECIALIST,
        agent_role=ROLE_OUTREACH_SPECIALIST,
        capabilities=[CAP_MESSAGE_PERSONALIZATION, CAP_CAMPAIGN_TRACKING],
        agent_instance=make_outreach_specialist_agent(runtime, llm=llm),
    )
