"""Tests for src.workspace.file_tools helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workspace.file_tools import (
    _list_impl,
    _read_impl,
    _write_impl,
    configure_workspace_root,
    _workspace_root,
)
import src.workspace.file_tools as _ft


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
    assert result["reason"] == "path_escape"


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
