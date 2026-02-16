"""Consensus memory backend using SQLite.

Last-writer-wins with full history preserved.  Supports a propose/approve
workflow for gated writes on decisions and strategies.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from src.framework.contracts import ConsensusEntry
from src.framework.types import ConsensusStatus, EntryType
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ConsensusStoreBackend:
    """SQLite-backed consensus memory with supersedes chain."""

    def __init__(self, db_path: str = "data/memory/consensus.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info(f"ConsensusStoreBackend initialised (db={db_path})")

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS consensus_entries (
                entity_id       TEXT PRIMARY KEY,
                key             TEXT NOT NULL,
                value           TEXT NOT NULL DEFAULT 'null',
                entry_type      TEXT NOT NULL DEFAULT 'fact',
                confidence      REAL DEFAULT 1.0,
                source_agent_id TEXT DEFAULT '',
                source_evidence TEXT DEFAULT '[]',
                supersedes      TEXT,
                consensus_status TEXT DEFAULT 'approved',
                run_id          TEXT,
                cycle_id        INTEGER,
                version         INTEGER DEFAULT 1,
                status          TEXT DEFAULT 'active',
                metadata        TEXT DEFAULT '{}',
                timestamp_utc   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cons_key
                ON consensus_entries(key);
            CREATE INDEX IF NOT EXISTS idx_cons_status
                ON consensus_entries(consensus_status);
            CREATE INDEX IF NOT EXISTS idx_cons_key_status
                ON consensus_entries(key, consensus_status);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def cons_set(self, entry: ConsensusEntry) -> str:
        """Set (approve immediately) a consensus entry.  Supersedes any
        existing approved entry for the same key."""
        entry.consensus_status = ConsensusStatus.APPROVED

        # Mark old approved entry as superseded
        old = await self.cons_get(entry.key)
        if old is not None:
            self._conn.execute(
                "UPDATE consensus_entries SET consensus_status = ? WHERE entity_id = ?",
                (ConsensusStatus.SUPERSEDED.value, old.entity_id),
            )
            entry.supersedes = old.entity_id

        self._upsert(entry)
        return entry.entity_id

    async def cons_get(self, key: str) -> Optional[ConsensusEntry]:
        row = self._conn.execute(
            "SELECT * FROM consensus_entries WHERE key = ? AND consensus_status = ? ORDER BY timestamp_utc DESC LIMIT 1",
            (key, ConsensusStatus.APPROVED.value),
        ).fetchone()
        return self._row_to_entry(row) if row else None

    async def cons_propose(self, entry: ConsensusEntry) -> str:
        entry.consensus_status = ConsensusStatus.PROPOSED
        self._upsert(entry)
        return entry.entity_id

    async def cons_approve(self, entity_id: str) -> bool:
        row = self._conn.execute(
            "SELECT * FROM consensus_entries WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            return False

        entry = self._row_to_entry(row)

        # Mark previous approved entry for this key as superseded
        old = await self.cons_get(entry.key)
        if old is not None and old.entity_id != entity_id:
            self._conn.execute(
                "UPDATE consensus_entries SET consensus_status = ? WHERE entity_id = ?",
                (ConsensusStatus.SUPERSEDED.value, old.entity_id),
            )

        self._conn.execute(
            "UPDATE consensus_entries SET consensus_status = ?, supersedes = ? WHERE entity_id = ?",
            (ConsensusStatus.APPROVED.value, old.entity_id if old else None, entity_id),
        )
        self._conn.commit()
        return True

    async def cons_list(
        self,
        prefix: Optional[str] = None,
        entry_type: Optional[EntryType] = None,
    ) -> List[ConsensusEntry]:
        query = "SELECT * FROM consensus_entries WHERE consensus_status = ?"
        params: list = [ConsensusStatus.APPROVED.value]

        if prefix:
            query += " AND key LIKE ?"
            params.append(f"{prefix}%")
        if entry_type:
            query += " AND entry_type = ?"
            params.append(entry_type.value)

        query += " ORDER BY key"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def cons_history(self, key: str) -> List[ConsensusEntry]:
        rows = self._conn.execute(
            "SELECT * FROM consensus_entries WHERE key = ? ORDER BY timestamp_utc",
            (key,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _upsert(self, entry: ConsensusEntry) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO consensus_entries
               (entity_id, key, value, entry_type, confidence, source_agent_id,
                source_evidence, supersedes, consensus_status, run_id, cycle_id,
                version, status, metadata, timestamp_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.entity_id,
                entry.key,
                json.dumps(entry.value),
                entry.entry_type.value,
                entry.confidence,
                entry.source_agent_id,
                json.dumps(entry.source_evidence),
                entry.supersedes,
                entry.consensus_status.value,
                entry.run_id,
                entry.cycle_id,
                entry.version,
                entry.status,
                json.dumps(entry.metadata),
                entry.timestamp_utc.isoformat(),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> ConsensusEntry:
        return ConsensusEntry(
            entity_id=row["entity_id"],
            key=row["key"],
            value=json.loads(row["value"]),
            entry_type=EntryType(row["entry_type"]),
            confidence=row["confidence"],
            source_agent_id=row["source_agent_id"],
            source_evidence=json.loads(row["source_evidence"]),
            supersedes=row["supersedes"],
            consensus_status=ConsensusStatus(row["consensus_status"]),
            run_id=row["run_id"],
            cycle_id=row["cycle_id"],
            version=row["version"],
            status=row["status"],
            metadata=json.loads(row["metadata"]),
        )
