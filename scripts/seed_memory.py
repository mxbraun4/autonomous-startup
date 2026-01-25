"""Seed memory systems with initial data."""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory import SemanticMemory, EpisodicMemory, ProceduralMemory
from src.utils.config import settings
from src.utils.logging import setup_logging, get_logger

setup_logging(settings.log_level)
logger = get_logger(__name__)


def load_json_file(path: str) -> list:
    """Load JSON file.

    Args:
        path: Path to file

    Returns:
        List of items
    """
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load {path}: {e}")
        return []


def seed_semantic_memory(semantic_mem: SemanticMemory) -> None:
    """Seed semantic memory with knowledge and data.

    Args:
        semantic_mem: Semantic memory instance
    """
    logger.info("Seeding semantic memory...")

    # Load and add knowledge documents
    knowledge_docs = load_json_file(settings.seed_knowledge_path)
    for doc in knowledge_docs:
        semantic_mem.add(
            text=f"{doc['topic']}: {doc['content']}",
            metadata={
                'type': 'knowledge',
                'category': doc.get('category'),
                'topic': doc.get('topic')
            }
        )

    logger.info(f"Added {len(knowledge_docs)} knowledge documents")

    # Load and add startup data
    startups = load_json_file(settings.seed_startups_path)
    for startup in startups:
        text = (
            f"{startup.get('name', 'Unknown')} - {startup.get('sector', 'Unknown')} startup. "
            f"{startup.get('description', '')} "
            f"Stage: {startup.get('stage', 'Unknown')}. "
            f"Location: {startup.get('location', 'Unknown')}. "
            f"Recent: {startup.get('recent_news', '')}"
        )
        semantic_mem.add(text=text, metadata={**startup, 'type': 'startup'})

    logger.info(f"Added {len(startups)} startups")

    # Load and add VC data
    vcs = load_json_file(settings.seed_vcs_path)
    for vc in vcs:
        sectors = ', '.join(vc.get('sectors', []))
        text = (
            f"{vc.get('name', 'Unknown')} - VC firm focusing on {sectors}. "
            f"Stage focus: {vc.get('stage_focus', 'Unknown')}. "
            f"Check size: {vc.get('check_size', 'Unknown')}. "
            f"Recent: {vc.get('recent_activity', '')}"
        )
        semantic_mem.add(text=text, metadata={**vc, 'type': 'vc'})

    logger.info(f"Added {len(vcs)} VCs")

    logger.info(f"Total semantic memory size: {semantic_mem.size()} documents")


def seed_episodic_memory(episodic_mem: EpisodicMemory) -> None:
    """Seed episodic memory with sample experiences.

    Args:
        episodic_mem: Episodic memory instance
    """
    logger.info("Seeding episodic memory with sample episodes...")

    # Add sample successful episodes to bootstrap learning
    sample_episodes = [
        {
            'agent_id': 'outreach_strategy_planner',
            'episode_type': 'outreach_campaign',
            'context': {
                'target': 'fintech',
                'personalization': 'high',
                'timing': 'Tuesday morning'
            },
            'outcome': {
                'response_rate': 0.35,
                'interested': 7,
                'total_sent': 20
            },
            'success': True
        },
        {
            'agent_id': 'data_strategy_planner',
            'episode_type': 'data_collection',
            'context': {
                'target_sector': 'healthtech',
                'source': 'Crunchbase'
            },
            'outcome': {
                'collected': 50,
                'quality_score': 0.95
            },
            'success': True
        },
        {
            'agent_id': 'product_strategy_planner',
            'episode_type': 'tool_building',
            'context': {
                'tool': 'startup_matcher',
                'complexity': 'medium'
            },
            'outcome': {
                'build_time': '2_hours',
                'test_pass_rate': 0.90
            },
            'success': True
        }
    ]

    for episode in sample_episodes:
        episodic_mem.record(
            agent_id=episode['agent_id'],
            episode_type=episode['episode_type'],
            context=episode['context'],
            outcome=episode['outcome'],
            success=episode['success'],
            iteration=0
        )

    logger.info(f"Added {len(sample_episodes)} sample episodes")


def seed_procedural_memory(procedural_mem: ProceduralMemory) -> None:
    """Seed procedural memory with initial workflows.

    Args:
        procedural_mem: Procedural memory instance
    """
    logger.info("Seeding procedural memory with initial workflows...")

    # Add sample workflows
    workflows = {
        'outreach_campaign': {
            'workflow': {
                'description': 'Proven outreach campaign workflow',
                'steps': [
                    'Identify high-potential targets',
                    'Research recent news and context',
                    'Generate personalized messages (under 150 words)',
                    'Send Tuesday-Thursday 9-11am',
                    'Follow up after 3-4 days'
                ],
                'best_practices': [
                    'Mention specific recent news or achievements',
                    'Highlight relevant VC matches',
                    'Include clear call-to-action',
                    'Keep tone professional but friendly'
                ]
            },
            'score': 0.75,
            'metadata': {'source': 'seed', 'validated': True}
        },
        'data_collection': {
            'workflow': {
                'description': 'Data collection workflow',
                'steps': [
                    'Identify data gaps',
                    'Prioritize by VC interest alignment',
                    'Define scraping targets and criteria',
                    'Collect data',
                    'Validate quality',
                    'Store in semantic memory'
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
    """Main function to seed all memory systems."""
    logger.info("Starting memory seeding process...")

    # Initialize memory systems
    semantic_mem = SemanticMemory()
    episodic_mem = EpisodicMemory(settings.episodic_db_path)
    procedural_mem = ProceduralMemory(settings.procedural_json_path)

    # Clear existing data
    logger.info("Clearing existing memory...")
    semantic_mem.clear()
    episodic_mem.clear()
    procedural_mem.clear()

    # Seed each memory type
    seed_semantic_memory(semantic_mem)
    seed_episodic_memory(episodic_mem)
    seed_procedural_memory(procedural_mem)

    logger.info("Memory seeding completed successfully!")

    # Print summary
    print("\n=== Memory Systems Summary ===")
    print(f"Semantic Memory: {semantic_mem.size()} documents")
    print(f"Episodic Memory: {len(episodic_mem.get_recent(limit=100))} episodes")
    print(f"Procedural Memory: {len(procedural_mem.get_all_workflows())} workflows")
    print("\nReady to run simulation!")


if __name__ == "__main__":
    main()
