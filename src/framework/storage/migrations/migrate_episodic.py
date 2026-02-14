"""Migrate old episodes table to episodes_v2 + ChromaDB embeddings.

Reads from the legacy ``episodes`` table in episodic.db and writes each row
into the new ``episodes_v2`` table and the ``episodic_summaries`` ChromaDB
collection.

Usage:
    python -m src.framework.storage.migrations.migrate_episodic
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.framework.contracts import Episode
from src.framework.types import EpisodeType
from src.framework.storage.backends.episodic_store import EpisodicStoreBackend
from src.utils.logging import setup_logging, get_logger

setup_logging("INFO")
logger = get_logger(__name__)


def _safe_episode_type(raw: str) -> EpisodeType:
    try:
        return EpisodeType(raw)
    except ValueError:
        return EpisodeType.GENERAL


async def migrate(
    old_db_path: str = "data/memory/episodic.db",
    new_db_path: str = "data/memory/episodic_v2.db",
    chroma_dir: str = "data/memory/chroma",
) -> int:
    """Run the migration and return the number of records migrated."""

    if not Path(old_db_path).exists():
        logger.warning(f"Legacy database not found at {old_db_path}, nothing to migrate")
        return 0

    old_conn = sqlite3.connect(old_db_path)
    old_conn.row_factory = sqlite3.Row

    rows = old_conn.execute("SELECT * FROM episodes ORDER BY id").fetchall()
    logger.info(f"Found {len(rows)} legacy episodes to migrate")

    backend = EpisodicStoreBackend(db_path=new_db_path, chroma_dir=chroma_dir)

    migrated = 0
    for row in rows:
        context = json.loads(row["context"]) if isinstance(row["context"], str) else row["context"]
        outcome = json.loads(row["outcome"]) if isinstance(row["outcome"], str) else row["outcome"]

        # Build a summary from context + outcome for embedding
        summary_parts = []
        if isinstance(context, dict):
            summary_parts.append(" ".join(str(v) for v in context.values()))
        if isinstance(outcome, dict):
            summary_parts.append(" ".join(str(v) for v in outcome.values()))
        summary_text = " ".join(summary_parts).strip()

        episode = Episode(
            entity_id=f"legacy_{row['id']}",
            agent_id=row["agent_id"],
            episode_type=_safe_episode_type(row["episode_type"]),
            context=context,
            outcome=outcome,
            success=bool(row["success"]),
            summary_text=summary_text,
            iteration=row["iteration"] or 0,
        )

        await backend.ep_record(episode)
        migrated += 1

    old_conn.close()
    logger.info(f"Migration complete: {migrated} episodes migrated")
    return migrated


def main() -> None:
    count = asyncio.run(migrate())
    print(f"Migrated {count} episodes")


if __name__ == "__main__":
    main()
