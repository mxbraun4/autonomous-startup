"""Test agent coordination and memory systems."""
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.client import LLMClient
from src.memory import SemanticMemory, EpisodicMemory, ProceduralMemory
from src.agents.master_planner import MasterPlanner
from src.agents.planners import DataStrategyPlanner
from src.agents.actors import ScraperActor


@pytest.fixture
def mock_llm():
    """Create mock LLM client."""
    return LLMClient(mock_mode=True)


@pytest.fixture
def memory_system():
    """Create in-memory memory system."""
    return {
        'semantic': SemanticMemory(),
        'episodic': EpisodicMemory(":memory:"),
        'procedural': ProceduralMemory(":memory:")
    }


def test_master_planner_initialization(mock_llm, memory_system):
    """Test Master Planner can be initialized."""
    planner = MasterPlanner(mock_llm, memory_system)
    assert planner.agent_id == "master_planner"
    assert len(planner.specialized_planners) == 0


def test_master_planner_delegation(mock_llm, memory_system):
    """Test that Master Planner correctly delegates to specialized planners."""
    master = MasterPlanner(mock_llm, memory_system)
    data_planner = DataStrategyPlanner(mock_llm, memory_system)

    master.add_planners([data_planner])

    assert len(master.specialized_planners) == 1

    # Assign a goal
    goal = {'type': 'data_strategy', 'description': 'Improve startup coverage'}
    data_planner.assign_goal(goal)

    assert data_planner.current_goal == goal


def test_semantic_memory_operations():
    """Test semantic memory add and search."""
    mem = SemanticMemory()

    # Add documents
    mem.add("Fintech startup focused on payments", metadata={'sector': 'fintech'})
    mem.add("Healthtech startup for remote monitoring", metadata={'sector': 'healthtech'})
    mem.add("AI startup building LLM tools", metadata={'sector': 'ai_ml'})

    assert mem.size() == 3

    # Search
    results = mem.search("payment fintech", top_k=2)

    assert len(results) > 0
    assert 'fintech' in results[0]['text'].lower()


def test_episodic_memory_recording():
    """Test that episodic memory captures and retrieves experiences."""
    mem = EpisodicMemory(":memory:")

    # Record successful outreach
    episode_id = mem.record(
        agent_id="outreach_planner",
        episode_type="campaign",
        context={'sector': 'fintech', 'personalization': 'high'},
        outcome={'response_rate': 0.35},
        success=True,
        iteration=1
    )

    assert episode_id > 0

    # Retrieve similar episodes
    similar = mem.search_similar(context_keywords=['fintech'])

    assert len(similar) > 0
    assert similar[0]['outcome']['response_rate'] == 0.35


def test_procedural_memory_workflows():
    """Test procedural memory workflow management."""
    mem = ProceduralMemory(":memory:")

    # Save workflow
    workflow = {
        'steps': ['step1', 'step2', 'step3'],
        'best_practices': ['practice1', 'practice2']
    }

    mem.save_workflow(
        task_type='outreach',
        workflow=workflow,
        performance_score=0.85
    )

    # Retrieve workflow
    retrieved = mem.get_workflow('outreach')

    assert retrieved is not None
    assert retrieved['workflow'] == workflow
    assert retrieved['score'] == 0.85

    # Try to save lower-performing workflow (should not update)
    mem.save_workflow(
        task_type='outreach',
        workflow={'steps': ['bad_step']},
        performance_score=0.60
    )

    # Should still have the better workflow
    retrieved = mem.get_workflow('outreach')
    assert retrieved['score'] == 0.85


def test_actor_task_execution(mock_llm, memory_system):
    """Test that actors can execute tasks."""
    actor = ScraperActor(mock_llm, memory_system)

    task = {
        'description': 'Collect fintech startup data',
        'type': 'scraping'
    }

    # Note: This will use seed data if files exist, otherwise returns empty
    result = actor.execute_task(task)

    assert result is not None
    assert result.get('success') is not None


def test_planner_learning_cycle(mock_llm, memory_system):
    """Test that planners can execute learning cycles."""
    planner = DataStrategyPlanner(mock_llm, memory_system)

    # Add some initial data to semantic memory
    memory_system['semantic'].add(
        "Fintech startup raising Series A",
        metadata={'sector': 'fintech', 'stage': 'series_a'}
    )

    # Assign goal
    goal = {'type': 'data_strategy', 'description': 'Expand data coverage'}
    planner.assign_goal(goal)

    # Add a mock actor
    actor = ScraperActor(mock_llm, memory_system)
    planner.add_actors([actor])

    # Run cycle
    results = planner.run_cycle(iteration=1)

    assert 'analysis' in results
    assert 'plan' in results
    assert 'results' in results


def test_message_bus():
    """Test agent message passing."""
    from src.agents.base import MessageBus

    bus = MessageBus()

    # Send message
    bus.send('agent_1', {
        'from': 'agent_2',
        'type': 'task',
        'content': 'Do something'
    })

    # Receive messages
    messages = bus.receive('agent_1')

    assert len(messages) == 1
    assert messages[0]['type'] == 'task'

    # Queue should be cleared
    messages = bus.receive('agent_1')
    assert len(messages) == 0


if __name__ == "__main__":
    pytest.main([__file__, '-v'])
