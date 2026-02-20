"""End-to-end integration tests exercising all 5 memory types through UnifiedStore.

These tests use the new backends (not legacy), hitting real ChromaDB and SQLite.
"""

import asyncio
import os
import pytest

from src.framework.contracts import (
    ConsensusEntry,
    Episode,
    SemanticDocument,
    WorkingMemoryItem,
)
from src.framework.storage.unified_store import UnifiedStore
from src.framework.storage.sync_wrapper import SyncUnifiedStore
from src.framework.types import (
    EntryType,
    EpisodeType,
    ItemType,
)


@pytest.fixture
def store(tmp_path):
    """Create a UnifiedStore in a temp directory."""
    s = UnifiedStore(data_dir=str(tmp_path))
    return SyncUnifiedStore(s)


# -----------------------------------------------------------------------
# Semantic (ChromaDB)
# -----------------------------------------------------------------------

class TestSemanticIntegration:
    def test_add_search_delete(self, store):
        store.sem_add(SemanticDocument(
            text="Stripe is a fintech company providing payment infrastructure",
            collection="semantic_startups",
            tags=["fintech", "payments"],
            source="web",
        ))
        store.sem_add(SemanticDocument(
            text="Moderna develops mRNA vaccines for infectious diseases",
            collection="semantic_startups",
            tags=["healthtech", "biotech"],
            source="web",
        ))

        results = store.sem_search("payment processing fintech", collection="semantic_startups", top_k=2)
        assert len(results) >= 1
        # The fintech doc should rank higher
        assert "fintech" in results[0].tags or "payment" in results[0].text.lower()

    def test_count_by_collection(self, store):
        store.sem_add(SemanticDocument(text="doc1", collection="col_a"))
        store.sem_add(SemanticDocument(text="doc2", collection="col_a"))
        store.sem_add(SemanticDocument(text="doc3", collection="col_b"))

        assert store.sem_count("col_a") == 2
        assert store.sem_count("col_b") == 1

    def test_get_by_id(self, store):
        doc = SemanticDocument(text="identifiable document", collection="semantic_default")
        eid = store.sem_add(doc)
        result = store.sem_get(eid)
        assert result is not None
        assert result.text == "identifiable document"


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
            agent_id="outreach_expert",
            episode_type=EpisodeType.OUTREACH,
            context={"target": "startup_x"},
            action="send_email",
            outcome={"response": "interested"},
            success=True,
            summary_text="Sent personalised email to startup_x, they expressed interest",
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
            episode_type=EpisodeType.OUTREACH,
            context={},
            action="sent emails to healthtech companies",
            outcome={"sent": 5},
            success=False,
            summary_text="Sent outreach to 5 healthtech companies, no responses received",
        ))

        results = store.ep_search_similar("fintech scraping Y Combinator")
        assert len(results) >= 1

    def test_success_rate(self, store):
        for success in [True, True, False, True]:
            store.ep_record(Episode(
                agent_id="a1",
                episode_type=EpisodeType.OUTREACH,
                context={},
                outcome={},
                success=success,
            ))
        rate = store.ep_get_success_rate("a1", EpisodeType.OUTREACH)
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

    def test_rollback(self, store):
        store.proc_save("wf", {"v": 1}, score=0.5)
        store.proc_save("wf", {"v": 2}, score=0.6)
        store.proc_save("wf", {"v": 3}, score=0.7)

        # Rollback to v1
        result = store.proc_rollback("wf", 1)
        assert result is not None
        assert result.current_version == 1

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
# Cross-tier: Working + Episodic + Consensus
# -----------------------------------------------------------------------

class TestCrossTierIntegration:
    def test_run_lifecycle_with_all_tiers(self, store):
        store.start_run("run_001")

        # Working memory
        store.wm_put(WorkingMemoryItem(
            agent_id="coordinator",
            item_type=ItemType.TASK_STATE,
            content={"phase": "build", "iteration": 1},
        ))

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

        # Store semantic knowledge
        store.sem_add(SemanticDocument(
            text="Fintech sector is growing 15% YoY in 2024",
            collection="semantic_default",
            tags=["fintech", "market_data"],
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
        assert len(store.wm_list("coordinator")) == 1
        assert store.ep_get_success_rate("data_expert") == 1.0
        assert store.sem_count() >= 1
        assert store.proc_get("data_collection") is not None
        assert store.cons_get("strategy.target_sector").value == "fintech"

    def test_working_memory_from_semantic(self, store):
        """Simulate pulling a fact from semantic into working memory."""
        store.sem_add(SemanticDocument(
            entity_id="sem_doc_1",
            text="Stripe processes $1T in payments annually",
            tags=["fintech"],
        ))

        # Agent pulls this into working memory
        store.wm_put(WorkingMemoryItem(
            agent_id="outreach_expert",
            item_type=ItemType.RETRIEVED_FACT,
            content={"fact": "Stripe processes $1T in payments annually"},
            source_memory_type="semantic",
            source_entity_id="sem_doc_1",
        ))

        items = store.wm_list("outreach_expert", item_type=ItemType.RETRIEVED_FACT)
        assert len(items) == 1
        assert items[0].source_entity_id == "sem_doc_1"
