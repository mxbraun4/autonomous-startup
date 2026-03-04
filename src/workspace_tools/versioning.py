"""Copy-on-write workspace versioning."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class WorkspaceVersioning:
    """Manages copy-on-write snapshots of the workspace directory."""

    VERSIONS_DIR = ".versions"

    def __init__(self, workspace_root: str | Path) -> None:
        self._root = Path(workspace_root).resolve()
        self._versions_dir = self._root / self.VERSIONS_DIR
        self._versions_dir.mkdir(parents=True, exist_ok=True)

    @property
    def versions_dir(self) -> Path:
        return self._versions_dir

    def snapshot(self, cycle_id: int) -> Dict[str, Any]:
        """Copy workspace (excluding .versions/) to .versions/cycle_{N}/."""
        dest = self._versions_dir / f"cycle_{cycle_id}"
        if dest.exists():
            shutil.rmtree(dest)

        dest.mkdir(parents=True, exist_ok=True)
        for item in self._root.iterdir():
            if item.name == self.VERSIONS_DIR:
                continue
            if item.is_file():
                shutil.copy2(item, dest / item.name)
            elif item.is_dir():
                shutil.copytree(item, dest / item.name)

        file_count = sum(1 for _ in dest.rglob("*") if _.is_file())
        return {
            "cycle_id": cycle_id,
            "path": str(dest),
            "file_count": file_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def restore(self, cycle_id: int) -> Dict[str, Any]:
        """Restore workspace from a snapshot."""
        src = self._versions_dir / f"cycle_{cycle_id}"
        if not src.exists():
            return {"status": "error", "reason": f"snapshot cycle_{cycle_id} not found"}

        # Remove current workspace files (except .versions/)
        for item in self._root.iterdir():
            if item.name == self.VERSIONS_DIR:
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

        # Copy snapshot back
        for item in src.iterdir():
            if item.is_file():
                shutil.copy2(item, self._root / item.name)
            elif item.is_dir():
                shutil.copytree(item, self._root / item.name)

        file_count = sum(1 for f in self._root.rglob("*") if f.is_file() and self.VERSIONS_DIR not in f.parts)
        return {
            "status": "ok",
            "cycle_id": cycle_id,
            "files_restored": file_count,
        }

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """Return metadata for all snapshots."""
        snapshots = []
        if not self._versions_dir.exists():
            return snapshots
        for entry in sorted(self._versions_dir.iterdir()):
            if entry.is_dir() and entry.name.startswith("cycle_"):
                try:
                    cid = int(entry.name.split("_", 1)[1])
                except (ValueError, IndexError):
                    continue
                file_count = sum(1 for f in entry.rglob("*") if f.is_file())
                snapshots.append({
                    "cycle_id": cid,
                    "path": str(entry),
                    "file_count": file_count,
                })
        return snapshots
