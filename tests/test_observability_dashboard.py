"""Tests for live dashboard snapshot helpers."""

from __future__ import annotations

from pathlib import Path

from src.framework.contracts import EvaluationResult, GateDecision, TaskResult, TaskSpec, ToolCall
from src.framework.observability.dashboard import (
    build_run_snapshot,
    build_snapshot_from_ndjson,
    load_events_from_ndjson,
)
from src.framework.observability.logger import EventLogger
from src.framework.types import TaskStatus, ToolCallStatus


def test_load_events_from_ndjson_returns_empty_for_missing_path(tmp_path):
    missing = tmp_path / "missing.ndjson"
    events = load_events_from_ndjson(missing)
    assert events == []


def test_build_run_snapshot_selects_latest_run_and_summarizes_counts(tmp_path):
    log_path = tmp_path / "events.ndjson"
    logger = EventLogger(persist_path=str(log_path))

    logger.emit("run_start", {"run_id": "run_old"})
    logger.emit("run_end", {"run_id": "run_old"})

    task_spec = TaskSpec(
        run_id="run_new",
        cycle_id=1,
        task_id="task_1",
        objective="Explore localhost product flow",
        agent_role="web_explorer",
    )
    task_result = TaskResult(
        run_id="run_new",
        cycle_id=1,
        task_id="task_1",
        task_status=TaskStatus.COMPLETED,
    )
    tool_call = ToolCall(
        run_id="run_new",
        cycle_id=1,
        tool_name="browser_navigate",
        capability="browser_navigate",
        caller_task_id="task_1",
        call_status=ToolCallStatus.SUCCESS,
    )
    evaluation = EvaluationResult(
        run_id="run_new",
        cycle_id=1,
        gates=[
            GateDecision(
                run_id="run_new",
                cycle_id=1,
                gate_name="reliability",
                gate_status="pass",
                recommended_action="continue",
            )
        ],
        overall_status="pass",
        recommended_action="continue",
        summary="pass",
    )

    logger.emit("run_start", {"run_id": "run_new"})
    logger.emit("cycle_start", {"run_id": "run_new", "cycle_id": 1})
    logger.emit("task_started", task_spec)
    logger.emit("tool_called", tool_call)
    logger.emit("task_completed", task_result)
    logger.emit("gate_decision", evaluation)
    logger.emit(
        "cycle_end",
        {
            "run_id": "run_new",
            "cycle_id": 1,
            "total_tasks": 1,
            "completed_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "evaluation_status": "pass",
            "evaluation_action": "continue",
            "termination_action": "stop",
            "termination_reason": "max_cycles_reached",
        },
    )
    logger.emit("run_end", {"run_id": "run_new"})

    events = load_events_from_ndjson(log_path, max_events=500)
    snapshot = build_run_snapshot(events)

    assert snapshot["selected_run_id"] == "run_new"
    assert snapshot["run"]["status"] == "completed"
    assert snapshot["tasks"]["started"] == 1
    assert snapshot["tasks"]["completed"] == 1
    assert snapshot["tasks"]["failed"] == 0
    assert snapshot["tools"]["called"] == 1
    assert snapshot["cycle_count"] == 1
    assert snapshot["latest_gate"]["overall_status"] == "pass"
    assert snapshot["latest_gate"]["recommended_action"] == "continue"
    assert snapshot["active_tasks"] == []
    assert snapshot["cycles"][0]["cycle_id"] == 1


def test_build_snapshot_from_ndjson_reports_active_task(tmp_path):
    log_path = tmp_path / "events.ndjson"
    logger = EventLogger(persist_path=str(log_path))

    task_spec = TaskSpec(
        run_id="run_live",
        cycle_id=3,
        task_id="task_active",
        objective="Run tests in workspace",
        agent_role="web_validator",
    )

    logger.emit("run_start", {"run_id": "run_live"})
    logger.emit("cycle_start", {"run_id": "run_live", "cycle_id": 3})
    logger.emit("task_started", task_spec)

    snapshot = build_snapshot_from_ndjson(Path(log_path), run_id="run_live")
    assert snapshot["selected_run_id"] == "run_live"
    assert snapshot["run"]["status"] == "running"
    assert snapshot["tasks"]["in_progress"] == 1
    assert len(snapshot["active_tasks"]) == 1
    assert snapshot["active_tasks"][0]["task_id"] == "task_active"
