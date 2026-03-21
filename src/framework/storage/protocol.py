"""Abstract protocol defining the unified memory store interface.

All methods are async to future-proof for daemon mode.
Method prefixes: ep_ (episodic), proc_ (procedural), cons_ (consensus).
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from src.framework.contracts import (
    ConsensusEntry,
    Episode,
    Procedure,
)
from src.framework.types import EntryType, EpisodeType


class MemoryStoreProtocol(abc.ABC):
    """Abstract interface for the unified memory store.

    Implementors: UnifiedStore (in-process), HttpMemoryClient (future daemon).
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def start_run(self, run_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Signal the beginning of an agent run / cycle."""

    @abc.abstractmethod
    async def end_run(self, run_id: str) -> None:
        """Signal the end of an agent run / cycle."""

    # ------------------------------------------------------------------
    # Episodic Memory (ep_*)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def ep_record(self, episode: Episode) -> str:
        """Record a new episode. Returns entity_id."""

    @abc.abstractmethod
    async def ep_get(self, entity_id: str) -> Optional[Episode]:
        """Retrieve an episode by ID."""

    @abc.abstractmethod
    async def ep_search_similar(
        self,
        query: str,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        top_k: int = 10,
    ) -> List[Episode]:
        """Semantic similarity search over episode summaries."""

    @abc.abstractmethod
    async def ep_search_structured(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> List[Episode]:
        """Structured (SQL-style) search over episodes."""

    @abc.abstractmethod
    async def ep_get_success_rate(
        self,
        agent_id: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
    ) -> float:
        """Calculate success rate for matching episodes."""

    # ------------------------------------------------------------------
    # Procedural Memory (proc_*)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def proc_save(
        self,
        task_type: str,
        workflow: Dict[str, Any],
        score: float = 0.0,
        created_by: str = "",
        provenance: str = "",
    ) -> Procedure:
        """Save a new version of a procedure. Auto-increments version."""

    @abc.abstractmethod
    async def proc_get(self, task_type: str) -> Optional[Procedure]:
        """Get the active procedure for a task type."""

    @abc.abstractmethod
    async def proc_get_history(self, task_type: str) -> List[Procedure]:
        """Get all versions of a procedure."""

    @abc.abstractmethod
    async def proc_list_types(self) -> List[str]:
        """List all known task types."""

    # ------------------------------------------------------------------
    # Consensus Memory (cons_*)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def cons_set(self, entry: ConsensusEntry) -> str:
        """Set (approve) a consensus entry. Returns entity_id."""

    @abc.abstractmethod
    async def cons_get(self, key: str) -> Optional[ConsensusEntry]:
        """Get the current (active) entry for a key."""

    @abc.abstractmethod
    async def cons_propose(self, entry: ConsensusEntry) -> str:
        """Propose a new entry (status=proposed). Returns entity_id."""

    @abc.abstractmethod
    async def cons_approve(self, entity_id: str) -> bool:
        """Approve a proposed entry. Returns True on success."""

    @abc.abstractmethod
    async def cons_list(
        self,
        prefix: Optional[str] = None,
        entry_type: Optional[EntryType] = None,
    ) -> List[ConsensusEntry]:
        """List consensus entries, optionally filtered by key prefix or type."""

    @abc.abstractmethod
    async def cons_history(self, key: str) -> List[ConsensusEntry]:
        """Get full history for a consensus key (including superseded)."""
