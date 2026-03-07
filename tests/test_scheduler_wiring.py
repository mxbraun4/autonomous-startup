"""Tests for scheduler/web wiring helpers."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_scheduler import _build_resume_checkpoint_reader, _load_schedules_file
from scripts.run_web_autonomy import build_web_arg_parser, create_web_run_controller


def test_load_schedules_file_supports_list_and_object(tmp_path):
    list_file = tmp_path / "schedules_list.json"
    list_file.write_text(
        json.dumps([{"trigger": "cron", "expression": "*/5 * * * *"}]),
        encoding="utf-8",
    )
    object_file = tmp_path / "schedules_object.json"
    object_file.write_text(
        json.dumps(
            {
                "schedules": [
                    {"trigger": "metric_drop", "metric": "completion_rate", "threshold": 0.8}
                ]
            }
        ),
        encoding="utf-8",
    )

    list_loaded = _load_schedules_file(list_file)
    object_loaded = _load_schedules_file(object_file)

    assert list_loaded == [{"trigger": "cron", "expression": "*/5 * * * *"}]
    assert object_loaded[0]["trigger"] == "metric_drop"


def test_resume_reader_uses_latest_checkpoint_once(tmp_path):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    cp1 = checkpoint_dir / "run_a_cycle_1_step_1.json"
    cp1.write_text(json.dumps({"run_id": "run_a"}), encoding="utf-8")

    reader = _build_resume_checkpoint_reader(
        "",
        checkpoint_dir=str(checkpoint_dir),
        resume_latest_checkpoint=True,
    )

    first = reader()
    second = reader()
    assert first == str(cp1.resolve())
    assert second is None

    cp2 = checkpoint_dir / "run_a_cycle_2_step_5.json"
    cp2.write_text(json.dumps({"run_id": "run_a"}), encoding="utf-8")
    third = reader()
    assert third == str(cp2.resolve())


def test_create_web_run_controller_applies_policy_and_schedule_overrides(tmp_path):
    parser = build_web_arg_parser(add_help=False)
    args = parser.parse_args(
        [
            "--run-id",
            "wiring_test_run",
            "--workspace",
            str(tmp_path),
            "--events-path",
            str(tmp_path / "events.ndjson"),
            "--checkpoint-dir",
            str(tmp_path / "checkpoints"),
            "--schedule-json",
            '{"trigger":"cron","expression":"*/15 * * * *"}',
            "--auto-resume-on-pause",
            "--pause-cooldown-seconds",
            "2",
            "--adaptive-policy-reliability-streak",
            "5",
            "--diagnostics-window-size",
            "55",
        ]
    )

    controller, _events, _run_id, _template_name = create_web_run_controller(args)

    run_config = controller._run_config
    assert run_config.schedules == [{"trigger": "cron", "expression": "*/15 * * * *"}]
    assert run_config.policies["auto_resume_on_pause"] is True
    assert run_config.policies["pause_cooldown_seconds"] == 2.0
    assert run_config.policies["adaptive_policy_reliability_streak"] == 5
    assert run_config.policies["diagnostics_window_size"] == 55
