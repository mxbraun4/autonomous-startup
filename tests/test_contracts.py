"""Tests for contract models: serialisation, validation, defaults."""

import json
from datetime import datetime, timezone

from src.framework.contracts import (
    BaseMemoryEntity,
    ConsensusEntry,
    Episode,
    Procedure,
    ProcedureVersion,
)
from src.framework.types import (
    ConsensusStatus,
    EntryType,
    EpisodeType,
)


class TestBaseMemoryEntity:
    def test_defaults(self):
        e = BaseMemoryEntity()
        assert len(e.entity_id) == 16
        assert e.version == 1
        assert e.status == "active"
        assert e.run_id is None
        assert isinstance(e.timestamp_utc, datetime)

    def test_json_round_trip(self):
        e = BaseMemoryEntity(run_id="r1", cycle_id=3)
        data = e.model_dump(mode="json")
        restored = BaseMemoryEntity.model_validate(data)
        assert restored.run_id == "r1"
        assert restored.cycle_id == 3


class TestEpisode:
    def test_creation(self):
        ep = Episode(
            agent_id="developer",
            episode_type=EpisodeType.GENERAL,
            context={"target": "startup_x"},
            action="built_feature",
            outcome={"result": "completed"},
            success=True,
            summary_text="Built feature for startup_x, completed successfully",
        )
        assert ep.success is True
        assert ep.action == "built_feature"

    def test_episode_type_enum(self):
        ep = Episode(agent_id="a", episode_type=EpisodeType.DATA_COLLECTION)
        assert ep.episode_type.value == "data_collection"


class TestProcedure:
    def test_versioned(self):
        v1 = ProcedureVersion(version=1, workflow={"steps": ["a"]}, score=0.5)
        v2 = ProcedureVersion(version=2, workflow={"steps": ["a", "b"]}, score=0.8, is_active=True)
        proc = Procedure(task_type="data_collection", current_version=2, versions=[v1, v2])
        assert proc.current_version == 2
        assert len(proc.versions) == 2
        assert proc.versions[1].score == 0.8


class TestConsensusEntry:
    def test_creation(self):
        entry = ConsensusEntry(
            key="strategy.target_sector",
            value="fintech",
            entry_type=EntryType.STRATEGY,
            confidence=0.85,
            source_agent_id="coordinator",
        )
        assert entry.key == "strategy.target_sector"
        assert entry.consensus_status == ConsensusStatus.APPROVED

    def test_proposed_status(self):
        entry = ConsensusEntry(
            key="param.batch_size",
            value=50,
            entry_type=EntryType.PARAMETER,
            consensus_status=ConsensusStatus.PROPOSED,
        )
        assert entry.consensus_status == ConsensusStatus.PROPOSED

    def test_json_round_trip(self):
        entry = ConsensusEntry(
            key="fact.market_size",
            value={"amount": 1_000_000, "currency": "USD"},
            entry_type=EntryType.FACT,
        )
        data = json.loads(entry.model_dump_json())
        restored = ConsensusEntry.model_validate(data)
        assert restored.value["amount"] == 1_000_000
