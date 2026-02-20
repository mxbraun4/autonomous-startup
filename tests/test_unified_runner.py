"""Tests for unified scripts/run.py entrypoint helpers."""

from pathlib import Path

import pytest

from scripts.run import build_command


def test_build_command_for_crewai_mode():
    command = build_command("crewai", ["--iterations", "1"])
    assert command[-2:] == ["--iterations", "1"]
    assert Path(command[1]).name == "run_simulation.py"


def test_build_command_for_web_mode():
    command = build_command("web", ["--iterations", "1"])
    assert command[-2:] == ["--iterations", "1"]
    assert Path(command[1]).name == "run_web_autonomy.py"


def test_build_command_for_dashboard_mode():
    command = build_command("dashboard", ["--port", "8765"])
    assert command[-2:] == ["--port", "8765"]
    assert Path(command[1]).name == "live_dashboard.py"


def test_build_command_for_scheduler_mode():
    command = build_command("scheduler", ["--once"])
    assert command[-1:] == ["--once"]
    assert Path(command[1]).name == "run_scheduler.py"


def test_build_command_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unsupported mode"):
        build_command("unknown", [])
