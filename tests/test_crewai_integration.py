"""Test CrewAI integration."""
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_crewai_imports():
    """Test that CrewAI modules can be imported."""
    try:
        from crewai import Agent, Task, Crew, Process
        from crewai.tools import tool
        assert True
    except ImportError as e:
        pytest.skip(f"CrewAI not installed: {e}")


def test_tools_creation():
    """Test that tools can be created."""
    from src.crewai_agents.tools import (
        scraper_tool,
        content_generator_tool,
        tool_builder_tool,
        data_validator_tool,
        analytics_tool
    )

    # Verify tools are callable
    assert callable(scraper_tool)
    assert callable(content_generator_tool)
    assert callable(tool_builder_tool)
    assert callable(data_validator_tool)
    assert callable(analytics_tool)


def test_scraper_tool_execution():
    """Test scraper tool can execute."""
    import json
    from src.crewai_agents.tools import scraper_tool

    # Call scraper tool
    result_json = scraper_tool(sector="fintech", stage="seed")

    # Parse result
    result = json.loads(result_json)

    assert result['status'] == 'success'
    assert result['sector'] == 'fintech'
    assert result['stage'] == 'seed'
    assert 'count' in result
    assert 'startups' in result


def test_content_generator_tool():
    """Test content generator tool."""
    import json
    from src.crewai_agents.tools import content_generator_tool

    result_json = content_generator_tool(
        startup_name="TestStartup",
        sector="fintech",
        recent_news="Series A funding"
    )

    result = json.loads(result_json)

    assert 'message' in result
    assert 'personalization_score' in result
    assert 'TestStartup' in result['message']
    assert result['personalization_score'] > 0


def test_agents_creation():
    """Test that agents can be created."""
    from src.crewai_agents.agents import (
        create_master_coordinator,
        create_data_strategist,
        create_product_strategist,
        create_outreach_strategist
    )

    # Create agents
    coordinator = create_master_coordinator()
    data_agent = create_data_strategist()
    product_agent = create_product_strategist()
    outreach_agent = create_outreach_strategist()

    # Verify agents have required properties
    assert coordinator.role == 'Strategic Coordinator'
    assert data_agent.role == 'Data Strategy Expert'
    assert product_agent.role == 'Product Strategy Expert'
    assert outreach_agent.role == 'Outreach Strategy Expert'

    # Verify agents have tools
    assert len(data_agent.tools) > 0
    assert len(outreach_agent.tools) > 0


def test_crew_creation():
    """Test that crew can be created."""
    from src.crewai_agents.crews import create_autonomous_startup_crew

    crew = create_autonomous_startup_crew(verbose=0)

    # Verify crew has agents and tasks
    assert len(crew.agents) == 4
    assert len(crew.tasks) > 0


@pytest.mark.slow
def test_single_iteration():
    """Test running a single Build-Measure-Learn iteration."""
    from src.crewai_agents.crews import run_build_measure_learn_cycle

    # Run just 1 iteration with minimal verbosity
    results = run_build_measure_learn_cycle(iterations=1, verbose=0)

    # Verify results structure
    assert 'iterations' in results
    assert len(results['iterations']) == 1
    assert 'metrics_evolution' in results
    assert len(results['metrics_evolution']) == 1

    # Verify metrics
    metrics = results['metrics_evolution'][0]
    assert 'response_rate' in metrics
    assert 'meeting_rate' in metrics
    assert metrics['response_rate'] >= 0


if __name__ == "__main__":
    pytest.main([__file__, '-v'])
