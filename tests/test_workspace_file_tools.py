"""Tests for src.workspace_tools.file_tools helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workspace_tools.file_tools import (
    _check_http_impl,
    _list_impl,
    _list_snapshots_impl,
    _read_impl,
    _restore_impl,
    _run_sql_impl,
    _snapshot_impl,
    _submit_feedback_impl,
    _write_impl,
    configure_workspace_root,
    _workspace_root,
)
import src.workspace_tools.file_tools as _ft


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_root():
    """Reset the module-level workspace root before and after every test."""
    original = _ft._workspace_root
    yield
    _ft._workspace_root = original


@pytest.fixture()
def workspace(tmp_path: Path):
    """Configure the workspace root to a temporary directory."""
    configure_workspace_root(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_configure_and_read(workspace: Path):
    """Configure root, write a file manually, read it via the impl helper."""
    (workspace / "hello.txt").write_text("world", encoding="utf-8")

    result = _read_impl("hello.txt")

    assert result["status"] == "ok"
    assert result["content"] == "world"
    assert result["path"] == str((workspace / "hello.txt").resolve())


def test_write_and_read_roundtrip(workspace: Path):
    """Write via impl, then read via impl — content should round-trip."""
    write_result = _write_impl("notes/ideas.txt", "launch plan")
    assert write_result["status"] == "ok"
    assert write_result["bytes_written"] == len(b"launch plan")

    read_result = _read_impl("notes/ideas.txt")
    assert read_result["status"] == "ok"
    assert read_result["content"] == "launch plan"


def test_list_files(workspace: Path):
    """Write several files and verify they all appear in the listing."""
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.txt").write_text("b", encoding="utf-8")

    result = _list_impl()

    assert result["status"] == "ok"
    listed = result["files"]
    # Normalize to forward-slash for cross-platform comparison
    listed_normalized = [p.replace("\\", "/") for p in listed]
    assert "a.txt" in listed_normalized
    assert "sub/b.txt" in listed_normalized


def test_path_escape_rejected(workspace: Path):
    """Attempting to escape the workspace root should be denied."""
    result = _read_impl("../etc/passwd")

    assert result["status"] == "denied"
    assert "Path escapes workspace" in result["reason"]


def test_read_missing_file(workspace: Path):
    """Reading a non-existent file should return an error status."""
    result = _read_impl("does_not_exist.txt")

    assert result["status"] == "error"
    assert "reason" in result


def test_list_excludes_versions(workspace: Path):
    """Files under .versions/ should not appear in the listing."""
    versions_dir = workspace / ".versions"
    versions_dir.mkdir()
    (versions_dir / "snapshot.txt").write_text("v1", encoding="utf-8")
    (workspace / "visible.txt").write_text("yes", encoding="utf-8")

    result = _list_impl()

    assert result["status"] == "ok"
    listed_normalized = [p.replace("\\", "/") for p in result["files"]]
    assert "visible.txt" in listed_normalized
    assert ".versions/snapshot.txt" not in listed_normalized


def test_unconfigured_root_errors():
    """Calling tools before configuring the root should give an error."""
    # Ensure root is explicitly None
    _ft._workspace_root = None

    read_result = _read_impl("anything.txt")
    assert read_result["status"] == "error"
    assert "not configured" in read_result["reason"].lower()

    write_result = _write_impl("anything.txt", "data")
    assert write_result["status"] == "error"
    assert "not configured" in write_result["reason"].lower()

    list_result = _list_impl()
    assert list_result["status"] == "error"
    assert "not configured" in list_result["reason"].lower()


# ---------------------------------------------------------------------------
# SQL tool tests
# ---------------------------------------------------------------------------


def test_sql_create_and_select(workspace: Path):
    """CREATE TABLE + INSERT + SELECT roundtrip."""
    result = _run_sql_impl(
        "test.db",
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)",
    )
    assert result["status"] == "ok"

    result = _run_sql_impl(
        "test.db",
        "INSERT INTO items (id, name) VALUES (?, ?)",
        '[1, "widget"]',
    )
    assert result["status"] == "ok"
    assert result["rowcount"] == 1

    result = _run_sql_impl("test.db", "SELECT * FROM items")
    assert result["status"] == "ok"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["name"] == "widget"


def test_sql_rejects_non_db_extension(workspace: Path):
    """Non-.db file name should be blocked."""
    result = _run_sql_impl("data.sqlite", "SELECT 1")
    assert result["status"] == "error"
    assert ".db" in result["reason"]


def test_sql_rejects_path_escape(workspace: Path):
    """Path traversal should be denied."""
    result = _run_sql_impl("../../evil.db", "SELECT 1")
    assert result["status"] == "denied"
    assert "Path escapes workspace" in result["reason"]


def test_sql_blocks_attach(workspace: Path):
    """ATTACH DATABASE should be blocked."""
    result = _run_sql_impl("test.db", "ATTACH DATABASE 'other.db' AS other")
    assert result["status"] == "denied"
    assert "ATTACH" in result["reason"]


def test_sql_blocks_load_extension(workspace: Path):
    """load_extension should be blocked."""
    result = _run_sql_impl("test.db", "SELECT load_extension('evil.so')")
    assert result["status"] == "denied"
    assert "LOAD_EXTENSION" in result["reason"]


def test_sql_invalid_params(workspace: Path):
    """Bad JSON params should return an error."""
    result = _run_sql_impl("test.db", "SELECT 1", "not-json")
    assert result["status"] == "error"
    assert "invalid params" in result["reason"].lower()


def test_sql_creates_parent_directory(workspace: Path):
    """Nested db_name like sub/nested.db should auto-create parent dirs."""
    result = _run_sql_impl(
        "sub/nested.db",
        "CREATE TABLE t (x INTEGER)",
    )
    assert result["status"] == "ok"
    assert (workspace / "sub" / "nested.db").exists()


def test_sql_unconfigured_root():
    """SQL tool should error when workspace root is None."""
    _ft._workspace_root = None
    result = _run_sql_impl("test.db", "SELECT 1")
    assert result["status"] == "error"
    assert "not configured" in result["reason"].lower()


# ---------------------------------------------------------------------------
# HTTP check tests
# ---------------------------------------------------------------------------


def test_http_check_landing_loads(workspace: Path):
    """Full suite should report landing page status."""
    (workspace / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Test</title></head>"
        "<body><h1>Hello</h1></body></html>",
        encoding="utf-8",
    )
    result = _check_http_impl()
    assert result["status"] == "ok"
    assert result["http_landing_score"] == 1.0


def test_http_check_specific_pages(workspace: Path):
    """Checking specific pages returns per-page results."""
    (workspace / "about.html").write_text("<html><body>About</body></html>", encoding="utf-8")
    result = _check_http_impl("about.html")
    assert result["status"] == "ok"
    assert "about.html" in result["pages"]
    assert result["pages"]["about.html"]["loaded"] is True


def test_http_check_missing_page(workspace: Path):
    """A missing page should show loaded=False."""
    result = _check_http_impl("nope.html")
    assert result["status"] == "ok"
    assert result["pages"]["nope.html"]["loaded"] is False


def test_http_check_unconfigured_root():
    """HTTP check should error when workspace root is None."""
    _ft._workspace_root = None
    result = _check_http_impl()
    assert result["status"] == "error"
    assert "not configured" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Workspace versioning tests
# ---------------------------------------------------------------------------


def test_snapshot_and_restore(workspace: Path):
    """Snapshot, modify, restore should recover original content."""
    (workspace / "page.html").write_text("original", encoding="utf-8")

    snap = _snapshot_impl(1)
    assert snap["status"] == "ok"
    assert snap["file_count"] >= 1

    # Modify
    (workspace / "page.html").write_text("modified", encoding="utf-8")
    assert (workspace / "page.html").read_text(encoding="utf-8") == "modified"

    # Restore
    restore = _restore_impl(1)
    assert restore["status"] == "ok"
    assert (workspace / "page.html").read_text(encoding="utf-8") == "original"


def test_list_snapshots(workspace: Path):
    """list_snapshots should show taken snapshots."""
    (workspace / "f.txt").write_text("x", encoding="utf-8")
    _snapshot_impl(1)
    _snapshot_impl(2)

    result = _list_snapshots_impl()
    assert result["status"] == "ok"
    ids = [s["cycle_id"] for s in result["snapshots"]]
    assert 1 in ids
    assert 2 in ids


def test_restore_missing_snapshot(workspace: Path):
    """Restoring a non-existent snapshot should error."""
    result = _restore_impl(999)
    assert result["status"] == "error"


def test_snapshot_unconfigured_root():
    """Snapshot should error when workspace root is None."""
    _ft._workspace_root = None
    assert _snapshot_impl(1)["status"] == "error"
    assert _restore_impl(1)["status"] == "error"
    assert _list_snapshots_impl()["status"] == "error"


# ---------------------------------------------------------------------------
# Test feedback tests
# ---------------------------------------------------------------------------


def test_submit_feedback_roundtrip(workspace: Path):
    """Submit feedback and verify it's in the database."""
    result = _submit_feedback_impl("index.html", "praise", "Looks great!")
    assert result["status"] == "ok"
    assert "feedback_id" in result

    # Verify via SQL
    rows = _run_sql_impl("feedback.db", "SELECT * FROM feedback")
    assert rows["status"] == "ok"
    assert len(rows["rows"]) == 1
    assert rows["rows"][0]["page"] == "index.html"
    assert rows["rows"][0]["feedback_type"] == "praise"


def test_submit_feedback_invalid_type(workspace: Path):
    """Invalid feedback_type should be rejected."""
    result = _submit_feedback_impl("index.html", "invalid_type", "msg")
    assert result["status"] == "error"
    assert "feedback_type" in result["reason"]


def test_submit_feedback_empty_fields(workspace: Path):
    """Empty page or message should be rejected."""
    result = _submit_feedback_impl("", "bug", "msg")
    assert result["status"] == "error"

    result = _submit_feedback_impl("page.html", "bug", "")
    assert result["status"] == "error"


def test_submit_feedback_unconfigured_root():
    """Feedback should error when workspace root is None."""
    _ft._workspace_root = None
    result = _submit_feedback_impl("page.html", "bug", "broken")
    assert result["status"] == "error"
