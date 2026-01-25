"""CrewAI Agents - Convert our Planners to Agents."""
from typing import Optional, List
from crewai import Agent, LLM
from src.crewai_agents.tools import (
    scraper_tool,
    data_validator_tool,
    content_generator_tool,
    tool_builder_tool,
    analytics_tool
)
from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_llm() -> LLM:
    """Get LLM instance based on configuration.

    Returns:
        LLM instance (uses fake LLM in mock mode)
    """
    if settings.mock_mode:
        # Use a fake LLM for mock mode
        # Set a dummy API key to satisfy CrewAI's requirements
        import os
        os.environ['OPENAI_API_KEY'] = 'fake-key-for-mock-mode'

        return LLM(
            model="gpt-4o-mini",
            temperature=0.7
        )

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

    # Default to fake LLM
    import os
    os.environ['OPENAI_API_KEY'] = 'fake-key-for-mock-mode'
    return LLM(model="gpt-4o-mini")


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
        - Prioritizing collection efforts based on business impact
        - Ensuring data quality through validation
        - Tracking data freshness and completeness metrics

        You use the scraper_tool to collect new startup data and data_validator_tool to ensure
        quality before adding it to the database.
        ''',
        tools=[scraper_tool, data_validator_tool],
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
        - Crafting highly personalized messages that reference specific achievements
        - Timing campaigns for maximum engagement (Tuesday-Thursday mornings)
        - Learning from past campaign results to optimize future outreach
        - Understanding what VCs look for and how to position startups effectively

        You analyze past campaigns to identify what worked, use content_generator_tool to create
        personalized messages, and use analytics_tool to measure campaign performance.
        ''',
        tools=[content_generator_tool, analytics_tool],
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
