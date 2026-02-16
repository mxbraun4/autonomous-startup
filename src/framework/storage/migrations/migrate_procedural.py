"""Migrate old workflows.json to versioned SQLite procedural store.

Reads from the legacy ``workflows.json`` file and inserts each workflow
as version 1 into the new ``procedures`` SQLite table.

Usage:
    python -m src.framework.storage.migrations.migrate_procedural
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.framework.storage.backends.procedural_store import ProceduralStoreBackend
from src.utils.logging import setup_logging, get_logger

setup_logging("INFO")
logger = get_logger(__name__)


async def migrate(
    json_path: str = "data/memory/workflows.json",
    db_path: str = "data/memory/procedural.db",
) -> int:
    """Run the migration and return the number of workflows migrated."""

    path = Path(json_path)
    if not path.exists():
        logger.warning(f"Legacy workflows file not found at {json_path}, nothing to migrate")
        return 0

    with open(path, "r") as f:
        workflows = json.load(f)

    logger.info(f"Found {len(workflows)} legacy workflows to migrate")

    backend = ProceduralStoreBackend(db_path=db_path)

    migrated = 0
    for task_type, data in workflows.items():
        workflow = data.get("workflow", data)
        score = data.get("score", 0.0)
        metadata = data.get("metadata", {})

        await backend.proc_save(
            task_type=task_type,
            workflow=workflow,
            score=score,
            created_by="migration",
            provenance=f"migrated from {json_path}",
        )
        migrated += 1

    logger.info(f"Migration complete: {migrated} workflows migrated")
    return migrated


def main() -> None:
    count = asyncio.run(migrate())
    print(f"Migrated {count} workflows")


if __name__ == "__main__":
    main()
