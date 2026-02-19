"""Tests for Layer H event logging and timelines."""

import json

from src.framework.contracts import EvaluationResult, GateDecision, TaskResult, TaskSpec, ToolCall
from src.framework.observability import EVENT_TYPES_REQUIRED, EventLogger, TimelineBuilder
from src.framework.types import TaskStatus, ToolCallStatus


def test_event_logger_emits_and_derives_required_classes(tmp_path):
    log_path = tmp_path / "events.ndjson"
    logger = EventLogger(persist_path=str(log_path))

    task_spec = TaskSpec(task_id="t1", run_id="run_obs", cycle_id=1, objective="demo")
    task_result = TaskResult(
        task_id="t1",
        run_id="run_obs",
        cycle_id=1,
        task_status=TaskStatus.COMPLETED,
    )
    task_failed = TaskResult(
        task_id="t2",
        run_id="run_obs",
        cycle_id=1,
        task_status=TaskStatus.FAILED,
    )
    tool_called = ToolCall(
        tool_name="tool_a",
        capability="cap",
        run_id="run_obs",
        cycle_id=1,
        call_status=ToolCallStatus.SUCCESS,
    )
    tool_denied = ToolCall(
        tool_name="tool_b",
        capability="cap",
        run_id="run_obs",
        cycle_id=1,
        call_status=ToolCallStatus.DENIED,
        denied_reason="Denied by policy engine",
    )
    evaluation = EvaluationResult(
        run_id="run_obs",
        cycle_id=1,
        gates=[GateDecision(gate_name="reliability", gate_status="pass")],
        overall_status="pass",
        recommended_action="continue",
        summary="ok",
    )

    logger.emit("run_start", {"run_id": "run_obs"})
    logger.emit("cycle_start", {"run_id": "run_obs", "cycle_id": 1})
    logger.emit("task_scheduled", task_spec)
    logger.emit("task_started", task_spec)
    logger.emit("task_completed", task_result)
    logger.emit("task_failed", task_failed)
    logger.emit("tool_called", tool_called)
    logger.emit("tool_denied", tool_denied)
    logger.emit("gate_decision", evaluation)
    logger.emit(
        "checkpoint_saved",
        {"run_id": "run_obs", "cycle_id": 1, "checkpoint_path": "cp.json"},
    )
    logger.emit(
        "checkpoint_restored",
        {"run_id": "run_obs", "cycle_id": 1, "checkpoint_path": "cp.json"},
    )
    logger.emit(
        "cycle_end",
        {"run_id": "run_obs", "cycle_id": 1, "termination_action": "continue"},
    )
    logger.emit("run_end", {"run_id": "run_obs"})

    events = logger.get_events(run_id="run_obs")
    event_types = {event.event_type for event in events}
    assert EVENT_TYPES_REQUIRED.issubset(event_types)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == logger.size
    # Verify persisted line is valid JSON.
    json.loads(lines[0])


def test_timeline_builder_groups_events_by_cycle():
    logger = EventLogger()
    logger.emit("run_start", {"run_id": "run_tl"})
    logger.emit("cycle_start", {"run_id": "run_tl", "cycle_id": 1})
    logger.emit("task_started", {"run_id": "run_tl", "cycle_id": 1, "task_id": "a"})
    logger.emit("cycle_end", {"run_id": "run_tl", "cycle_id": 1})
    logger.emit("run_end", {"run_id": "run_tl"})

    timeline = TimelineBuilder.build(logger.get_events(run_id="run_tl"))
    assert timeline.run_id == "run_tl"
    assert timeline.total_events == 5
    assert timeline.event_counts["cycle_start"] == 1
    assert timeline.event_counts["cycle_end"] == 1
    assert 1 in timeline.cycles
    assert len(timeline.cycles[1]) == 3
    assert len(timeline.unscoped_events) == 2  # run_start/run_end

