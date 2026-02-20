"""Tests for autonomous run scheduler triggers and dispatch behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.framework.autonomy.run_controller import RunControllerResult
from src.framework.autonomy.run_scheduler import RunScheduler


class _FakeController:
    def __init__(self) -> None:
        self.run_calls = 0
        self.resume_calls: list[str] = []

    def run(self) -> RunControllerResult:
        self.run_calls += 1
        return RunControllerResult(
            run_id="scheduled_run",
            final_status="completed",
            final_action="stop",
            final_reason="max_cycles_reached",
            cycles_completed=1,
        )

    def resume(self, checkpoint_path: str) -> RunControllerResult:
        self.resume_calls.append(checkpoint_path)
        return RunControllerResult(
            run_id="scheduled_run",
            final_status="completed",
            final_action="stop",
            final_reason="max_cycles_reached",
            cycles_completed=1,
            last_checkpoint_path=checkpoint_path,
        )


def test_cron_trigger_dispatches_once_per_minute(tmp_path):
    controller = _FakeController()
    now = datetime(2026, 2, 20, 12, 0, tzinfo=timezone.utc)
    scheduler = RunScheduler(
        run_controller=controller,
        schedules=[{"trigger": "cron", "expression": "* * * * *"}],
        now_fn=lambda: now,
        lock_path=str(tmp_path / "scheduler.lock"),
    )

    first = scheduler.run_once()
    second = scheduler.run_once()

    assert first.triggered is True
    assert first.dispatched is True
    assert first.dispatch_mode == "run"
    assert second.triggered is False
    assert second.dispatched is False
    assert controller.run_calls == 1


def test_resume_dispatch_when_checkpoint_callback_returns_path(tmp_path):
    controller = _FakeController()
    scheduler = RunScheduler(
        run_controller=controller,
        schedules=[{"trigger": "event", "event_name": "ingest.completed"}],
        event_trigger_fn=lambda event_name, schedule: bool(event_name and schedule),
        resume_checkpoint_fn=lambda: "checkpoint.json",
        lock_path=str(tmp_path / "scheduler.lock"),
    )

    result = scheduler.run_once()

    assert result.triggered is True
    assert result.dispatched is True
    assert result.dispatch_mode == "resume"
    assert controller.run_calls == 0
    assert controller.resume_calls == ["checkpoint.json"]


def test_scheduler_skips_when_global_lock_exists(tmp_path):
    controller = _FakeController()
    lock_path = tmp_path / "scheduler.lock"
    lock_path.write_text("busy", encoding="utf-8")
    scheduler = RunScheduler(
        run_controller=controller,
        schedules=[{"trigger": "event", "event_name": "manual"}],
        event_trigger_fn=lambda _event, _schedule: True,
        lock_path=str(lock_path),
        stale_lock_seconds=86_400,
    )

    result = scheduler.run_once()

    assert result.triggered is True
    assert result.dispatched is False
    assert result.dispatch_mode == "locked"
    assert result.reason == "concurrency_lock_active"
    assert controller.run_calls == 0
    assert controller.resume_calls == []
    assert Path(lock_path).exists()
