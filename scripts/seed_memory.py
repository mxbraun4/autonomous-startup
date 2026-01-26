"""Initialize memory systems and database."""
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


def initialize_database():
    """Initialize the startup/VC database."""
    logger.info("Initializing startup database...")
    db = StartupDatabase()
    stats = db.get_stats()
    logger.info(f"Database ready: {stats['total_startups']} startups, {stats['total_vcs']} VCs")
    db.close()


def seed_procedural_memory(procedural_mem: ProceduralMemory) -> None:
    """Seed procedural memory with initial workflows."""
    logger.info("Seeding procedural memory with initial workflows...")

    workflows = {
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

    for task_type, workflow_data in workflows.items():
        procedural_mem.save_workflow(
            task_type=task_type,
            workflow=workflow_data['workflow'],
            performance_score=workflow_data['score'],
            metadata=workflow_data['metadata']
        )

    logger.info(f"Added {len(workflows)} workflows")


def main():
    """Main function to initialize all systems."""
    logger.info("Initializing autonomous startup system...")

    # Initialize database
    initialize_database()

    # Initialize memory systems
    semantic_mem = SemanticMemory()
    episodic_mem = EpisodicMemory(settings.episodic_db_path)
    procedural_mem = ProceduralMemory(settings.procedural_json_path)

    # Clear and seed procedural memory
    logger.info("Clearing existing memory...")
    semantic_mem.clear()
    episodic_mem.clear()
    procedural_mem.clear()

    seed_procedural_memory(procedural_mem)

    logger.info("System initialization completed!")

    # Print summary
    print("\n=== System Initialized ===")
    print(f"Semantic Memory: {semantic_mem.size()} documents")
    print(f"Episodic Memory: {len(episodic_mem.get_recent(limit=100))} episodes")
    print(f"Procedural Memory: {len(procedural_mem.get_all_workflows())} workflows")
    print("\nDatabase ready for data collection.")
    print("\nNext steps:")
    print("  1. Run simulation: python scripts/run_simulation.py")
    print("  2. The system will collect startup/VC data via web search")
    print("  3. Outreach campaigns will use collected data")


if __name__ == "__main__":
    main()
