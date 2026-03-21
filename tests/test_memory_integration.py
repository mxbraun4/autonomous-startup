"""End-to-end integration tests exercising episodic, procedural, and consensus memory through UnifiedStore.

These tests use the new backends (not legacy), hitting real ChromaDB and SQLite.
"""

import asyncio
import os
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
    s = UnifiedStore(data_dir=str(tmp_path))
    return SyncUnifiedStore(s)


# -----------------------------------------------------------------------
# Episodic (SQLite v2 + ChromaDB)
# -----------------------------------------------------------------------

class TestEpisodicIntegration:
    def test_record_and_structured_search(self, store):
        store.ep_record(Episode(
            agent_id="data_expert",
            episode_type=EpisodeType.DATA_COLLECTION,
            context={"sector": "fintech", "query": "seed stage"},
            action="web_search",
            outcome={"startups_found": 5},
            success=True,
            summary_text="Searched for fintech seed-stage startups, found 5 results",
        ))
        store.ep_record(Episode(
            agent_id="developer",
            episode_type=EpisodeType.GENERAL,
            context={"target": "startup_x"},
            action="build_feature",
            outcome={"result": "completed"},
            success=True,
            summary_text="Built matching feature for startup_x, completed successfully",
        ))

        # Structured search
        data_episodes = store.ep_search_structured(
            agent_id="data_expert",
            episode_type=EpisodeType.DATA_COLLECTION,
        )
        assert len(data_episodes) == 1
        assert data_episodes[0].success is True

    def test_semantic_episode_search(self, store):
        store.ep_record(Episode(
            agent_id="a1",
            episode_type=EpisodeType.DATA_COLLECTION,
            context={},
            action="scraped fintech startups",
            outcome={"count": 10},
            success=True,
            summary_text="Successfully scraped 10 fintech startups from Y Combinator directory",
        ))
        store.ep_record(Episode(
            agent_id="a1",
            episode_type=EpisodeType.GENERAL,
            context={},
            action="built healthtech landing page",
            outcome={"pages": 5},
            success=False,
            summary_text="Built landing pages for 5 healthtech companies, QA failed",
        ))

        results = store.ep_search_similar("fintech scraping Y Combinator")
        assert len(results) >= 1

    def test_success_rate(self, store):
        for success in [True, True, False, True]:
            store.ep_record(Episode(
                agent_id="a1",
                episode_type=EpisodeType.GENERAL,
                context={},
                outcome={},
                success=success,
            ))
        rate = store.ep_get_success_rate("a1", EpisodeType.GENERAL)
        assert 0.7 <= rate <= 0.8

    def test_get_by_id(self, store):
        ep = Episode(
            agent_id="a1",
            episode_type=EpisodeType.GENERAL,
            context={"test": True},
            outcome={"result": "ok"},
            success=True,
        )
        eid = store.ep_record(ep)
        result = store.ep_get(eid)
        assert result is not None
        assert result.context["test"] is True


# -----------------------------------------------------------------------
# Procedural (Versioned SQLite)
# -----------------------------------------------------------------------

class TestProceduralIntegration:
    def test_versioning(self, store):
        store.proc_save("data_collection", {"steps": ["a"]}, score=0.5, created_by="seed")
        store.proc_save("data_collection", {"steps": ["a", "b"]}, score=0.75, created_by="agent")

        proc = store.proc_get("data_collection")
        assert proc is not None
        assert proc.current_version == 2
        assert len(proc.versions) == 2
        # Active version should be v2
        active = [v for v in proc.versions if v.is_active]
        assert len(active) == 1
        assert active[0].version == 2
        assert active[0].score == 0.75

    def test_list_types(self, store):
        store.proc_save("type_a", {"s": 1}, 0.5)
        store.proc_save("type_b", {"s": 2}, 0.6)
        types = store.proc_list_types()
        assert set(types) == {"type_a", "type_b"}


# -----------------------------------------------------------------------
# Consensus
# -----------------------------------------------------------------------

class TestConsensusIntegration:
    def test_full_lifecycle(self, store):
        # Set initial value
        store.cons_set(ConsensusEntry(
            key="strategy.batch_size",
            value=20,
            entry_type=EntryType.PARAMETER,
            confidence=0.8,
            source_agent_id="coordinator",
        ))

        # Read it back
        result = store.cons_get("strategy.batch_size")
        assert result is not None
        assert result.value == 20

        # Update (supersede)
        store.cons_set(ConsensusEntry(
            key="strategy.batch_size",
            value=50,
            entry_type=EntryType.PARAMETER,
            confidence=0.95,
            source_agent_id="data_expert",
        ))

        result = store.cons_get("strategy.batch_size")
        assert result.value == 50

        # History should show both
        history = store.cons_history("strategy.batch_size")
        assert len(history) == 2

    def test_propose_approve_workflow(self, store):
        # Propose a decision
        eid = store.cons_propose(ConsensusEntry(
            key="decision.target_sector",
            value="fintech",
            entry_type=EntryType.DECISION,
            source_agent_id="product_expert",
        ))

        # Not yet approved
        assert store.cons_get("decision.target_sector") is None

        # Approve
        store.cons_approve(eid)
        result = store.cons_get("decision.target_sector")
        assert result is not None
        assert result.value == "fintech"


# -----------------------------------------------------------------------
# Cross-tier: Episodic + Procedural + Consensus
# -----------------------------------------------------------------------

class TestCrossTierIntegration:
    def test_run_lifecycle_with_all_tiers(self, store):
        store.start_run("run_001")

        # Record episode
        store.ep_record(Episode(
            agent_id="data_expert",
            episode_type=EpisodeType.DATA_COLLECTION,
            context={"target": "fintech"},
            action="web_search",
            outcome={"found": 3},
            success=True,
            summary_text="Found 3 fintech startups",
        ))

        # Record a procedure
        store.proc_save(
            "data_collection",
            {"steps": ["search", "validate", "save"]},
            score=0.8,
        )

        # Set consensus
        store.cons_set(ConsensusEntry(
            key="strategy.target_sector",
            value="fintech",
            entry_type=EntryType.STRATEGY,
            confidence=0.9,
        ))

        store.end_run("run_001")

        # Verify everything persisted
        assert store.ep_get_success_rate("data_expert") == 1.0
        assert store.proc_get("data_collection") is not None
        assert store.cons_get("strategy.target_sector").value == "fintech"
