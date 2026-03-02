"""Test CrewAI integration."""
import json
from unittest.mock import patch, MagicMock

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


# ---------------------------------------------------------------------------
# Web search tools — Serper.dev integration
# ---------------------------------------------------------------------------

def test_web_search_startups_no_api_key():
    """web_search_startups returns status=skipped when SERPER_API_KEY is absent."""
    with patch("src.crewai_agents.tools.settings") as mock_settings:
        mock_settings.serper_api_key = None
        from src.crewai_agents.tools import web_search_startups

        result = json.loads(web_search_startups.run(query="fintech startups", sector="fintech"))
        assert result["status"] == "skipped"
        assert "SERPER_API_KEY" in result.get("reason", "")


def test_web_search_vcs_no_api_key():
    """web_search_vcs returns status=skipped when SERPER_API_KEY is absent."""
    with patch("src.crewai_agents.tools.settings") as mock_settings:
        mock_settings.serper_api_key = None
        from src.crewai_agents.tools import web_search_vcs

        result = json.loads(web_search_vcs.run(query="seed VCs", focus_sector="fintech"))
        assert result["status"] == "skipped"


def test_web_search_startups_with_mocked_serper():
    """web_search_startups returns structured results from mocked Serper response."""
    mock_serper_response = {
        "organic": [
            {"title": "Acme Fintech", "link": "https://acme.com", "snippet": "Acme is a fintech startup."},
            {"title": "Beta AI", "link": "https://beta.ai", "snippet": "Beta builds AI tools."},
        ]
    }
    with patch("src.crewai_agents.tools.settings") as mock_settings, \
         patch("src.crewai_agents.tools.requests.post") as mock_post:
        mock_settings.serper_api_key = "test-key"
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_serper_response
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from src.crewai_agents.tools import web_search_startups

        result = json.loads(web_search_startups.run(query="fintech startups", sector="fintech"))
        assert result["status"] == "success"
        assert result["result_count"] == 2
        assert result["results"][0]["title"] == "Acme Fintech"
        mock_post.assert_called_once()


def test_web_search_vcs_with_mocked_serper():
    """web_search_vcs returns structured results from mocked Serper response."""
    mock_serper_response = {
        "organic": [
            {"title": "Alpha Ventures", "link": "https://alpha.vc", "snippet": "Seed-stage VC."},
        ]
    }
    with patch("src.crewai_agents.tools.settings") as mock_settings, \
         patch("src.crewai_agents.tools.requests.post") as mock_post:
        mock_settings.serper_api_key = "test-key"
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_serper_response
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from src.crewai_agents.tools import web_search_vcs

        result = json.loads(web_search_vcs.run(query="seed VCs", focus_sector="fintech"))
        assert result["status"] == "success"
        assert result["result_count"] == 1
        assert result["results"][0]["title"] == "Alpha Ventures"


def test_fetch_webpage_with_mocked_http():
    """fetch_webpage returns stripped text from mocked HTTP response."""
    html = "<html><body><h1>Hello</h1><p>World of startups</p></body></html>"
    with patch("src.crewai_agents.tools.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        from src.crewai_agents.tools import fetch_webpage

        result = json.loads(fetch_webpage.run(url="https://example.com", extract_type="startups"))
        assert result["status"] == "ok"
        assert "Hello" in result["text"]
        assert "World of startups" in result["text"]
        # HTML tags should be stripped
        assert "<h1>" not in result["text"]
        assert result["extract_type"] == "startups"


def test_data_strategist_agent_creation():
    """Data Strategy Expert agent can be created with expected properties."""
    from src.crewai_agents.agents import create_data_strategist

    agent = create_data_strategist()
    assert agent.role == "Data Strategy Expert"
    assert len(agent.tools) > 0
    tool_names = [getattr(t, "name", "") for t in agent.tools]
    assert any("Startup" in n for n in tool_names), f"Expected startup tool, got {tool_names}"
    assert any("Data Collection" in n for n in tool_names), f"Expected data collection tool, got {tool_names}"


def test_run_data_collection_no_api_key():
    """run_data_collection returns status=skipped when SERPER_API_KEY is absent."""
    with patch("src.crewai_agents.tools.settings") as mock_settings:
        mock_settings.serper_api_key = None
        from src.crewai_agents.tools import run_data_collection

        result = json.loads(run_data_collection.run(sectors="fintech"))
        assert result["status"] == "skipped"


def test_run_data_collection_with_mocked_serper():
    """run_data_collection searches, saves to DB, and returns sector counts."""
    mock_serper_response = {
        "organic": [
            {"title": "Acme Fintech", "link": "https://acme.com", "snippet": "A fintech startup."},
        ]
    }
    with patch("src.crewai_agents.tools.settings") as mock_settings, \
         patch("src.crewai_agents.tools.requests.post") as mock_post:
        mock_settings.serper_api_key = "test-key"
        mock_settings.startup_db_path = ":memory:"
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_serper_response
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from src.crewai_agents.tools import run_data_collection

        result = json.loads(run_data_collection.run(sectors="fintech"))
        assert result["status"] == "success"
        assert len(result["by_sector"]) == 1
        assert result["by_sector"][0]["sector"] == "fintech"
        # At least startup and VC searches (2 calls per sector)
        assert mock_post.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, '-v'])
