"""CrewAI Agents - Convert our Planners to Agents."""

from typing import Optional

from src.crewai_agents.runtime_env import configure_runtime_environment
from src.utils.config import settings

configure_runtime_environment()
from crewai import Agent, LLM
from src.crewai_agents.mock_llm import DeterministicMockLLM
from src.crewai_agents.tools import (
    # Web collection tools
    web_search_startups,
    web_search_vcs,
    fetch_webpage,
    save_startup,
    save_vc,
    # Database tools
    get_startups_tool,
    get_vcs_tool,
    get_database_stats,
    # Analysis tools
    data_validator_tool,
    tool_builder_tool,
    register_dynamic_tool,
    list_dynamic_tools,
    execute_dynamic_tool,
    analytics_tool,
    run_quality_checks_tool,
    # Consensus memory tools
    share_insight,
    get_team_insights,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _with_prompt_override(backstory: str, prompt_override: Optional[str]) -> str:
    override = str(prompt_override or "").strip()
    if not override:
        return backstory
    return f"{backstory}\n\nAutonomous prompt refinement:\n- {override}"


def _normalize_role(role: Optional[str]) -> str:
    text = str(role or "").strip().lower()
    aliases = {
        "strategic_coordinator": "coordinator",
        "master_coordinator": "coordinator",
        "product_strategist": "product",
        "developer_agent": "developer",
        "reviewer": "reviewer",
        "qa": "reviewer",
        "reviewer_agent": "reviewer",
        "engineering": "developer",
        "data": "developer",
        "data_strategist": "developer",
    }
    return aliases.get(text, text)


def _openrouter_model_for_role(role: Optional[str]) -> str:
    normalized = _normalize_role(role)
    attr_map = {
        "coordinator": "coordinator_model",
        "product": "product_model",
        "developer": "developer_model",
        "reviewer": "reviewer_model",
        "manager": "manager_model",
    }

    attrs = []
    mapped = attr_map.get(normalized)
    if mapped:
        attrs.append(mapped)
    if normalized == "manager":
        attrs.append("coordinator_model")
    attrs.append("openrouter_default_model")

    for attr in attrs:
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            return value
    return ""


def _build_openrouter_llm(model: str) -> LLM:
    return LLM(
        model=model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


def get_llm(role: Optional[str] = None) -> LLM | DeterministicMockLLM:
    """Get an LLM instance based on configuration and optional role.

    When ``OPENROUTER_API_KEY`` is configured (and ``MOCK_MODE=false``), role-
    specific models are selected for coordinator/product/developer/reviewer/manager.
    """
    if settings.mock_mode:
        return DeterministicMockLLM()

    if settings.openrouter_api_key:
        model = _openrouter_model_for_role(role)
        if not model:
            raise RuntimeError(
                "OPENROUTER_API_KEY is set but no OpenRouter model could be resolved"
            )
        return _build_openrouter_llm(model)

    if settings.anthropic_api_key:
        return LLM(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
        )

    if settings.openai_api_key:
        return LLM(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )

    raise RuntimeError(
        "No LLM configured: set MOCK_MODE=true or provide OPENROUTER_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY"
    )


def create_master_coordinator(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
) -> Agent:
    """Create the Master Coordinator agent.

    This agent orchestrates the Build-Measure-Learn cycle and delegates
    to specialized strategist agents.

    Args:
        llm: LLM instance to use

    Returns:
        Master Coordinator agent
    """
    backstory = _with_prompt_override(
        '''You are an experienced startup ecosystem operator who has built and scaled
        multiple platforms connecting startups with investors. You understand the importance of
        data quality, product innovation, and effective outreach. You coordinate specialized teams
        to execute on strategy, measure results, and adapt based on learnings.

        Your approach:
        - Start by analyzing the current state and recent performance
        - Decompose high-level goals into specific objectives for each team
        - Delegate to specialists (data, product, outreach) while maintaining strategic oversight
        - Synthesize results and extract learnings to improve next iteration
        ''',
        prompt_override,
    )

    return Agent(
        role='Strategic Coordinator',
        goal='Execute Build-Measure-Learn cycles to continuously improve the startup-VC matching platform',
        backstory=backstory,
        llm=llm or get_llm("coordinator"),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_data_strategist(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
) -> Agent:
    """Create the Data Strategy Expert agent.

    This agent identifies data gaps and coordinates data collection efforts.

    Args:
        llm: LLM instance to use

    Returns:
        Data Strategist agent
    """
    backstory = _with_prompt_override(
        '''You are an expert in data quality, coverage analysis, and gap identification.
        You can quickly spot where data is missing or outdated by comparing current coverage
        against VC investment preferences and market trends.

        Your expertise:
        - Identifying data gaps by analyzing VC interests vs. startup coverage
        - Searching the web to find and collect startup and VC data
        - Prioritizing collection efforts based on business impact
        - Ensuring data quality through validation
        - Tracking data freshness and completeness metrics

        You use web search tools to find startups and VCs, save them to the database,
        and validate data quality. Your workflow:
        1. Check database stats to understand current coverage
        2. Search web for startups/VCs in underrepresented sectors
        3. Save found data to database
        4. Validate data quality
        ''',
        prompt_override,
    )

    return Agent(
        role='Data Strategy Expert',
        goal='Maintain comprehensive, high-quality startup and VC data with zero critical gaps',
        backstory=backstory,
        tools=[
            web_search_startups,
            web_search_vcs,
            fetch_webpage,
            save_startup,
            save_vc,
            get_startups_tool,
            get_vcs_tool,
            get_database_stats,
            data_validator_tool,
            share_insight,
            get_team_insights,
        ],
        llm=llm or get_llm("data"),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_developer_agent(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
) -> Agent:
    """Create the Developer Agent.

    This agent implements and validates platform improvements based on product
    feedback and shared team insights.

    Args:
        llm: LLM instance to use

    Returns:
        Developer agent
    """
    backstory = _with_prompt_override(
        '''You are a pragmatic software engineer responsible for turning product ideas
        into working platform capabilities. You focus on shipping small, testable
        improvements that increase match quality, explainability, and operator efficiency.

        Your approach:
        - Review product feedback and acceptance criteria before building
        - Use shared team insights to understand what changed and why
        - Implement or refine tools/features incrementally
        - Validate behavior and report tradeoffs, risks, and next steps

        You collaborate tightly with the Product Strategy Expert. Product feedback is
        shared through team insight tools, and you use that feedback to drive execution.
        ''',
        prompt_override,
    )

    return Agent(
        role='Developer Agent',
        goal='Implement and improve platform tools/features based on product feedback with reliable, testable iterations',
        backstory=backstory,
        tools=[
            tool_builder_tool,
            register_dynamic_tool,
            list_dynamic_tools,
            execute_dynamic_tool,
            data_validator_tool,
            analytics_tool,
            share_insight,
            get_team_insights,
        ],
        llm=llm or get_llm("developer"),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_product_strategist(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
) -> Agent:
    """Create the Product Strategy Expert agent.

    This agent identifies platform needs and coordinates tool building.

    Args:
        llm: LLM instance to use

    Returns:
        Product Strategist agent
    """
    backstory = _with_prompt_override(
        '''You are a product manager with a strong technical background. You identify
        user needs by analyzing interaction patterns, feedback, and workflow inefficiencies.
        You excel at translating needs into clear product specifications.

        Your approach:
        - Listen to user pain points and observe workflow patterns
        - Identify opportunities where automation or tools can add value
        - Design solutions that are simple, effective, and well-tested
        - Ensure new tools integrate smoothly with existing platform

        You use the tool_builder_tool to create specifications for new tools and features.
        ''',
        prompt_override,
    )

    return Agent(
        role='Product Strategy Expert',
        goal='Build tools and features that enhance platform capabilities and user experience',
        backstory=backstory,
        tools=[
            tool_builder_tool,
            register_dynamic_tool,
            list_dynamic_tools,
            execute_dynamic_tool,
            share_insight,
            get_team_insights,
        ],
        llm=llm or get_llm("product"),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_reviewer_agent(
    llm: LLM = None,
    prompt_override: Optional[str] = None,
) -> Agent:
    """Create the Reviewer (QA) Agent.

    This agent runs strict quality gates (syntax/tests) and blocks broken code
    from reaching strategic review.

    Args:
        llm: LLM instance to use

    Returns:
        Reviewer QA agent
    """
    backstory = _with_prompt_override(
        '''You are a strict software QA reviewer. Your responsibility is to catch
        broken code before it reaches the Strategic Coordinator.

        Your approach:
        - Run deterministic quality checks (syntax and tests)
        - Report exact failures and probable root causes
        - Require fixes from the Developer Agent before sign-off
        - Share QA status and blocking defects with the team

        You focus on correctness and release readiness, not feature ideation.
        ''',
        prompt_override,
    )

    return Agent(
        role='Reviewer (QA) Agent',
        goal='Run syntax and test checks, catch defects early, and block broken code from reaching the coordinator',
        backstory=backstory,
        tools=[
            run_quality_checks_tool,
            share_insight,
            get_team_insights,
        ],
        llm=llm or get_llm("reviewer"),
        verbose=True,
        allow_delegation=False,
        memory=True
    )

