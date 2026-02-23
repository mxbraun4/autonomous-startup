"""Tests for copy-on-write workspace versioning."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.workspace.versioning import WorkspaceVersioning


class TestWorkspaceVersioning:
    """Tests for WorkspaceVersioning using tmp_path."""

    def test_snapshot_creates_copy(self, tmp_path: Path) -> None:
        """Create files in workspace, snapshot, verify copy exists."""
        # Setup workspace with files
        (tmp_path / "file_a.txt").write_text("alpha")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "file_b.txt").write_text("beta")

        wv = WorkspaceVersioning(tmp_path)
        result = wv.snapshot(1)

        assert result["cycle_id"] == 1
        assert result["file_count"] == 2
        assert "timestamp" in result

        snap_dir = Path(result["path"])
        assert (snap_dir / "file_a.txt").read_text() == "alpha"
        assert (snap_dir / "subdir" / "file_b.txt").read_text() == "beta"

    def test_snapshot_excludes_versions_dir(self, tmp_path: Path) -> None:
        """.versions/ directory is not copied recursively into the snapshot."""
        (tmp_path / "data.txt").write_text("hello")

        wv = WorkspaceVersioning(tmp_path)
        # First snapshot creates .versions/cycle_1
        wv.snapshot(1)
        # Second snapshot should NOT contain .versions/ from the workspace
        result = wv.snapshot(2)

        snap_dir = Path(result["path"])
        assert not (snap_dir / WorkspaceVersioning.VERSIONS_DIR).exists()

    def test_restore_from_snapshot(self, tmp_path: Path) -> None:
        """Snapshot, modify files, restore, verify original content."""
        (tmp_path / "config.txt").write_text("original")

        wv = WorkspaceVersioning(tmp_path)
        wv.snapshot(1)

        # Modify the file after snapshotting
        (tmp_path / "config.txt").write_text("modified")
        (tmp_path / "extra.txt").write_text("should be removed")

        result = wv.restore(1)

        assert result["status"] == "ok"
        assert result["cycle_id"] == 1
        assert (tmp_path / "config.txt").read_text() == "original"
        assert not (tmp_path / "extra.txt").exists()

    def test_restore_missing_snapshot(self, tmp_path: Path) -> None:
        """Restore nonexistent cycle returns error."""
        wv = WorkspaceVersioning(tmp_path)
        result = wv.restore(999)

        assert result["status"] == "error"
        assert "not found" in result["reason"]

    def test_list_snapshots(self, tmp_path: Path) -> None:
        """Create multiple snapshots, verify list returns them ordered."""
        (tmp_path / "a.txt").write_text("a")

        wv = WorkspaceVersioning(tmp_path)
        wv.snapshot(3)
        wv.snapshot(1)
        wv.snapshot(2)

        snapshots = wv.list_snapshots()

        assert len(snapshots) == 3
        cycle_ids = [s["cycle_id"] for s in snapshots]
        assert cycle_ids == [1, 2, 3]
        for s in snapshots:
            assert "path" in s
            assert "file_count" in s

    def test_snapshot_overwrites_existing(self, tmp_path: Path) -> None:
        """Snapshot same cycle_id twice, second overwrites first."""
        (tmp_path / "v1.txt").write_text("version1")

        wv = WorkspaceVersioning(tmp_path)
        wv.snapshot(5)

        # Change workspace content
        (tmp_path / "v1.txt").unlink()
        (tmp_path / "v2.txt").write_text("version2")

        result = wv.snapshot(5)

        snap_dir = Path(result["path"])
        assert not (snap_dir / "v1.txt").exists()
        assert (snap_dir / "v2.txt").read_text() == "version2"
        assert result["file_count"] == 1
