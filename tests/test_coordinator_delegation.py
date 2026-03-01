"""Tests for coordinator delegation helpers in startup_vc_agents."""

from __future__ import annotations

import pytest

from src.framework.runtime.startup_vc_agents import (
    _default_delegation,
    _format_feedback_for_coordinator,
    _parse_delegated_tasks,
)


# ---------------------------------------------------------------------------
# _parse_delegated_tasks
# ---------------------------------------------------------------------------


class TestParseDelegatedTasksJsonCodeFence:
    """Parse delegated_tasks from a ```json code fence."""

    def test_parse_json_code_fence(self) -> None:
        text = (
            "Here is my plan:\n"
            "```json\n"
            '{"delegated_tasks": [\n'
            '  {"agent_role": "workspace_developer", "objective": "Improve CTA"},\n'
            '  {"agent_role": "data_specialist", "objective": "Fill gaps"}\n'
            "]}\n"
            "```\n"
            "That's it."
        )
        result = _parse_delegated_tasks(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["agent_role"] == "workspace_developer"
        assert result[1]["agent_role"] == "data_specialist"


class TestParseDelegatedTasksRawJson:
    """Parse delegated_tasks from raw JSON (no code fence)."""

    def test_parse_raw_json(self) -> None:
        text = '{"delegated_tasks": [{"agent_role": "workspace_developer", "objective": "Score matches"}]}'
        result = _parse_delegated_tasks(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["agent_role"] == "workspace_developer"


class TestParseDelegatedTasksGarbage:
    """Return None for garbage / unparseable text."""

    def test_parse_garbage(self) -> None:
        assert _parse_delegated_tasks("This is just random text with no JSON.") is None
        assert _parse_delegated_tasks("") is None
        assert _parse_delegated_tasks(None) is None


class TestParseDelegatedTasksMockOutput:
    """Mock LLM output (DeterministicMockLLM) won't parse — should return None."""

    def test_parse_mock_output(self) -> None:
        mock_text = (
            "I'll analyze the current state of the workspace and formulate a "
            "strategic vision for this cycle. Based on the available information..."
        )
        assert _parse_delegated_tasks(mock_text) is None


class TestParseDelegatedTasksBareArray:
    """Parse a bare JSON array of tasks."""

    def test_parse_bare_array(self) -> None:
        text = '[{"agent_role": "product_strategist", "objective": "Define requirements"}]'
        result = _parse_delegated_tasks(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["agent_role"] == "product_strategist"


# ---------------------------------------------------------------------------
# _default_delegation
# ---------------------------------------------------------------------------


class TestDefaultDelegation:
    """_default_delegation returns all 3 agent roles with correct priorities."""

    def test_default_delegation_returns_three_agents(self) -> None:
        result = _default_delegation({})
        assert len(result) == 3

        roles = [t["agent_role"] for t in result]
        assert "product_strategist" in roles
        assert "workspace_developer" in roles
        assert "data_specialist" in roles

    def test_default_delegation_priorities_ascending(self) -> None:
        result = _default_delegation({})
        priorities = [t["priority"] for t in result]
        assert priorities == sorted(priorities), "Priorities should be in ascending order"

    def test_default_delegation_all_have_objectives(self) -> None:
        result = _default_delegation({})
        for task in result:
            assert "objective" in task
            assert len(task["objective"]) > 0


# ---------------------------------------------------------------------------
# _format_feedback_for_coordinator
# ---------------------------------------------------------------------------


class TestFormatFeedbackEmpty:
    """No feedback available returns a default message."""

    def test_format_empty(self) -> None:
        result = _format_feedback_for_coordinator({})
        assert "No feedback" in result or "first cycle" in result


class TestFormatFeedbackWithHTTPChecks:
    """HTTP checks appear in formatted output."""

    def test_format_with_http_checks(self) -> None:
        data = {
            "previous_http_checks": {
                "http_landing_score": 0.9,
                "http_signup_score": 0.7,
            }
        }
        result = _format_feedback_for_coordinator(data)
        assert "HTTP check" in result
        assert "http_landing_score" in result
        assert "0.9" in result


class TestFormatFeedbackWithCustomerMetrics:
    """Customer metrics appear in formatted output."""

    def test_format_with_customer_metrics(self) -> None:
        data = {
            "customer_metrics": {
                "founder_interested_rate": 0.25,
                "meeting_conversion_rate": 0.10,
            }
        }
        result = _format_feedback_for_coordinator(data)
        assert "Customer simulation" in result
        assert "founder_interested_rate" in result


class TestFormatFeedbackWithPreviousResults:
    """Previous results appear in formatted output."""

    def test_format_with_previous_results(self) -> None:
        data = {
            "previous_results": {
                "success_rate": 0.8,
                "response_rate": 0.3,
            }
        }
        result = _format_feedback_for_coordinator(data)
        assert "Previous cycle" in result
        assert "success_rate" in result


class TestFormatFeedbackCombined:
    """All three feedback sources combined."""

    def test_format_combined(self) -> None:
        data = {
            "previous_http_checks": {"http_landing_score": 1.0},
            "customer_metrics": {"founder_interested_rate": 0.5},
            "previous_results": {"success_rate": 1.0},
        }
        result = _format_feedback_for_coordinator(data)
        assert "HTTP check" in result
        assert "Customer simulation" in result
        assert "Previous cycle" in result
