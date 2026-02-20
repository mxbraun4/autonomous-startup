"""Episodic memory backend: SQLite v2 + ChromaDB dual-write.

Structured data goes to SQLite (episodes_v2 table), summary embeddings go
to the ``episodic_summaries`` ChromaDB collection.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

import chromadb

from src.framework.contracts import Episode
from src.framework.types import EpisodeType
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _safe_episode_type(raw: str) -> EpisodeType:
    try:
        return EpisodeType(raw)
    except ValueError:
        return EpisodeType.GENERAL


class EpisodicStoreBackend:
    """Dual-write episodic store: SQLite for structured queries, ChromaDB for
    semantic similarity search over episode summaries."""

    CHROMA_COLLECTION = "episodic_summaries"

    def __init__(
        self,
        db_path: str = "data/memory/episodic_v2.db",
        chroma_dir: str = "data/memory/chroma",
    ):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

        os.makedirs(chroma_dir, exist_ok=True)
        self._chroma = chromadb.PersistentClient(path=chroma_dir)
        self._collection = self._chroma.get_or_create_collection(
            name=self.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"EpisodicStoreBackend initialised (db={db_path}, chroma={chroma_dir})")

    def close(self) -> None:
        """Close the SQLite connection (idempotent)."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes_v2 (
                entity_id   TEXT PRIMARY KEY,
                agent_id    TEXT NOT NULL,
                episode_type TEXT NOT NULL,
                context     TEXT NOT NULL DEFAULT '{}',
                action      TEXT NOT NULL DEFAULT '',
                outcome     TEXT NOT NULL DEFAULT '{}',
                success     INTEGER NOT NULL DEFAULT 0,
                summary_text TEXT NOT NULL DEFAULT '',
                tags        TEXT NOT NULL DEFAULT '[]',
                run_id      TEXT,
                cycle_id    INTEGER,
                iteration   INTEGER DEFAULT 0,
                version     INTEGER DEFAULT 1,
                status      TEXT DEFAULT 'active',
                metadata    TEXT DEFAULT '{}',
                timestamp_utc TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ep2_agent_type
                ON episodes_v2(agent_id, episode_type);
            CREATE INDEX IF NOT EXISTS idx_ep2_success
                ON episodes_v2(success);
            CREATE INDEX IF NOT EXISTS idx_ep2_run
                ON episodes_v2(run_id);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def ep_record(self, episode: Episode) -> str:
        return await asyncio.to_thread(self._sync_record, episode)

    async def ep_get(self, entity_id: str) -> Optional[Episode]:
        return await asyncio.to_thread(self._sync_get, entity_id)

    async def ep_search_similar(
        self,
        query: str,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        top_k: int = 10,
    ) -> List[Episode]:
        """Query ChromaDB first, then fetch full records from SQLite."""
        return await asyncio.to_thread(
            self._sync_search_similar, query, agent_id, episode_type, top_k,
        )

    async def ep_search_structured(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> List[Episode]:
        return await asyncio.to_thread(
            self._sync_search_structured, agent_id, episode_type, success_only, limit,
        )

    async def ep_get_success_rate(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
    ) -> float:
        return await asyncio.to_thread(self._sync_get_success_rate, agent_id, episode_type)

    # ------------------------------------------------------------------
    # Synchronous helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _sync_record(self, episode: Episode) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO episodes_v2
               (entity_id, agent_id, episode_type, context, action, outcome,
                success, summary_text, tags, run_id, cycle_id, iteration,
                version, status, metadata, timestamp_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                episode.entity_id,
                episode.agent_id,
                episode.episode_type.value,
                json.dumps(episode.context),
                episode.action,
                json.dumps(episode.outcome),
                int(episode.success),
                episode.summary_text,
                json.dumps(episode.tags),
                episode.run_id,
                episode.cycle_id,
                episode.iteration,
                episode.version,
                episode.status,
                json.dumps(episode.metadata),
                episode.timestamp_utc.isoformat(),
            ),
        )
        self._conn.commit()

        embed_text = episode.summary_text or episode.action or json.dumps(episode.context)
        if embed_text.strip():
            self._collection.upsert(
                ids=[episode.entity_id],
                documents=[embed_text],
                metadatas=[{
                    "agent_id": episode.agent_id,
                    "episode_type": episode.episode_type.value,
                    "success": str(episode.success),
                }],
            )

        return episode.entity_id

    def _sync_get(self, entity_id: str) -> Optional[Episode]:
        row = self._conn.execute(
            "SELECT * FROM episodes_v2 WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        return self._row_to_episode(row) if row else None

    def _sync_search_similar(
        self,
        query: str,
        agent_id: Optional[str],
        episode_type: Optional[EpisodeType],
        top_k: int,
    ) -> List[Episode]:
        count = self._collection.count()
        if count == 0:
            return []

        effective_k = min(top_k, count)
        where = self._build_chroma_where(agent_id, episode_type)
        results = self._collection.query(
            query_texts=[query],
            n_results=effective_k,
            where=where,
        )

        entity_ids = results.get("ids", [[]])[0]
        if not entity_ids:
            return []

        placeholders = ",".join("?" for _ in entity_ids)
        rows = self._conn.execute(
            f"SELECT * FROM episodes_v2 WHERE entity_id IN ({placeholders})",
            entity_ids,
        ).fetchall()

        return [self._row_to_episode(r) for r in rows]

    def _sync_search_structured(
        self,
        agent_id: Optional[str],
        episode_type: Optional[EpisodeType],
        success_only: bool,
        limit: int,
    ) -> List[Episode]:
        query = "SELECT * FROM episodes_v2 WHERE 1=1"
        params: list = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if episode_type:
            query += " AND episode_type = ?"
            params.append(episode_type.value)
        if success_only:
            query += " AND success = 1"

        query += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def _sync_get_success_rate(
        self,
        agent_id: Optional[str],
        episode_type: Optional[EpisodeType],
    ) -> float:
        query = "SELECT AVG(CAST(success AS FLOAT)) as rate FROM episodes_v2 WHERE 1=1"
        params: list = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if episode_type:
            query += " AND episode_type = ?"
            params.append(episode_type.value)

        row = self._conn.execute(query, params).fetchone()
        return float(row["rate"]) if row and row["rate"] is not None else 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_episode(row: sqlite3.Row) -> Episode:
        return Episode(
            entity_id=row["entity_id"],
            agent_id=row["agent_id"],
            episode_type=_safe_episode_type(row["episode_type"]),
            context=json.loads(row["context"]),
            action=row["action"],
            outcome=json.loads(row["outcome"]),
            success=bool(row["success"]),
            summary_text=row["summary_text"],
            tags=json.loads(row["tags"]),
            run_id=row["run_id"],
            cycle_id=row["cycle_id"],
            iteration=row["iteration"],
            version=row["version"],
            status=row["status"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _build_chroma_where(
        agent_id: Optional[str],
        episode_type: Optional[EpisodeType],
    ) -> Optional[Dict[str, Any]]:
        conditions = []
        if agent_id:
            conditions.append({"agent_id": {"$eq": agent_id}})
        if episode_type:
            conditions.append({"episode_type": {"$eq": episode_type.value}})
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}
