"""Sandboxed file tools for workspace-scoped reads, writes, and listings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

from crewai.tools import tool

# ---------------------------------------------------------------------------
# Module-level workspace root
# ---------------------------------------------------------------------------

_workspace_root: Optional[Path] = None


def configure_workspace_root(path: Union[str, Path]) -> None:
    """Set the module-level workspace root directory."""
    global _workspace_root
    _workspace_root = Path(path).resolve()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_safe_path(relative_path: str) -> Path:
    """Resolve *relative_path* inside the workspace root and validate it.

    Raises
    ------
    RuntimeError
        If the workspace root has not been configured yet.
    ValueError
        If the resolved path escapes the workspace root.
    """
    if _workspace_root is None:
        raise RuntimeError("Workspace root is not configured. Call configure_workspace_root first.")

    candidate = (_workspace_root / relative_path).resolve()
    # .relative_to raises ValueError when candidate is not under root
    candidate.relative_to(_workspace_root)
    return candidate


# ---------------------------------------------------------------------------
# Implementation functions (plain helpers — easy to test directly)
# ---------------------------------------------------------------------------


def _read_impl(file_path: str) -> dict:
    """Return a dict with the result of reading *file_path*."""
    try:
        resolved = _resolve_safe_path(file_path)
    except ValueError:
        return {"status": "denied", "reason": "path_escape"}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    try:
        content = resolved.read_text(encoding="utf-8")
        return {"status": "ok", "path": str(resolved), "content": content}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _write_impl(file_path: str, content: str) -> dict:
    """Return a dict with the result of writing *content* to *file_path*."""
    try:
        resolved = _resolve_safe_path(file_path)
    except ValueError:
        return {"status": "denied", "reason": "path_escape"}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return {"status": "ok", "path": str(resolved), "bytes_written": len(content.encode("utf-8"))}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _list_impl(subdirectory: str = "") -> dict:
    """Return a dict with a recursive listing of workspace files."""
    try:
        resolved = _resolve_safe_path(subdirectory) if subdirectory else _resolve_safe_path(".")
    except ValueError:
        return {"status": "denied", "reason": "path_escape"}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    try:
        files: list[str] = []
        for entry in resolved.rglob("*"):
            if entry.is_file():
                rel = entry.relative_to(_workspace_root)
                # Exclude anything under a .versions directory
                if ".versions" in rel.parts:
                    continue
                files.append(str(rel))
        return {"status": "ok", "files": sorted(files)}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# CrewAI @tool decorated functions
# ---------------------------------------------------------------------------

@tool
def read_workspace_file(file_path: str) -> str:
    """Read a file from the workspace directory."""
    return json.dumps(_read_impl(file_path))


@tool
def write_workspace_file(file_path: str, content: str) -> str:
    """Write (or overwrite) a file inside the workspace directory."""
    return json.dumps(_write_impl(file_path, content))


@tool
def list_workspace_files(subdirectory: str = "") -> str:
    """Recursively list all files in the workspace (excluding .versions/)."""
    return json.dumps(_list_impl(subdirectory))


# Disable CrewAI's per-tool result cache for workspace tools.  The default
# cache_function returns True (= always cache), which causes reads after
# writes to return stale content for the same file_path argument.
_NO_CACHE = lambda _args=None, _result=None: False  # noqa: E731
read_workspace_file.cache_function = _NO_CACHE
write_workspace_file.cache_function = _NO_CACHE
list_workspace_files.cache_function = _NO_CACHE
