"""Tests for dynamic tool creation and adaptive CrewAI wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _require_crewai() -> None:
    try:
        import crewai  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"CrewAI not installed: {exc}")


def test_tool_builder_auto_registers_and_deploys_dynamic_tool(tmp_path, monkeypatch):
    _require_crewai()

    from src.crewai_agents.tools import (
        clear_dynamic_tool_registry,
        execute_dynamic_tool,
        get_dynamic_tool_registry_snapshot,
        tool_builder_tool,
    )

    monkeypatch.setattr(
        "src.utils.config.settings.generated_tools_dir",
        str(tmp_path / "generated_tools"),
    )
    clear_dynamic_tool_registry()

    spec_json = tool_builder_tool.run(
        tool_idea="Signal Analyzer",
        requirements="Rank startup outreach quality by response likelihood",
    )
    spec = json.loads(spec_json)

    tool_name = spec["tool_name"]
    assert spec["runtime_registration"]["status"] == "registered"
    assert spec["deployment"]["status"] == "deployed"

    snapshot = get_dynamic_tool_registry_snapshot()
    assert tool_name in snapshot

    artifact_path = Path(spec["deployment"]["artifact_path"])
    assert artifact_path.exists()

    execution = json.loads(
        execute_dynamic_tool.run(
            tool_name=tool_name,
            payload_json=json.dumps({"startup_name": "Acme", "sector": "fintech"}),
        )
    )
    assert execution["status"] == "success"
    assert execution["tool_name"] == tool_name
    assert execution["invocation_count"] == 1


def test_prompt_override_is_appended_to_agent_backstory():
    _require_crewai()

    from src.crewai_agents.agents import create_developer_agent

    agent = create_developer_agent(prompt_override="Always include one concrete CTA.")
    assert "Always include one concrete CTA." in agent.backstory
