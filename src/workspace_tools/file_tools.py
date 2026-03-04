"""Sandboxed file tools for workspace-scoped reads, writes, and listings."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
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
                # Exclude anything under a .versions directory and feedback.json
                if ".versions" in rel.parts:
                    continue
                if rel.name == "feedback.db":
                    continue
                files.append(str(rel))
        return {"status": "ok", "files": sorted(files)}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# SQL safety regexes
# ---------------------------------------------------------------------------

# Block ATTACH/DETACH/LOAD_EXTENSION — these can escape the sandbox.
_BLOCKED_SQL_RE = re.compile(
    r"\b(ATTACH|DETACH|LOAD_EXTENSION)\b",
    re.IGNORECASE,
)

# Block dangerous PRAGMAs that could leak keys or attach databases.
_BLOCKED_PRAGMA_RE = re.compile(
    r"\bPRAGMA\s+(key|rekey|cipher|kdf_iter|cipher_page_size|"
    r"cipher_use_hmac|cipher_hmac_algorithm|attach_key)\b",
    re.IGNORECASE,
)

_MAX_SELECT_ROWS = 200


def _run_sql_impl(db_name: str, query: str, params: str = "[]") -> dict:
    """Execute a SQL query against a workspace SQLite database.

    Parameters
    ----------
    db_name:
        Relative path to the ``.db`` file inside the workspace (e.g.
        ``feedback.db`` or ``sub/nested.db``).
    query:
        SQL statement to execute.
    params:
        JSON-encoded list of bind parameters (default ``"[]"``).

    Returns
    -------
    dict
        ``{"status": "ok", "rows": [...]}`` for SELECT, or
        ``{"status": "ok", "rowcount": N}`` for DML/DDL.
    """
    # Validate .db extension
    if not db_name.endswith(".db"):
        return {"status": "error", "reason": "db_name must end with .db"}

    # Resolve and sandbox-check the path
    try:
        resolved = _resolve_safe_path(db_name)
    except ValueError:
        return {"status": "denied", "reason": "path_escape"}
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}

    # Block dangerous SQL
    if _BLOCKED_SQL_RE.search(query):
        return {"status": "denied", "reason": "blocked_sql: ATTACH/DETACH/LOAD_EXTENSION not allowed"}
    if _BLOCKED_PRAGMA_RE.search(query):
        return {"status": "denied", "reason": "blocked_sql: dangerous PRAGMA not allowed"}

    # Parse params
    try:
        param_list = json.loads(params)
        if not isinstance(param_list, list):
            return {"status": "error", "reason": "params must be a JSON list"}
    except (json.JSONDecodeError, TypeError) as exc:
        return {"status": "error", "reason": f"invalid params JSON: {exc}"}

    # Ensure parent directory exists
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}

    # Execute
    try:
        conn = sqlite3.connect(str(resolved))
        try:
            cursor = conn.execute(query, param_list)
            # Determine if this is a SELECT-like query
            if cursor.description is not None:
                rows = cursor.fetchmany(_MAX_SELECT_ROWS)
                col_names = [desc[0] for desc in cursor.description]
                result_rows = [dict(zip(col_names, row)) for row in rows]
                conn.commit()
                return {"status": "ok", "rows": result_rows}
            else:
                conn.commit()
                return {"status": "ok", "rowcount": cursor.rowcount}
        finally:
            conn.close()
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# HTTP check helpers
# ---------------------------------------------------------------------------


def _check_http_impl(pages: str = "") -> dict:
    """Start a temporary server, run HTTP checks, and return results.

    Parameters
    ----------
    pages:
        Comma-separated list of pages to check (e.g. ``"index.html,about.html"``).
        If empty, runs the full standard check suite (landing, signup, navigation).
    """
    if _workspace_root is None:
        return {"status": "error", "reason": "Workspace root is not configured. Call configure_workspace_root first."}

    # Lazy imports to avoid circular dependencies
    from src.workspace_tools.server import WorkspaceServer
    from src.simulation.http_checks import WorkspaceHTTPChecker

    server = WorkspaceServer(str(_workspace_root), port=0)
    try:
        base_url = server.start()
        checker = WorkspaceHTTPChecker(base_url)

        if pages.strip():
            # Check specific pages
            results: dict = {}
            for page in [p.strip() for p in pages.split(",") if p.strip()]:
                results[page] = checker.check_page_loads(page)
            return {"status": "ok", "pages": results}
        else:
            # Full standard suite
            all_checks = checker.run_all_checks()
            return {"status": "ok", **all_checks}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Workspace versioning helpers
# ---------------------------------------------------------------------------


def _snapshot_impl(cycle_id: int) -> dict:
    """Take a versioned snapshot of the workspace."""
    if _workspace_root is None:
        return {"status": "error", "reason": "Workspace root is not configured. Call configure_workspace_root first."}

    from src.workspace_tools.versioning import WorkspaceVersioning

    try:
        v = WorkspaceVersioning(_workspace_root)
        result = v.snapshot(cycle_id)
        return {"status": "ok", **result}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _restore_impl(cycle_id: int) -> dict:
    """Restore the workspace from a snapshot."""
    if _workspace_root is None:
        return {"status": "error", "reason": "Workspace root is not configured. Call configure_workspace_root first."}

    from src.workspace_tools.versioning import WorkspaceVersioning

    try:
        v = WorkspaceVersioning(_workspace_root)
        return v.restore(cycle_id)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _list_snapshots_impl() -> dict:
    """List all workspace snapshots."""
    if _workspace_root is None:
        return {"status": "error", "reason": "Workspace root is not configured. Call configure_workspace_root first."}

    from src.workspace_tools.versioning import WorkspaceVersioning

    try:
        v = WorkspaceVersioning(_workspace_root)
        snapshots = v.list_snapshots()
        return {"status": "ok", "snapshots": snapshots}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ---------------------------------------------------------------------------
# Test feedback helper
# ---------------------------------------------------------------------------

_VALID_FEEDBACK_TYPES = {"bug", "friction", "feature_request", "praise"}


def _submit_feedback_impl(page: str, feedback_type: str, message: str) -> dict:
    """Insert a test feedback entry into workspace/feedback.db.

    Creates the feedback table if it does not exist.
    """
    if feedback_type not in _VALID_FEEDBACK_TYPES:
        return {
            "status": "error",
            "reason": f"feedback_type must be one of {sorted(_VALID_FEEDBACK_TYPES)}",
        }
    if not page or not message:
        return {"status": "error", "reason": "page and message are required"}

    # Create table if needed
    create_result = _run_sql_impl(
        "feedback.db",
        "CREATE TABLE IF NOT EXISTS feedback ("
        "  id TEXT PRIMARY KEY,"
        "  timestamp TEXT NOT NULL,"
        "  page TEXT NOT NULL,"
        "  feedback_type TEXT NOT NULL,"
        "  message TEXT NOT NULL"
        ")",
    )
    if create_result.get("status") != "ok":
        return create_result

    feedback_id = uuid.uuid4().hex[:16]
    timestamp = datetime.now(timezone.utc).isoformat()

    insert_result = _run_sql_impl(
        "feedback.db",
        "INSERT INTO feedback (id, timestamp, page, feedback_type, message) "
        "VALUES (?, ?, ?, ?, ?)",
        json.dumps([feedback_id, timestamp, page, feedback_type, message]),
    )
    if insert_result.get("status") != "ok":
        return insert_result

    return {
        "status": "ok",
        "feedback_id": feedback_id,
        "timestamp": timestamp,
    }


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


@tool
def review_workspace_files() -> str:
    """List all workspace files and read every HTML file in one call.

    Returns a JSON object with ``files`` (full listing) and ``html_contents``
    (a dict mapping each ``.html`` filename to its content).  Use this for QA
    review so you can inspect everything in a single tool call.
    """
    listing = _list_impl("")
    if listing.get("status") != "ok":
        return json.dumps(listing)
    html_contents: dict[str, str] = {}
    for fname in listing.get("files", []):
        if fname.endswith(".html"):
            result = _read_impl(fname)
            if result.get("status") == "ok":
                html_contents[fname] = result["content"]
    return json.dumps({
        "status": "ok",
        "files": listing["files"],
        "html_contents": html_contents,
    })


# Disable CrewAI's per-tool result cache for workspace tools.  The default
# cache_function returns True (= always cache), which causes reads after
# writes to return stale content for the same file_path argument.
_NO_CACHE = lambda _args=None, _result=None: False  # noqa: E731
@tool("Run Workspace SQL")
def run_workspace_sql(db_name: str, query: str, params: str = "[]") -> str:
    """Execute a SQL query against a SQLite database in the workspace directory.

    Use this to CREATE TABLE, INSERT, SELECT, UPDATE, DELETE on any .db file
    in the workspace.  The database file is created automatically if it does
    not exist.  Pass bind parameters as a JSON list in *params*.

    Examples:
        run_workspace_sql("feedback.db",
                          "CREATE TABLE IF NOT EXISTS feedback (id TEXT, msg TEXT)")
        run_workspace_sql("feedback.db",
                          "INSERT INTO feedback VALUES (?, ?)",
                          '["1", "Great site!"]')
        run_workspace_sql("feedback.db", "SELECT * FROM feedback")
    """
    return json.dumps(_run_sql_impl(db_name, query, params))


@tool("Check Workspace HTTP")
def check_workspace_http(pages: str = "") -> str:
    """Serve the workspace over HTTP and run validation checks.

    With no arguments, runs the full check suite: landing page load,
    signup form validation, and navigation link verification.
    Pass a comma-separated list of pages (e.g. ``"index.html,about.html"``)
    to check only those specific pages.

    Returns JSON with scores: ``http_landing_score``, ``http_signup_score``,
    ``http_navigation_score`` (each 0.0–1.0).
    """
    return json.dumps(_check_http_impl(pages))


@tool("Snapshot Workspace")
def snapshot_workspace(cycle_id: int) -> str:
    """Save a versioned snapshot of the entire workspace.

    Use this before making risky changes so you can restore later.
    Pass the current iteration number as ``cycle_id``.
    """
    return json.dumps(_snapshot_impl(cycle_id))


@tool("Restore Workspace")
def restore_workspace(cycle_id: int) -> str:
    """Restore the workspace from a previously saved snapshot.

    Pass the ``cycle_id`` of the snapshot to restore.  This replaces all
    current workspace files with the snapshot contents.
    """
    return json.dumps(_restore_impl(cycle_id))


@tool("List Workspace Snapshots")
def list_workspace_snapshots() -> str:
    """List all available workspace snapshots with their cycle IDs and file counts."""
    return json.dumps(_list_snapshots_impl())


@tool("Submit Test Feedback")
def submit_test_feedback(page: str, feedback_type: str, message: str) -> str:
    """Submit a test feedback entry to workspace/feedback.db.

    Use this to validate that the feedback pipeline works end-to-end.
    Valid ``feedback_type`` values: bug, friction, feature_request, praise.
    """
    return json.dumps(_submit_feedback_impl(page, feedback_type, message))


read_workspace_file.cache_function = _NO_CACHE
write_workspace_file.cache_function = _NO_CACHE
list_workspace_files.cache_function = _NO_CACHE
review_workspace_files.cache_function = _NO_CACHE
run_workspace_sql.cache_function = _NO_CACHE
check_workspace_http.cache_function = _NO_CACHE
snapshot_workspace.cache_function = _NO_CACHE
restore_workspace.cache_function = _NO_CACHE
list_workspace_snapshots.cache_function = _NO_CACHE
submit_test_feedback.cache_function = _NO_CACHE
