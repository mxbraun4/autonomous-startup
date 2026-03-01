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
        get_startups_tool,
        tool_builder_tool,
        data_validator_tool,
        run_quality_checks_tool,
        register_dynamic_tool,
        list_dynamic_tools,
        execute_dynamic_tool,
    )

    # CrewAI @tool decorator produces Tool objects with a .run() method
    for t in [
        get_startups_tool,
        tool_builder_tool,
        data_validator_tool,
        run_quality_checks_tool,
        register_dynamic_tool,
        list_dynamic_tools,
        execute_dynamic_tool,
    ]:
        assert hasattr(t, "run"), f"{t} missing .run() method"


def test_get_startups_tool_execution():
    """Test get_startups_tool can execute."""
    import json
    from src.crewai_agents.tools import get_startups_tool

    # CrewAI tools are invoked via .run()
    result_json = get_startups_tool.run(sector="fintech", stage="seed")

    result = json.loads(result_json)

    assert result['status'] == 'success'
    assert result['sector'] == 'fintech'
    assert result['stage'] == 'seed'
    assert 'count' in result
    assert 'startups' in result


def test_run_quality_checks_tool_syntax_only():
    """Test QA tool contract in syntax-only mode."""
    import json
    from src.crewai_agents.tools import run_quality_checks_tool

    result_json = run_quality_checks_tool.run(
        paths_csv="src/crewai_agents",
        pytest_targets_csv="",
        run_pytest=False,
        timeout_seconds=30,
    )
    result = json.loads(result_json)

    assert "status" in result
    assert "qa_gate_passed" in result
    assert "syntax" in result
    assert "pytest" in result
    assert result["pytest"]["pytest_status"] == "disabled"


def test_agents_creation():
    """Test that agents can be created."""
    from src.crewai_agents.agents import (
        create_master_coordinator,
        create_developer_agent,
        create_reviewer_agent,
        create_product_strategist,
    )

    # Create agents
    coordinator = create_master_coordinator()
    developer_agent = create_developer_agent()
    reviewer_agent = create_reviewer_agent()
    product_agent = create_product_strategist()

    # Verify agents have required properties
    assert coordinator.role == 'Strategic Coordinator'
    assert developer_agent.role == 'Developer Agent'
    assert reviewer_agent.role == 'Reviewer (QA) Agent'
    assert product_agent.role == 'Product Strategy Expert'

    # Verify agents have tools
    assert len(developer_agent.tools) > 0
    assert len(reviewer_agent.tools) > 0
    assert len(product_agent.tools) > 0


def test_crew_creation():
    """Test that crew can be created."""
    from src.crewai_agents.crews import create_autonomous_startup_crew

    crew = create_autonomous_startup_crew(verbose=0)

    # Verify crew has agents and tasks
    assert len(crew.agents) == 4
    assert len(crew.tasks) > 0


@pytest.mark.slow
def test_single_iteration():
    """Test running a single Build-Measure-Learn iteration.

    Requires a valid LLM API key (OpenAI or Anthropic).  Skipped automatically
    when running in mock mode without real credentials.
    """
    from src.crewai_agents.crews import run_build_measure_learn_cycle
    from src.utils.config import settings

    if (
        settings.mock_mode
        and not settings.openrouter_api_key
        and not settings.openai_api_key
        and not settings.anthropic_api_key
    ):
        pytest.skip("No LLM API key configured; skipping live iteration test")

    # Run just 1 iteration with minimal verbosity
    results = run_build_measure_learn_cycle(iterations=1, verbose=0)

    # Verify results structure
    assert 'iterations' in results
    assert len(results['iterations']) == 1
    assert 'metrics_evolution' in results
    assert len(results['metrics_evolution']) == 1

    # Verify metrics
    metrics = results['metrics_evolution'][0]
    assert 'qa_passed' in metrics
    assert 'task_count' in metrics


if __name__ == "__main__":
    pytest.main([__file__, '-v'])
