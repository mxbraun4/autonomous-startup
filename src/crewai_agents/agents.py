"""CrewAI Agents - Convert our Planners to Agents."""

from typing import Optional, List

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
    # Outreach tools
    send_outreach_email,
    get_outreach_history,
    record_outreach_response,
    # Analysis tools
    scraper_tool,
    data_validator_tool,
    content_generator_tool,
    tool_builder_tool,
    analytics_tool
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_llm() -> LLM | DeterministicMockLLM:
    """Get LLM instance based on configuration.

    Returns:
        LLM instance (uses fake LLM in mock mode)
    """
    if settings.mock_mode:
        # Fully local deterministic model; no network/API dependency.
        return DeterministicMockLLM()

    # Use Anthropic Claude as primary
    if settings.anthropic_api_key:
        return LLM(
            model="anthropic/claude-3-haiku-20240307",
            api_key=settings.anthropic_api_key
        )

    # Fallback to OpenAI
    if settings.openai_api_key:
        return LLM(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key
        )

    logger.warning(
        "No API keys configured with MOCK_MODE=false; falling back to deterministic mock LLM."
    )
    return DeterministicMockLLM()


def create_master_coordinator(llm: LLM = None) -> Agent:
    """Create the Master Coordinator agent.

    This agent orchestrates the Build-Measure-Learn cycle and delegates
    to specialized strategist agents.

    Args:
        llm: LLM instance to use

    Returns:
        Master Coordinator agent
    """
    return Agent(
        role='Strategic Coordinator',
        goal='Execute Build-Measure-Learn cycles to continuously improve the startup-VC matching platform',
        backstory='''You are an experienced startup ecosystem operator who has built and scaled
        multiple platforms connecting startups with investors. You understand the importance of
        data quality, product innovation, and effective outreach. You coordinate specialized teams
        to execute on strategy, measure results, and adapt based on learnings.

        Your approach:
        - Start by analyzing the current state and recent performance
        - Decompose high-level goals into specific objectives for each team
        - Delegate to specialists (data, product, outreach) while maintaining strategic oversight
        - Synthesize results and extract learnings to improve next iteration
        ''',
        llm=llm or get_llm(),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_data_strategist(llm: LLM = None) -> Agent:
    """Create the Data Strategy Expert agent.

    This agent identifies data gaps and coordinates data collection efforts.

    Args:
        llm: LLM instance to use

    Returns:
        Data Strategist agent
    """
    return Agent(
        role='Data Strategy Expert',
        goal='Maintain comprehensive, high-quality startup and VC data with zero critical gaps',
        backstory='''You are an expert in data quality, coverage analysis, and gap identification.
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
        tools=[
            web_search_startups,
            web_search_vcs,
            fetch_webpage,
            save_startup,
            save_vc,
            get_startups_tool,
            get_vcs_tool,
            get_database_stats,
            data_validator_tool
        ],
        llm=llm or get_llm(),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_product_strategist(llm: LLM = None) -> Agent:
    """Create the Product Strategy Expert agent.

    This agent identifies platform needs and coordinates tool building.

    Args:
        llm: LLM instance to use

    Returns:
        Product Strategist agent
    """
    return Agent(
        role='Product Strategy Expert',
        goal='Build tools and features that enhance platform capabilities and user experience',
        backstory='''You are a product manager with a strong technical background. You identify
        user needs by analyzing interaction patterns, feedback, and workflow inefficiencies.
        You excel at translating needs into clear product specifications.

        Your approach:
        - Listen to user pain points and observe workflow patterns
        - Identify opportunities where automation or tools can add value
        - Design solutions that are simple, effective, and well-tested
        - Ensure new tools integrate smoothly with existing platform

        You use the tool_builder_tool to create specifications for new tools and features.
        ''',
        tools=[tool_builder_tool],
        llm=llm or get_llm(),
        verbose=True,
        allow_delegation=True,
        memory=True
    )


def create_outreach_strategist(llm: LLM = None) -> Agent:
    """Create the Outreach Strategy Expert agent.

    This agent optimizes outreach campaigns and learns from results.

    Args:
        llm: LLM instance to use

    Returns:
        Outreach Strategist agent
    """
    return Agent(
        role='Outreach Strategy Expert',
        goal='Achieve 35%+ response rate on startup outreach campaigns through personalization and learning',
        backstory='''You are a growth expert specializing in B2B outreach and startup-investor
        matchmaking. You understand what makes outreach effective: personalization, timing,
        relevance, and clear value proposition.

        Your expertise:
        - Accessing startup data from the database to find outreach targets
        - Crafting highly personalized messages that reference specific achievements
        - Timing campaigns for maximum engagement (Tuesday-Thursday mornings)
        - Learning from past campaign results to optimize future outreach
        - Understanding what VCs look for and how to position startups effectively

        You retrieve startups from the database, analyze past campaigns to identify what worked,
        use content_generator_tool to create personalized messages, and use analytics_tool
        to measure campaign performance.
        ''',
        tools=[
            get_startups_tool,
            get_vcs_tool,
            content_generator_tool,
            send_outreach_email,
            get_outreach_history,
            record_outreach_response,
            analytics_tool
        ],
        llm=llm or get_llm(),
        verbose=True,
        allow_delegation=True,
        memory=True  # Critical: remembers past campaign results
    )


def create_all_agents(llm: Optional[LLM] = None) -> dict:
    """Create all agents.

    Args:
        llm: LLM instance to use for all agents

    Returns:
        Dict mapping agent names to agent instances
    """
    return {
        'coordinator': create_master_coordinator(llm),
        'data_strategist': create_data_strategist(llm),
        'product_strategist': create_product_strategist(llm),
        'outreach_strategist': create_outreach_strategist(llm)
    }
