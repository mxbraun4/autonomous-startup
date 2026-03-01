"""Initialize memory systems and database using non-legacy UnifiedStore."""

import asyncio
from pathlib import Path

if __package__:
    from ._bootstrap import add_repo_root_to_path
else:
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path(__file__)

from src.data.database import StartupDatabase
from src.utils.config import settings
from src.utils.logging import setup_logging, get_logger

setup_logging(settings.log_level)
logger = get_logger(__name__)


SEED_WORKFLOWS = {
    "data_collection": {
        "workflow": {
            "description": "Web data collection workflow",
            "steps": [
                "Check database stats for current coverage",
                "Identify sectors with low coverage",
                "Search web for startups in target sectors",
                "Extract and validate startup data",
                "Save validated startups to database",
                "Search web for VCs in relevant sectors",
                "Save VCs to database",
            ],
            "best_practices": [
                "Focus on sectors relevant to the business idea",
                "Prioritize startups with recent funding news",
                "Look for VCs that actively invest in the target sector",
                "Validate data completeness before saving",
            ],
        },
        "score": 0.75,
    },
    "vc_matching": {
        "workflow": {
            "description": "Startup-VC matching workflow",
            "steps": [
                "Get startup profile and requirements",
                "Search VCs matching sector and stage",
                "Score VCs by alignment",
                "Generate match recommendations",
                "Prepare intro materials",
            ],
            "best_practices": [
                "Match on sector, stage, and check size",
                "Consider geographic preferences",
                "Look at recent VC activity",
                "Prioritize VCs with portfolio synergies",
            ],
        },
        "score": 0.70,
    },
}




def initialize_database() -> None:
    """Initialize the startup/VC database."""
    logger.info("Initializing startup database...")
    with StartupDatabase() as db:
        stats = db.get_stats()
        logger.info(
            "Database ready: %s startups, %s VCs",
            stats["total_startups"],
            stats["total_vcs"],
        )


async def seed_unified_store() -> None:
    """Seed memory through the non-legacy UnifiedStore."""
    from src.framework.storage.unified_store import UnifiedStore

    data_dir = str(Path(settings.memory_data_dir).resolve())
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    async with UnifiedStore(data_dir=data_dir) as store:
        for task_type, workflow_data in SEED_WORKFLOWS.items():
            await store.proc_save(
                task_type=task_type,
                workflow=workflow_data["workflow"],
                score=workflow_data["score"],
                created_by="seed_memory",
                provenance="initial seed",
            )

        proc_types = await store.proc_list_types()
        logger.info("Seeded %s workflows via UnifiedStore (data_dir=%s)", len(proc_types), data_dir)


def main() -> None:
    """Main entry point."""
    logger.info("Initializing autonomous startup system...")
    initialize_database()

    logger.info("Seeding via UnifiedStore...")
    asyncio.run(seed_unified_store())

    logger.info("System initialization completed!")
    print("\n=== System Initialized (UnifiedStore) ===")
    print("Procedural workflows seeded")
    print("Consensus baseline seeded")
    print("\nDatabase ready for data collection.")
    print("\nNext steps:")
    print("  1. Run simulation: python scripts/run.py")
    print("  2. The system will collect startup/VC data via web search")


if __name__ == "__main__":
    main()
