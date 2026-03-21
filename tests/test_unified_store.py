"""Tests for UnifiedStore CRUD across episodic, procedural, and consensus memory types."""

import pytest

from src.framework.contracts import (
    ConsensusEntry,
    Episode,
)
from src.framework.storage.unified_store import UnifiedStore
from src.framework.storage.sync_wrapper import SyncUnifiedStore
from src.framework.types import (
    EntryType,
    EpisodeType,
)


@pytest.fixture
def store(tmp_path):
    """Create a UnifiedStore in a temp directory."""
    return UnifiedStore(data_dir=str(tmp_path))


@pytest.fixture
def sync_store(store):
    return SyncUnifiedStore(store)


# -----------------------------------------------------------------------
# Episodic Memory
# -----------------------------------------------------------------------

class TestEpisodicMemory:
    def test_record_and_search(self, sync_store):
        ep = Episode(
            agent_id="data_expert",
            episode_type=EpisodeType.DATA_COLLECTION,
            context={"sector": "fintech"},
            outcome={"startups_found": 5},
            success=True,
        )
        eid = sync_store.ep_record(ep)
        assert eid

        results = sync_store.ep_search_structured(
            agent_id="data_expert",
            episode_type=EpisodeType.DATA_COLLECTION,
        )
        assert len(results) >= 1

    def test_success_rate(self, sync_store):
        sync_store.ep_record(Episode(
            agent_id="a", episode_type=EpisodeType.OUTREACH,
            success=True, context={}, outcome={},
        ))
        sync_store.ep_record(Episode(
            agent_id="a", episode_type=EpisodeType.OUTREACH,
            success=False, context={}, outcome={},
        ))
        rate = sync_store.ep_get_success_rate("a", EpisodeType.OUTREACH)
        assert 0.4 <= rate <= 0.6


# -----------------------------------------------------------------------
# Procedural Memory
# -----------------------------------------------------------------------

class TestProceduralMemory:
    def test_save_and_get(self, sync_store):
        proc = sync_store.proc_save(
            task_type="test_workflow",
            workflow={"steps": ["step1", "step2"]},
            score=0.75,
        )
        assert proc is not None
        assert proc.task_type == "test_workflow"

        retrieved = sync_store.proc_get("test_workflow")
        assert retrieved is not None

    def test_list_types(self, sync_store):
        sync_store.proc_save("type_a", {"steps": ["a"]}, 0.5)
        sync_store.proc_save("type_b", {"steps": ["b"]}, 0.6)
        types = sync_store.proc_list_types()
        assert "type_a" in types
        assert "type_b" in types


# -----------------------------------------------------------------------
# Consensus Memory
# -----------------------------------------------------------------------

class TestConsensusMemory:
    def test_set_and_get(self, sync_store):
        entry = ConsensusEntry(
            key="strategy.email.time",
            value="Tuesday 10am",
            entry_type=EntryType.STRATEGY,
            confidence=0.9,
        )
        eid = sync_store.cons_set(entry)
        assert eid

        result = sync_store.cons_get("strategy.email.time")
        assert result is not None
        assert result.value == "Tuesday 10am"

    def test_supersedes(self, sync_store):
        e1 = ConsensusEntry(key="k", value="v1", entry_type=EntryType.FACT)
        sync_store.cons_set(e1)
        e2 = ConsensusEntry(key="k", value="v2", entry_type=EntryType.FACT)
        sync_store.cons_set(e2)

        current = sync_store.cons_get("k")
        assert current.value == "v2"

        history = sync_store.cons_history("k")
        assert len(history) == 2

    def test_propose_and_approve(self, sync_store):
        proposed = ConsensusEntry(
            key="decision.pivot",
            value="yes",
            entry_type=EntryType.DECISION,
        )
        eid = sync_store.cons_propose(proposed)

        # Before approval, cons_get returns None (no approved entry)
        assert sync_store.cons_get("decision.pivot") is None

        # Approve
        assert sync_store.cons_approve(eid) is True

        # Now it's available
        result = sync_store.cons_get("decision.pivot")
        assert result is not None
        assert result.value == "yes"

    def test_list_with_prefix(self, sync_store):
        sync_store.cons_set(ConsensusEntry(key="strategy.a", value=1, entry_type=EntryType.STRATEGY))
        sync_store.cons_set(ConsensusEntry(key="strategy.b", value=2, entry_type=EntryType.STRATEGY))
        sync_store.cons_set(ConsensusEntry(key="fact.x", value=3, entry_type=EntryType.FACT))

        strats = sync_store.cons_list(prefix="strategy.")
        assert len(strats) == 2

        facts = sync_store.cons_list(entry_type=EntryType.FACT)
        assert len(facts) == 1


# -----------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------

class TestLifecycle:
    def test_run_lifecycle(self, sync_store):
        sync_store.start_run("run_001")
        sync_store.end_run("run_001")
