"""Versioned procedural memory backend using SQLite.

Each ``task_type`` can have multiple versions. ``proc_save()`` auto-increments
version and deactivates the previous active version.  ``proc_rollback()``
reactivates an older version.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.framework.contracts import Procedure, ProcedureVersion
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ProceduralStoreBackend:
    """SQLite-backed procedural memory with version history."""

    def __init__(self, db_path: str = "data/memory/procedural.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info(f"ProceduralStoreBackend initialised (db={db_path})")

    def close(self) -> None:
        """Close the SQLite connection (idempotent)."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS procedures (
                task_type   TEXT NOT NULL,
                version     INTEGER NOT NULL,
                workflow    TEXT NOT NULL DEFAULT '{}',
                score       REAL DEFAULT 0.0,
                is_active   INTEGER DEFAULT 1,
                created_by  TEXT DEFAULT '',
                provenance  TEXT DEFAULT '',
                created_at  TEXT NOT NULL,
                UNIQUE(task_type, version)
            );

            CREATE INDEX IF NOT EXISTS idx_proc_task_active
                ON procedures(task_type, is_active);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def proc_save(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float = 0.0,
        created_by: str = "",
        provenance: str = "",
    ) -> Procedure:
        await asyncio.to_thread(self._sync_save, task_type, workflow, score, created_by, provenance)
        return (await self.proc_get(task_type))  # type: ignore[return-value]

    async def proc_get(self, task_type: str) -> Optional[Procedure]:
        return await asyncio.to_thread(self._sync_get, task_type)

    async def proc_get_history(self, task_type: str) -> List[Procedure]:
        proc = await self.proc_get(task_type)
        return [proc] if proc else []

    async def proc_rollback(self, task_type: str, target_version: int) -> Optional[Procedure]:
        ok = await asyncio.to_thread(self._sync_rollback, task_type, target_version)
        if not ok:
            return None
        return await self.proc_get(task_type)

    async def proc_list_types(self) -> List[str]:
        return await asyncio.to_thread(self._sync_list_types)

    # ------------------------------------------------------------------
    # Synchronous helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _sync_save(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float,
        created_by: str,
        provenance: str,
    ) -> None:
        row = self._conn.execute(
            "SELECT MAX(version) as max_v FROM procedures WHERE task_type = ?",
            (task_type,),
        ).fetchone()
        next_version = (row["max_v"] or 0) + 1

        self._conn.execute(
            "UPDATE procedures SET is_active = 0 WHERE task_type = ? AND is_active = 1",
            (task_type,),
        )

        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO procedures (task_type, version, workflow, score,
               is_active, created_by, provenance, created_at)
               VALUES (?,?,?,?,1,?,?,?)""",
            (task_type, next_version, json.dumps(workflow), score, created_by, provenance, now),
        )
        self._conn.commit()

    def _sync_get(self, task_type: str) -> Optional[Procedure]:
        rows = self._conn.execute(
            "SELECT * FROM procedures WHERE task_type = ? ORDER BY version",
            (task_type,),
        ).fetchall()
        if not rows:
            return None
        return self._rows_to_procedure(task_type, rows)

    def _sync_rollback(self, task_type: str, target_version: int) -> bool:
        row = self._conn.execute(
            "SELECT version FROM procedures WHERE task_type = ? AND version = ?",
            (task_type, target_version),
        ).fetchone()
        if not row:
            logger.warning(f"Rollback failed: version {target_version} not found for {task_type}")
            return False

        self._conn.execute(
            "UPDATE procedures SET is_active = 0 WHERE task_type = ?",
            (task_type,),
        )
        self._conn.execute(
            "UPDATE procedures SET is_active = 1 WHERE task_type = ? AND version = ?",
            (task_type, target_version),
        )
        self._conn.commit()
        return True

    def _sync_list_types(self) -> List[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT task_type FROM procedures"
        ).fetchall()
        return [r["task_type"] for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rows_to_procedure(task_type: str, rows: list) -> Procedure:
        versions: List[ProcedureVersion] = []
        current_version = 1
        for r in rows:
            pv = ProcedureVersion(
                version=r["version"],
                workflow=json.loads(r["workflow"]),
                score=r["score"],
                created_by=r["created_by"],
                provenance=r["provenance"],
                is_active=bool(r["is_active"]),
            )
            versions.append(pv)
            if pv.is_active:
                current_version = pv.version

        return Procedure(
            task_type=task_type,
            current_version=current_version,
            versions=versions,
        )
