"""Tests for agent prompt override wiring."""

from __future__ import annotations

import pytest


def _require_crewai() -> None:
    try:
        import crewai  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"CrewAI not installed: {exc}")


def test_prompt_override_is_appended_to_agent_backstory():
    _require_crewai()

    from src.crewai_agents.agents import create_developer_agent

    agent = create_developer_agent(prompt_override="Always include one concrete CTA.")
    assert "Always include one concrete CTA." in agent.backstory
