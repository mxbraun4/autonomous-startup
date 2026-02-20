"""Runtime environment configuration for CrewAI execution."""

from __future__ import annotations

import os
from pathlib import Path

from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def configure_runtime_environment() -> None:
    """Configure writable local paths and mock-mode telemetry defaults."""
    project_root = _project_root()

    local_appdata = (project_root / settings.crewai_local_appdata_dir).resolve()
    local_appdata.mkdir(parents=True, exist_ok=True)

    os.environ["LOCALAPPDATA"] = str(local_appdata)
    os.environ["APPDATA"] = str(local_appdata)
    os.environ["CREWAI_STORAGE_DIR"] = settings.crewai_storage_namespace

    if settings.mock_mode:
        os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
        os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")
        os.environ.setdefault("OTEL_SDK_DISABLED", "true")
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")


def crewai_db_storage_path() -> str:
    """Return writable project-local CrewAI DB storage path."""
    project_root = _project_root()
    storage_dir = (project_root / settings.crewai_db_storage_dir).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    return str(storage_dir)
