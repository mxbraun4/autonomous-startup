"""Tests for the dispatch task tool factory (make_dispatch_task_tool)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def _require_crewai() -> None:
    try:
        import crewai  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"CrewAI not installed: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_factory(llm=None, prompt_override=None, extra_tools=None):
    """Minimal agent factory for tests — returns a MagicMock agent."""
    agent = MagicMock()
    agent.role = "DummyAgent"
    return agent


def _make_registry():
    return {
        "product_strategist": {
            "factory": _dummy_factory,
            "llm": None,
            "extra_tools": None,
            "prompt_override": "",
        },
        "developer": {
            "factory": _dummy_factory,
            "llm": None,
            "extra_tools": None,
            "prompt_override": "",
        },
        "reviewer": {
            "factory": _dummy_factory,
            "llm": None,
            "extra_tools": None,
            "prompt_override": "",
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unknown_role_rejected():
    """Dispatching to an unknown role returns rejection with available roles."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit)

    result = json.loads(dispatch.run(agent_role="nonexistent", task_description="do something"))
    assert result["status"] == "rejected"
    assert "nonexistent" in result["reason"]
    assert sorted(result["available_roles"]) == ["developer", "product_strategist", "reviewer"]
    # No events should be emitted for rejected dispatch
    emit.assert_not_called()


def _crew_patches():
    """Context manager that patches crewai.Crew, crewai.Task, crewai.Process for dispatch tests."""
    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "mock result"

    crew_patch = patch("crewai.Crew")
    task_patch = patch("crewai.Task")
    process_patch = patch("crewai.Process")

    return crew_patch, task_patch, process_patch, mock_crew_output


def test_max_dispatches_enforced():
    """After max_dispatches, further calls are rejected."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=2)

    crew_p, task_p, proc_p, mock_output = _crew_patches()

    with crew_p as MockCrew, task_p, proc_p:
        MockCrew.return_value.kickoff.return_value = mock_output

        # First two should succeed
        r1 = json.loads(dispatch.run(agent_role="developer", task_description="task 1"))
        assert r1["status"] == "success"
        assert r1["dispatches_remaining"] == 1

        r2 = json.loads(dispatch.run(agent_role="reviewer", task_description="task 2"))
        assert r2["status"] == "success"
        assert r2["dispatches_remaining"] == 0

    # Third should be rejected (no Crew mock needed)
    r3 = json.loads(dispatch.run(agent_role="developer", task_description="task 3"))
    assert r3["status"] == "rejected"
    assert "Max dispatches" in r3["reason"]
    assert r3["dispatches_used"] == 2


def test_events_emitted_for_dispatch_and_result():
    """Both dispatch and dispatch_result events are emitted."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=3)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "agent result text"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p:
        MockCrew.return_value.kickoff.return_value = mock_crew_output
        dispatch.run(agent_role="developer", task_description="build page")

    # Should have 2 emit calls: dispatch + dispatch_result
    assert emit.call_count == 2

    # Each call: emit("agent_exchange", {...})
    assert emit.call_args_list[0][0][0] == "agent_exchange"
    assert emit.call_args_list[1][0][0] == "agent_exchange"

    dispatch_event = emit.call_args_list[0][0][1]
    assert dispatch_event["exchange_type"] == "dispatch"
    assert dispatch_event["to_agent"] == "developer"

    result_event = emit.call_args_list[1][0][1]
    assert result_event["exchange_type"] == "dispatch_result"
    assert result_event["from_agent"] == "developer"


def test_result_truncation():
    """Results longer than result_truncation are truncated."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=3, result_truncation=50)

    long_output = "x" * 200
    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: long_output

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p:
        MockCrew.return_value.kickoff.return_value = mock_crew_output
        result = json.loads(dispatch.run(agent_role="developer", task_description="task"))

    assert result["status"] == "success"
    assert result["truncated"] is True
    assert len(result["result"]) == 50


def test_dispatch_history_accumulates():
    """Each dispatch is recorded in the history returned with every call."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "result"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p:
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        r1 = json.loads(dispatch.run(agent_role="product_strategist", task_description="spec"))
        assert len(r1["dispatch_history"]) == 1
        assert r1["dispatch_history"][0]["agent_role"] == "product_strategist"

        r2 = json.loads(dispatch.run(agent_role="developer", task_description="build"))
        assert len(r2["dispatch_history"]) == 2
        assert r2["dispatch_history"][1]["agent_role"] == "developer"

        r3 = json.loads(dispatch.run(agent_role="reviewer", task_description="review"))
        assert len(r3["dispatch_history"]) == 3
        roles = [h["agent_role"] for h in r3["dispatch_history"]]
        assert roles == ["product_strategist", "developer", "reviewer"]


def test_crew_exception_returns_error():
    """When the inner crew raises, the dispatch returns an error message (after retry)."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=3)

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools.time"):
        MockCrew.return_value.kickoff.side_effect = RuntimeError("LLM timeout")
        result = json.loads(dispatch.run(agent_role="developer", task_description="task"))

    assert result["status"] == "success"  # dispatch itself succeeded
    assert "[dispatch error after retry]" in result["result"]
    assert "LLM timeout" in result["result"]


def test_separate_factory_calls_have_independent_state():
    """Two factory calls produce tools with independent counters and history."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch_a, _pa, _get_count_a, _get_history_a = make_dispatch_task_tool(registry, emit, max_dispatches=2)
    dispatch_b, _pb, _get_count_b, _get_history_b = make_dispatch_task_tool(registry, emit, max_dispatches=2)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "result"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p:
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        r_a = json.loads(dispatch_a.run(agent_role="developer", task_description="task"))
        assert r_a["dispatches_remaining"] == 1

        # dispatch_b should still have its full budget
        r_b = json.loads(dispatch_b.run(agent_role="developer", task_description="task"))
        assert r_b["dispatches_remaining"] == 1
        assert len(r_b["dispatch_history"]) == 1  # independent history


def test_dispatch_result_written_to_consensus_memory():
    """Successful dispatch auto-shares result to consensus memory."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=3)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "developer built the page"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl") as mock_share:
        MockCrew.return_value.kickoff.return_value = mock_crew_output
        result = json.loads(dispatch.run(agent_role="developer", task_description="build landing"))

    assert result["status"] == "success"
    mock_share.assert_called_once()
    call_kw = mock_share.call_args.kwargs
    assert call_kw["key"] == "dispatch.developer.1"
    assert "developer built the page" in call_kw["value"]
    assert call_kw["source_agent"] == "developer"


def test_extra_context_prepended_to_dispatch():
    """extra_context from prior iterations is injected into every dispatch description."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(
        registry, emit, max_dispatches=3,
        extra_context="[learning hint] fix navigation links",
    )

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "done"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p as MockTask, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output
        dispatch.run(agent_role="developer", task_description="build page")

    # The Task constructor should have received a description with preamble
    task_call_kwargs = MockTask.call_args
    description = task_call_kwargs[1]["description"] if "description" in (task_call_kwargs[1] or {}) else task_call_kwargs[0][0]
    assert "get_team_insights" in description
    assert "[learning hint] fix navigation links" in description
    assert "build page" in description


# ---------------------------------------------------------------------------
# New tests: retry, role instructions, history accessor
# ---------------------------------------------------------------------------


def test_retry_success_on_first_failure():
    """When kickoff raises once, retry succeeds and result is returned."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=3)

    mock_retry_output = MagicMock()
    mock_retry_output.__str__ = lambda self: "retry succeeded"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"), \
         patch("src.crewai_agents.tools.time") as mock_time:
        # First kickoff raises, second (retry) succeeds
        MockCrew.return_value.kickoff.side_effect = [
            RuntimeError("BadRequestError"),
            mock_retry_output,
        ]
        result = json.loads(dispatch.run(agent_role="developer", task_description="build"))

    assert result["status"] == "success"
    assert "retry succeeded" in result["result"]
    # Budget slot consumed only once
    assert _get_count() == 1
    mock_time.sleep.assert_called_once_with(2)


def test_retry_both_fail():
    """When both kickoff and retry fail, error message includes 'after retry'."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=3)

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"), \
         patch("src.crewai_agents.tools.time"):
        MockCrew.return_value.kickoff.side_effect = RuntimeError("persistent error")
        result = json.loads(dispatch.run(agent_role="developer", task_description="build"))

    assert result["status"] == "success"
    assert "[dispatch error after retry]" in result["result"]
    assert "persistent error" in result["result"]
    assert _get_count() == 1


def test_role_instructions_injected():
    """Developer and reviewer dispatches include TOOL INSTRUCTIONS in the task description."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "done"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p as MockTask, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        # Dispatch to developer
        dispatch.run(agent_role="developer", task_description="build page")
        dev_call = MockTask.call_args
        dev_desc = dev_call[1].get("description", dev_call[0][0] if dev_call[0] else "")
        assert "TOOL INSTRUCTIONS" in dev_desc
        assert "write_workspace_file" in dev_desc

        # Dispatch to reviewer
        dispatch.run(agent_role="reviewer", task_description="review page")
        rev_call = MockTask.call_args
        rev_desc = rev_call[1].get("description", rev_call[0][0] if rev_call[0] else "")
        assert "TOOL INSTRUCTIONS" in rev_desc
        assert "review_workspace_files" in rev_desc


def test_history_accessor_returns_dispatch_history():
    """The _get_dispatch_history accessor returns independent copy of history list."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, _parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    # Before any dispatch, history is empty
    assert _get_history() == []

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "result"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        dispatch.run(agent_role="developer", task_description="task 1")
        dispatch.run(agent_role="reviewer", task_description="task 2")

    history = _get_history()
    assert len(history) == 2
    assert history[0]["agent_role"] == "developer"
    assert history[1]["agent_role"] == "reviewer"
    # Verify it's a copy (mutating doesn't affect internal state)
    history.clear()
    assert len(_get_history()) == 2


# ---------------------------------------------------------------------------
# Parallel dispatch tests
# ---------------------------------------------------------------------------


def test_parallel_dispatch_two_developers():
    """dispatch_parallel runs two developer tasks concurrently and returns aggregated results."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    _dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "page built"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        result = json.loads(parallel.run(
            agent_role_1="developer", task_description_1="Build page A",
            agent_role_2="developer", task_description_2="Build page B",
        ))

    assert result["status"] == "success"
    assert result["parallel_count"] == 2
    assert len(result["results"]) == 2
    assert all(r["status"] == "success" for r in result["results"])
    assert all(r["agent_role"] == "developer" for r in result["results"])
    assert result["dispatches_remaining"] == 3
    assert _get_count() == 2
    assert len(_get_history()) == 2


def test_parallel_dispatch_three_tasks():
    """dispatch_parallel runs three tasks when the optional third slot is used."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    _dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "done"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        result = json.loads(parallel.run(
            agent_role_1="developer", task_description_1="Build page A",
            agent_role_2="developer", task_description_2="Build page B",
            agent_role_3="developer", task_description_3="Build page C",
        ))

    assert result["status"] == "success"
    assert result["parallel_count"] == 3
    assert len(result["results"]) == 3
    assert result["dispatches_remaining"] == 2
    assert _get_count() == 3


def test_parallel_dispatch_third_slot_skipped():
    """When agent_role_3 is empty, only two tasks are dispatched."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    _dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "done"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        result = json.loads(parallel.run(
            agent_role_1="developer", task_description_1="Build page A",
            agent_role_2="developer", task_description_2="Build page B",
            agent_role_3="", task_description_3="",
        ))

    assert result["parallel_count"] == 2
    assert _get_count() == 2


def test_parallel_dispatch_budget_enforcement():
    """dispatch_parallel rejects batch when budget is insufficient."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    _dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=1)

    result = json.loads(parallel.run(
        agent_role_1="developer", task_description_1="Build page A",
        agent_role_2="developer", task_description_2="Build page B",
    ))

    assert result["status"] == "rejected"
    assert "Not enough budget" in result["reason"]
    # No dispatches should have been consumed
    assert _get_count() == 0


def test_parallel_dispatch_invalid_role_rejected():
    """dispatch_parallel rejects entire batch if any role is unknown."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    _dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    result = json.loads(parallel.run(
        agent_role_1="developer", task_description_1="Build page A",
        agent_role_2="nonexistent", task_description_2="Do something",
    ))

    assert result["status"] == "rejected"
    assert "nonexistent" in result["reason"]
    assert _get_count() == 0


def test_parallel_dispatch_one_task_fails():
    """When one parallel task fails, others still succeed and results are aggregated."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    _dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=5)

    call_count = [0]
    mock_success = MagicMock()
    mock_success.__str__ = lambda self: "built page"

    def _kickoff_side_effect():
        call_count[0] += 1
        if call_count[0] <= 2:
            # First crew kickoff fails, retry also fails (for first task)
            raise RuntimeError("LLM timeout")
        return mock_success

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"), \
         patch("src.crewai_agents.tools.time"):
        MockCrew.return_value.kickoff.side_effect = _kickoff_side_effect

        result = json.loads(parallel.run(
            agent_role_1="developer", task_description_1="Build page A",
            agent_role_2="developer", task_description_2="Build page B",
        ))

    assert result["status"] == "success"
    assert result["parallel_count"] == 2
    # Both complete (one with error text, one with success)
    assert len(result["results"]) == 2
    assert _get_count() == 2


def test_parallel_and_sequential_share_budget():
    """Sequential and parallel dispatches share the same budget counter."""
    _require_crewai()
    from src.crewai_agents.tools import make_dispatch_task_tool

    registry = _make_registry()
    emit = MagicMock()
    dispatch, parallel, _get_count, _get_history = make_dispatch_task_tool(registry, emit, max_dispatches=4)

    mock_crew_output = MagicMock()
    mock_crew_output.__str__ = lambda self: "done"

    crew_p, task_p, proc_p, _ = _crew_patches()
    with crew_p as MockCrew, task_p, proc_p, \
         patch("src.crewai_agents.tools._share_insight_impl"):
        MockCrew.return_value.kickoff.return_value = mock_crew_output

        # Use 1 sequential dispatch
        r1 = json.loads(dispatch.run(agent_role="product_strategist", task_description="spec"))
        assert r1["dispatches_remaining"] == 3

        # Use 2 parallel dispatches
        r2 = json.loads(parallel.run(
            agent_role_1="developer", task_description_1="Build A",
            agent_role_2="developer", task_description_2="Build B",
        ))
        assert r2["dispatches_remaining"] == 1

    assert _get_count() == 3

    # Only 1 remaining — trying to parallel dispatch 2 should fail
    r3 = json.loads(parallel.run(
        agent_role_1="reviewer", task_description_1="Review A",
        agent_role_2="reviewer", task_description_2="Review B",
    ))
    assert r3["status"] == "rejected"
    assert "Not enough budget" in r3["reason"]
