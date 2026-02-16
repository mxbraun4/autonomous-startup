"""Initialize memory systems and database.

Supports both legacy memory systems and the new UnifiedStore.
By default seeds through UnifiedStore; pass --legacy to use old code paths.
"""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory import SemanticMemory, EpisodicMemory, ProceduralMemory
from src.data.database import StartupDatabase
from src.utils.config import settings
from src.utils.logging import setup_logging, get_logger

setup_logging(settings.log_level)
logger = get_logger(__name__)

# Workflow seed data shared between legacy and new paths
SEED_WORKFLOWS = {
    'data_collection': {
        'workflow': {
            'description': 'Web data collection workflow',
            'steps': [
                'Check database stats for current coverage',
                'Identify sectors with low coverage',
                'Search web for startups in target sectors',
                'Extract and validate startup data',
                'Save validated startups to database',
                'Search web for VCs in relevant sectors',
                'Save VCs to database'
            ],
            'best_practices': [
                'Focus on sectors relevant to the business idea',
                'Prioritize startups with recent funding news',
                'Look for VCs that actively invest in the target sector',
                'Validate data completeness before saving'
            ]
        },
        'score': 0.75,
        'metadata': {'source': 'seed', 'validated': True}
    },
    'outreach_campaign': {
        'workflow': {
            'description': 'Startup outreach campaign workflow',
            'steps': [
                'Get startups from database matching criteria',
                'Research each startup for personalization',
                'Generate personalized outreach message',
                'Send outreach email',
                'Log outreach in database',
                'Track responses and update status'
            ],
            'best_practices': [
                'Mention specific recent news or achievements',
                'Keep messages under 150 words',
                'Include clear call-to-action',
                'Send Tuesday-Thursday 9-11am for best response',
                'Follow up after 3-4 days if no response'
            ]
        },
        'score': 0.80,
        'metadata': {'source': 'seed', 'validated': True}
    },
    'vc_matching': {
        'workflow': {
            'description': 'Startup-VC matching workflow',
            'steps': [
                'Get startup profile and requirements',
                'Search VCs matching sector and stage',
                'Score VCs by alignment',
                'Generate match recommendations',
                'Prepare intro materials'
            ],
            'best_practices': [
                'Match on sector, stage, and check size',
                'Consider geographic preferences',
                'Look at recent VC activity',
                'Prioritize VCs with portfolio synergies'
            ]
        },
        'score': 0.70,
        'metadata': {'source': 'seed'}
    }
}


def initialize_database():
    """Initialize the startup/VC database."""
    logger.info("Initializing startup database...")
    db = StartupDatabase()
    stats = db.get_stats()
    logger.info(f"Database ready: {stats['total_startups']} startups, {stats['total_vcs']} VCs")
    db.close()


def seed_procedural_memory(procedural_mem: ProceduralMemory) -> None:
    """Seed procedural memory with initial workflows (legacy path)."""
    logger.info("Seeding procedural memory with initial workflows...")
    for task_type, workflow_data in SEED_WORKFLOWS.items():
        procedural_mem.save_workflow(
            task_type=task_type,
            workflow=workflow_data['workflow'],
            performance_score=workflow_data['score'],
            metadata=workflow_data['metadata']
        )
    logger.info(f"Added {len(SEED_WORKFLOWS)} workflows")


async def seed_unified_store():
    """Seed memory through the new UnifiedStore."""
    from src.framework.storage.unified_store import UnifiedStore
    from src.framework.contracts import SemanticDocument, ConsensusEntry
    from src.framework.types import EntryType

    use_legacy = getattr(settings, "memory_use_legacy", False)
    data_dir = getattr(settings, "memory_data_dir", "data/memory")
    store = UnifiedStore(use_legacy_stores=use_legacy, data_dir=data_dir)

    # Seed procedural workflows
    for task_type, workflow_data in SEED_WORKFLOWS.items():
        await store.proc_save(
            task_type=task_type,
            workflow=workflow_data['workflow'],
            score=workflow_data['score'],
            created_by="seed_memory",
            provenance="initial seed",
        )

    # Seed a baseline consensus entry
    await store.cons_set(ConsensusEntry(
        key="strategy.outreach.best_time",
        value="Tuesday-Thursday 9-11am",
        entry_type=EntryType.STRATEGY,
        confidence=0.80,
        source_agent_id="seed_memory",
        source_evidence=["industry best practices"],
    ))

    proc_types = await store.proc_list_types()
    logger.info(f"Seeded {len(proc_types)} workflows via UnifiedStore")
    return store


def main_legacy():
    """Legacy initialisation path."""
    initialize_database()

    semantic_mem = SemanticMemory()
    episodic_mem = EpisodicMemory(settings.episodic_db_path)
    procedural_mem = ProceduralMemory(settings.procedural_json_path)

    logger.info("Clearing existing memory...")
    semantic_mem.clear()
    episodic_mem.clear()
    procedural_mem.clear()

    seed_procedural_memory(procedural_mem)

    logger.info("System initialization completed!")

    print("\n=== System Initialized (Legacy) ===")
    print(f"Semantic Memory: {semantic_mem.size()} documents")
    print(f"Episodic Memory: {len(episodic_mem.get_recent(limit=100))} episodes")
    print(f"Procedural Memory: {len(procedural_mem.get_all_workflows())} workflows")
    print("\nDatabase ready for data collection.")
    print("\nNext steps:")
    print("  1. Run simulation: python scripts/run_simulation.py")
    print("  2. The system will collect startup/VC data via web search")
    print("  3. Outreach campaigns will use collected data")


def main_unified():
    """New UnifiedStore initialisation path."""
    initialize_database()

    logger.info("Seeding via UnifiedStore...")
    asyncio.run(seed_unified_store())

    logger.info("System initialization completed!")
    print("\n=== System Initialized (UnifiedStore) ===")
    print("Procedural workflows seeded")
    print("Consensus baseline seeded")
    print("\nDatabase ready for data collection.")
    print("\nNext steps:")
    print("  1. Run simulation: python scripts/run_simulation.py")
    print("  2. The system will collect startup/VC data via web search")
    print("  3. Outreach campaigns will use collected data")


def main():
    """Main entry point. Pass --legacy for old code path."""
    import argparse
    parser = argparse.ArgumentParser(description="Initialize memory systems")
    parser.add_argument("--legacy", action="store_true", help="Use legacy memory systems")
    args = parser.parse_args()

    logger.info("Initializing autonomous startup system...")

    if args.legacy:
        main_legacy()
    else:
        main_unified()


if __name__ == "__main__":
    main()
