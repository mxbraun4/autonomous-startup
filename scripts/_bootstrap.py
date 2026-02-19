"""Shared bootstrap helpers for repository scripts."""

from __future__ import annotations

import sys
from pathlib import Path


def add_repo_root_to_path(script_file: str) -> Path:
    """Ensure repository root is on sys.path and return it."""
    repo_root = Path(script_file).resolve().parent.parent
    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return repo_root


def configure_stdio_utf8() -> None:
    """Normalize stdio encoding for robust console output on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
