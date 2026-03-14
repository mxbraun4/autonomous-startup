"""Runtime environment configuration for CrewAI execution."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)
_RESOLVED_LOCAL_APPDATA: Path | None = None
_RESOLVED_DB_STORAGE: Path | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def configure_runtime_environment() -> None:
    """Configure writable local paths and mock-mode telemetry defaults."""
    project_root = _project_root()

    global _RESOLVED_LOCAL_APPDATA
    if _RESOLVED_LOCAL_APPDATA is None:
        _RESOLVED_LOCAL_APPDATA = _resolve_writable_directory(
            preferred=(project_root / settings.crewai_local_appdata_dir).resolve(),
            fallback=(project_root / "data/crewai_local_runtime").resolve(),
        )
    local_appdata = _RESOLVED_LOCAL_APPDATA

    os.environ["LOCALAPPDATA"] = str(local_appdata)
    os.environ["APPDATA"] = str(local_appdata)
    os.environ["CREWAI_STORAGE_DIR"] = settings.crewai_storage_namespace

    if settings.mock_mode:
        os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
        os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")
        os.environ.setdefault("OTEL_SDK_DISABLED", "true")
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

    # Best-effort patch to keep CrewAI sqlite/chroma files in the workspace.
    patch_crewai_storage_paths()

    # Patch CrewAI's native tool loop to be more generous with text responses.
    from src.crewai_agents.patch_crewai import patch_crewai_native_tool_loop
    patch_crewai_native_tool_loop()


def crewai_db_storage_path() -> str:
    """Return writable project-local CrewAI DB storage path."""
    global _RESOLVED_DB_STORAGE
    if _RESOLVED_DB_STORAGE is not None:
        return str(_RESOLVED_DB_STORAGE)
    project_root = _project_root()
    _RESOLVED_DB_STORAGE = _resolve_writable_directory(
        preferred=(project_root / settings.crewai_db_storage_dir).resolve(),
        fallback=(project_root / "data/crewai_storage_runtime").resolve(),
    )
    return str(_RESOLVED_DB_STORAGE)


def patch_crewai_storage_paths() -> str:
    """Patch CrewAI path resolvers to a workspace-writable directory.

    CrewAI modules often import ``db_storage_path`` by value:
    ``from crewai.utilities.paths import db_storage_path``.
    Updating only ``crewai.utilities.paths.db_storage_path`` is not enough when
    those modules are already imported, so this patches known modules too.
    """
    storage_path = crewai_db_storage_path()

    def _patched_db_storage_path() -> str:
        return storage_path

    try:
        from crewai.utilities import paths as crewai_paths

        crewai_paths.db_storage_path = _patched_db_storage_path  # type: ignore[attr-defined]
    except Exception:
        return storage_path

    module_names = [
        "crewai.memory.storage.kickoff_task_outputs_storage",
        "crewai.memory.storage.ltm_sqlite_storage",
        "crewai.memory.storage.rag_storage",
        "crewai.flow.persistence.sqlite",
        "crewai.events.listeners.tracing.utils",
        "crewai.rag.chromadb.constants",
    ]

    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue

        if hasattr(module, "db_storage_path"):
            try:
                setattr(module, "db_storage_path", _patched_db_storage_path)
            except Exception:
                pass

        # Some modules cache a constant path at import time.
        if hasattr(module, "DEFAULT_STORAGE_PATH"):
            try:
                setattr(module, "DEFAULT_STORAGE_PATH", storage_path)
            except Exception:
                pass

    logger.info("CrewAI storage path patched to workspace directory: %s", storage_path)
    return storage_path


def _resolve_writable_directory(preferred: Path, fallback: Path) -> Path:
    """Return a writable directory, falling back if preferred is not writable."""
    if _can_write_to_directory(preferred):
        return preferred
    logger.warning(
        "Preferred CrewAI directory not writable: %s. Falling back to %s",
        preferred,
        fallback,
    )
    fallback.mkdir(parents=True, exist_ok=True)
    if _can_write_to_directory(fallback):
        return fallback
    raise PermissionError(
        f"CrewAI runtime directory not writable: preferred={preferred} fallback={fallback}"
    )


def _can_write_to_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False
