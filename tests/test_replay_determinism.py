"""Tests for deterministic replay traces and diff reports."""

from src.framework.observability import EventLogger, ReplayEngine


def _emit_trace(logger: EventLogger, run_id: str, *, fail: bool = False) -> None:
    logger.emit("run_start", {"run_id": run_id})
    logger.emit("cycle_start", {"run_id": run_id, "cycle_id": 1})
    logger.emit("task_started", {"run_id": run_id, "cycle_id": 1, "task_id": "t1"})
    if fail:
        logger.emit(
            "task_failed",
            {"run_id": run_id, "cycle_id": 1, "task_id": "t1", "task_status": "failed"},
        )
    else:
        logger.emit(
            "task_completed",
            {"run_id": run_id, "cycle_id": 1, "task_id": "t1", "task_status": "completed"},
        )
    logger.emit(
        "tool_called",
        {
            "run_id": run_id,
            "cycle_id": 1,
            "tool_name": "search",
            "call_status": "success",
        },
    )
    logger.emit(
        "gate_decision",
        {
            "run_id": run_id,
            "cycle_id": 1,
            "overall_status": "pass" if not fail else "fail",
            "recommended_action": "continue" if not fail else "pause",
        },
    )
    logger.emit(
        "cycle_end",
        {
            "run_id": run_id,
            "cycle_id": 1,
            "termination_action": "continue" if not fail else "pause",
            "termination_reason": "continue" if not fail else "gate_pause",
            "evaluation_status": "pass" if not fail else "fail",
        },
    )
    logger.emit("run_end", {"run_id": run_id})


def test_replay_hash_is_equal_for_equivalent_runs():
    logger = EventLogger()
    _emit_trace(logger, "run_a", fail=False)
    _emit_trace(logger, "run_b", fail=False)

    replay = ReplayEngine(logger)
    diff = replay.compare_runs("run_a", "run_b")
    assert diff.is_equal is True
    assert diff.mismatch_indices == []
    assert diff.left_hash == diff.right_hash


def test_replay_diff_detects_behavior_regression():
    logger = EventLogger()
    _emit_trace(logger, "run_a", fail=False)
    _emit_trace(logger, "run_c", fail=True)

    replay = ReplayEngine(logger)
    diff = replay.compare_runs("run_a", "run_c")
    assert diff.is_equal is False
    assert len(diff.mismatch_indices) > 0
    assert diff.left_hash != diff.right_hash
    assert "traces_differ" in diff.summary

