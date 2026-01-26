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
    analytics_tool
)
from .agents import (
    create_master_coordinator,
    create_data_strategist,
    create_product_strategist,
    create_outreach_strategist
)
from .crews import (
    create_autonomous_startup_crew,
    run_build_measure_learn_cycle
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
    # Agents
    'create_master_coordinator',
    'create_data_strategist',
    'create_product_strategist',
    'create_outreach_strategist',
    # Crews
    'create_autonomous_startup_crew',
    'run_build_measure_learn_cycle'
]
