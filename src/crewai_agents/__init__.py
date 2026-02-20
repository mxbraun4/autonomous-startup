"""CrewAI-based agent implementation."""
from .tools import (
    # Web collection
    web_search_startups,
    web_search_vcs,
    save_startup,
    save_vc,
    # Database
    get_startups_tool,
    get_vcs_tool,
    get_database_stats,
    # Outreach
    send_outreach_email,
    get_outreach_history,
    content_generator_tool,
    # Analysis
    data_validator_tool,
    analytics_tool,
    register_dynamic_tool,
    list_dynamic_tools,
    execute_dynamic_tool,
    # Consensus memory
    share_insight,
    get_team_insights,
)
from .agents import (
    create_master_coordinator,
    create_data_strategist,
    create_product_strategist,
    create_outreach_strategist,
)
from .crews import (
    create_autonomous_startup_crew,
    run_build_measure_learn_cycle,
    BuildMeasureLearnFlow,
    BuildPhaseOutput,
    MeasurementOutput,
    LearnPhaseOutput,
)

__all__ = [
    # Tools
    'web_search_startups',
    'web_search_vcs',
    'save_startup',
    'save_vc',
    'get_startups_tool',
    'get_vcs_tool',
    'get_database_stats',
    'send_outreach_email',
    'get_outreach_history',
    'content_generator_tool',
    'data_validator_tool',
    'analytics_tool',
    'register_dynamic_tool',
    'list_dynamic_tools',
    'execute_dynamic_tool',
    'share_insight',
    'get_team_insights',
    # Agents
    'create_master_coordinator',
    'create_data_strategist',
    'create_product_strategist',
    'create_outreach_strategist',
    # Crews & Flows
    'create_autonomous_startup_crew',
    'run_build_measure_learn_cycle',
    'BuildMeasureLearnFlow',
    # Structured output models
    'BuildPhaseOutput',
    'MeasurementOutput',
    'LearnPhaseOutput',
]
