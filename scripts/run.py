"""Unified project runner for autonomous modes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


def _mode_script(mode: str) -> Path:
    scripts_dir = Path(__file__).resolve().parent
    mapping = {
        "crewai": scripts_dir / "run_simulation.py",
        "web": scripts_dir / "run_web_autonomy.py",
        "framework": scripts_dir / "run_framework_simulation.py",
        "scheduler": scripts_dir / "run_scheduler.py",
        "dashboard": scripts_dir / "live_dashboard.py",
    }
    if mode not in mapping:
        raise ValueError(f"Unsupported mode: {mode}")
    return mapping[mode]


def build_command(mode: str, passthrough_args: List[str]) -> List[str]:
    """Build subprocess command for the selected mode."""
    script_path = _mode_script(mode)
    return [sys.executable, str(script_path), *passthrough_args]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified runner for CrewAI, web-autonomy, framework, scheduler, and dashboard modes.",
    )
    parser.add_argument(
        "--mode",
        choices=["crewai", "web", "framework", "scheduler", "dashboard"],
        default="crewai",
        help="Execution mode (default: crewai)",
    )
    args, passthrough = parser.parse_known_args(argv)

    command = build_command(args.mode, passthrough)
    completed = subprocess.run(command)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
