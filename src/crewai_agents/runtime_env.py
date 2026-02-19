"""Runtime environment configuration for CrewAI execution."""

from __future__ import annotations

import os
from pathlib import Path

from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_writable_directory(path: Path) -> bool:
    """Return True when directory exists and supports file writes."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _resolve_writable_directory(preferred: Path, fallback: Path) -> Path:
    """Pick preferred directory when writable, otherwise use fallback."""
    if _is_writable_directory(preferred):
        return preferred

    if _is_writable_directory(fallback):
        logger.warning(
            "Directory not writable, falling back to %s (preferred: %s)",
            fallback,
            preferred,
        )
        return fallback

    # Last resort: keep preferred and let downstream fail with a concrete error.
    return preferred


def configure_runtime_environment() -> None:
    """Configure writable local paths and mock-mode telemetry defaults."""
    project_root = _project_root()

    preferred_local_appdata = (project_root / settings.crewai_local_appdata_dir).resolve()
    fallback_local_appdata = (project_root / settings.memory_data_dir / "crewai_local").resolve()
    local_appdata = _resolve_writable_directory(
        preferred=preferred_local_appdata,
        fallback=fallback_local_appdata,
    )

    os.environ["LOCALAPPDATA"] = str(local_appdata)
    os.environ["APPDATA"] = str(local_appdata)
    os.environ["CREWAI_STORAGE_DIR"] = settings.crewai_storage_namespace

    # Keep constrained runs fully local and network-free by default.
    if settings.mock_mode:
        os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
        os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")
        os.environ.setdefault("OTEL_SDK_DISABLED", "true")
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")


def crewai_db_storage_path() -> str:
    """Return writable project-local CrewAI DB storage path."""
    project_root = _project_root()
    preferred_storage = (project_root / settings.crewai_db_storage_dir).resolve()
    fallback_storage = (project_root / settings.memory_data_dir / "crewai_storage").resolve()
    storage_dir = _resolve_writable_directory(
        preferred=preferred_storage,
        fallback=fallback_storage,
    )
    return str(storage_dir)
