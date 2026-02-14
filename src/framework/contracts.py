"""Pydantic V2 data models for all five memory types."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.framework.types import (
    ConsensusStatus,
    EntryType,
    EpisodeType,
    ItemType,
    MemoryType,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class BaseMemoryEntity(BaseModel):
    """Base for all memory entities (Layer A fields)."""

    entity_id: str = Field(default_factory=_new_id)
    run_id: Optional[str] = None
    cycle_id: Optional[int] = None
    timestamp_utc: datetime = Field(default_factory=_utc_now)
    version: int = 1
    status: str = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


# ---------------------------------------------------------------------------
# Working Memory
# ---------------------------------------------------------------------------


class WorkingMemoryItem(BaseMemoryEntity):
    """Per-agent active context kept in memory."""

    agent_id: str
    item_type: ItemType
    content: Dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 1.0
    ttl_seconds: Optional[int] = None
    source_memory_type: Optional[MemoryType] = None
    source_entity_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Semantic Memory
# ---------------------------------------------------------------------------


class SemanticDocument(BaseMemoryEntity):
    """Document stored in vector store for similarity search."""

    text: str
    collection: str = "semantic_default"
    document_type: str = "general"
    tags: List[str] = Field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Episodic Memory
# ---------------------------------------------------------------------------


class Episode(BaseMemoryEntity):
    """Record of an agent action and its outcome."""

    agent_id: str
    episode_type: EpisodeType = EpisodeType.GENERAL
    context: Dict[str, Any] = Field(default_factory=dict)
    action: str = ""
    outcome: Dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    summary_text: str = ""
    tags: List[str] = Field(default_factory=list)
    iteration: int = 0


# ---------------------------------------------------------------------------
# Procedural Memory
# ---------------------------------------------------------------------------


class ProcedureVersion(BaseModel):
    """A single version snapshot of a procedure."""

    version: int
    workflow: Dict[str, Any]
    score: float = 0.0
    created_by: str = ""
    provenance: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class Procedure(BaseMemoryEntity):
    """A versioned procedure/workflow for a task type."""

    task_type: str
    current_version: int = 1
    versions: List[ProcedureVersion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Consensus Memory
# ---------------------------------------------------------------------------


class ConsensusEntry(BaseMemoryEntity):
    """A shared-knowledge entry agreed upon by agents."""

    key: str  # namespaced, e.g. "strategy.outreach.best_time"
    value: Any = None
    entry_type: EntryType = EntryType.FACT
    confidence: float = 1.0
    source_agent_id: str = ""
    source_evidence: List[str] = Field(default_factory=list)
    supersedes: Optional[str] = None  # entity_id of the entry this replaces
    consensus_status: ConsensusStatus = ConsensusStatus.APPROVED
